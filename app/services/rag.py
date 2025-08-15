from openai import AzureOpenAI
from ..core.config import settings
from ..db.mongo import get_db
from typing import List, Dict, Any
import numpy as np

_client: AzureOpenAI | None = None

def _client_fn() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version="2024-08-01-preview"
        )
    return _client

async def embed(texts: List[str]) -> List[List[float]]:
    client = _client_fn()
    resp = client.embeddings.create(
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        input=texts
    )
    return [item.embedding for item in resp.data]

async def upsert_cbse_doc(chapter: str, subject: str, class_no: int, text: str) -> str:
    db = await get_db()
    vec = (await embed([text]))[0]
    doc = {"chapter": chapter, "subject": subject, "class_no": class_no, "text": text, "embedding": vec}
    res = await db.cbse_docs.insert_one(doc)
    return str(res.inserted_id)

async def search_cbse(query: str, class_no: int, subject: str, k: int = 4) -> List[Dict[str, Any]]:
    # If Atlas Vector Search is configured, use $vectorSearch:
    db = await get_db()
    qvec = (await embed([query]))[0]
    try:
        pipeline = [
            {"$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": qvec,
                "numCandidates": 200,
                "limit": k,
                "filter": {"class_no": class_no, "subject": subject}
            }},
            {"$project": {"text":1, "chapter":1, "class_no":1, "subject":1, "_id":0}}
        ]
        cursor = db.cbse_docs.aggregate(pipeline)
        return [doc async for doc in cursor]
    except Exception:
        # Fallback: naive top-k by dot product (only for small datasets)
        import numpy as np
        docs = [d async for d in db.cbse_docs.find({"class_no": class_no, "subject": subject}, {"text":1,"chapter":1,"embedding":1})]
        sims = []
        for d in docs:
            e = np.array(d.get("embedding", []), dtype=float)
            if e.size == 0:
                sims.append(-1.0)
            else:
                sims.append(float(np.dot(e, np.array(qvec)) / (np.linalg.norm(e)+1e-8)))
        top = sorted(zip(docs, sims), key=lambda x: x[1], reverse=True)[:k]
        return [{"text":d["text"], "chapter":d["chapter"], "class_no":class_no, "subject":subject} for d,_ in top]

async def answer_with_rag(query: str, class_no: int, subject: str) -> str:
    chunks = await search_cbse(query, class_no, subject, k=4)
    context = "\n\n".join([c["text"] for c in chunks])
    client = _client_fn()
    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role":"system","content":"Answer using ONLY the provided CBSE context. If the answer isn't in the context, say you don't know."},
            {"role":"user","content":f"Context:\n{context}\n\nQuestion: {query}"},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()
