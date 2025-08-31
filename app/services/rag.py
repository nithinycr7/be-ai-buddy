from __future__ import annotations

from typing import List, Dict, Any, Optional
from openai import AzureOpenAI
from ..core.config import settings
from ..db.mongo import get_db  # expects Motor (async) DB
from pymongo.errors import PyMongoError

# ----------------------------
# OpenAI / Azure OpenAI Client
# ----------------------------

_client: AzureOpenAI | None = None

def _client_fn() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=getattr(settings, "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        )
    return _client


# ----------------------------
# Embeddings (sync SDK usage)
# ----------------------------

async def embed(texts: List[str]) -> List[List[float]]:
    """
    Embed a list of texts using your configured Azure OpenAI embedding deployment.
    Returns list[list[float]] in the same order as inputs.
    """
    model_name = "text-embedding-3-large"
    deployment = "text-embedding-3-large"
    api_version = "2024-02-01"

    client_embedding = AzureOpenAI(
        api_version="2024-12-01-preview",
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY
    )
    if not texts:
        return []
  
    resp = client_embedding.embeddings.create(
        model=model_name,
        input=texts
    )
    # Sort by 'index' to preserve order (SDK should already do so, but be explicit)
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]


# ----------------------------
# Cosmos Mongo vCore Vector Index
# ----------------------------

_index_created = False

async def _ensure_vector_index(dimensions: int,
                               field: str = "embedding",
                               name: str = "embeddings_vector_idx",
                               kind: str = "vector-diskann",
                               similarity: str = "COS") -> None:
    """
    Create the Cosmos DB for MongoDB vCore vector index if it doesn't exist.
    Safe to call multiple times; duplicate index errors are ignored.
    """
    global _index_created
    if _index_created:
        return

    db = await get_db()
    try:
        # Create the vector index
        await db.command({
            "createIndexes": "cbse_docs",
            "indexes": [{
                "name": name,
                "key": { field: "cosmosSearch" },
                "cosmosSearchOptions": {
                    "kind": kind,           # "vector-diskann" (good default), "vector-hnsw" (M30+), or "vector-ivf"
                    "similarity": similarity,   # COS | L2 | IP
                    "dimensions": dimensions,
                    # Optional DiskANN tuning:
                    "maxDegree": 32,
                    "lBuild": 64,
                }
            }]
        })

        # Helpful scalar indexes for filter pre-conditions
        await db.command({
            "createIndexes": "cbse_docs",
            "indexes": [
                {"name": "class_no_idx", "key": {"class_no": 1}},
                {"name": "subject_idx",  "key": {"subject": 1}},
                {"name": "chapter_idx",  "key": {"chapter": 1}},
            ]
        })
        _index_created = True
    except PyMongoError as e:
        msg = str(e).lower()
        # Ignore if it already exists or if plan throws a harmless error on re-create
        if "already exists" in msg or "duplicate" in msg:
            _index_created = True
        else:
            # Log but don't break application flow
            print(f"[cosmos index create] non-fatal: {e}")
            _index_created = True  # avoid spamming attempts


# ----------------------------
# Upsert a single CBSE doc
# ----------------------------

async def upsert_cbse_doc(chapter: str, subject: str, class_no: int, text: str,
                          source_pdf: Optional[str] = None, page: Optional[int] = None) -> str:
    """
    Compute embedding, ensure the vector index exists, and upsert the document.
    Returns the inserted/updated document _id as a hex string.
    """
    db = await get_db()
    coll = db.cbse_docs

    vec = (await embed([text]))[0]
    await _ensure_vector_index(dimensions=len(vec))

    # Generate a stable _id from natural keys to keep upserts idempotent
    import hashlib
    base_key = f"{subject}|{class_no}|{chapter}|{page or ''}|{(source_pdf or '').split('/')[-1]}|{text[:64]}"
    _id = hashlib.sha1(base_key.encode("utf-8")).hexdigest()

    doc: Dict[str, Any] = {
        "_id": _id,
        "chapter": chapter,
        "subject": subject,
        "class_no": class_no,
        "text": text,
        "embedding": vec,
    }
    if source_pdf:
        doc["source_pdf"] = source_pdf
    if page is not None:
        doc["page"] = page

    await coll.update_one({"_id": _id}, {"$set": doc}, upsert=True)
    return _id


# ----------------------------
# Vector Search with cosmosSearch
# ----------------------------

async def search_cbse(query: str, class_no: int, subject: str, k: int = 4) -> List[Dict[str, Any]]:
    """
    Embed the query once, then run a $search.cosmosSearch pipeline with pre-filters.
    """
    db = await get_db()
    coll = db.cbse_docs

    # Get query vector and make sure index dimension matches (first call only)
    qvec = (await embed([query]))[0]
    await _ensure_vector_index(dimensions=len(qvec))

    # Build filter
    filt: Dict[str, Any] = {"$and": [
        {"class_no": {"$eq": class_no}},
        {"subject":  {"$eq": subject}},
    ]}

    pipeline = [
        {"$search": {
            "cosmosSearch": {
                "path": "embedding",
                "vector": qvec,
                "k": k,
                "filter": filt,
            }
        }},
        {"$project": {
            "_id": 0,
            "text": 1,
            "chapter": 1,
            "subject": 1,
            "class_no": 1,
            "page": 1,
            "source_pdf": 1
        }}
    ]

    cursor = coll.aggregate(pipeline)
    results: List[Dict[str, Any]] = []
    async for doc in cursor:
        results.append(doc)
    return results


# ----------------------------
# RAG: retrieve + generate
# ----------------------------

async def answer_with_rag(query: str, class_no: int, subject: str) -> str:
    """
    Retrieve top-k matching chunks and answer strictly from those.
    """
    chunks = await search_cbse(query, class_no, subject, k=4)
    context = "\n\n".join([c["text"] for c in chunks]) if chunks else ""

    client = _client_fn()
    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": "Answer using ONLY the provided context. If the answer isn't in the context, say you don't know. Cite with [1], [2], etc."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()
