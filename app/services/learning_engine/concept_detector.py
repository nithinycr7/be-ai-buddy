from __future__ import annotations
import json
import re
import logging
from openai import AzureOpenAI
from app.db.sqlite_db import get_sqlite_db
from app.core.config import settings

logger = logging.getLogger(__name__)

_client: AzureOpenAI | None = None


def get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version="2024-12-01-preview",
        )
    return _client


def detect_concept(query: str, grade: int, curriculum: str) -> dict:
    """
    1. Try exact / keyword match in SQLite concepts table
    2. Fall back to LLM extraction if not found in DB
    Returns dict: {slug, name, concept_type, subject, found_in_db}
    """
    normalized = query.lower().strip()

    with get_sqlite_db() as db:
        # Exact name or slug match
        row = db.execute(
            """SELECT id, name, slug, concept_type, subject
               FROM concepts
               WHERE (lower(name) = ? OR slug = ?)
               AND grade_min <= ? AND grade_max >= ?
               AND curriculum = ?
               LIMIT 1""",
            (normalized, normalized.replace(" ", "-"), grade, grade, curriculum)
        ).fetchone()

        if not row:
            # Keyword / partial match
            row = db.execute(
                """SELECT id, name, slug, concept_type, subject
                   FROM concepts
                   WHERE (lower(name) LIKE ? OR keywords LIKE ?)
                   AND grade_min <= ? AND grade_max >= ?
                   AND curriculum = ?
                   LIMIT 1""",
                (f"%{normalized}%", f"%{normalized}%", grade, grade, curriculum)
            ).fetchone()

    if row:
        return {
            "slug":         row["slug"],
            "name":         row["name"],
            "concept_type": row["concept_type"],
            "subject":      row["subject"],
            "found_in_db":  True,
        }

    # LLM fallback
    return _llm_extract_concept(query, grade, curriculum)


def _llm_extract_concept(query: str, grade: int, curriculum: str) -> dict:
    from app.prompts.learning_engine_prompts import CONCEPT_EXTRACTION_PROMPT

    try:
        client = get_client()
        prompt = CONCEPT_EXTRACTION_PROMPT.format(query=query)

        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        data = json.loads(resp.choices[0].message.content)
        name = data.get("concept_name", query)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

        return {
            "slug":         slug,
            "name":         name,
            "concept_type": None,
            "subject":      data.get("subject", "General"),
            "found_in_db":  False,
        }
    except Exception as e:
        logger.warning(f"LLM concept extraction failed: {e}")
        # Graceful fallback: treat query as-is
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
        return {
            "slug":         slug,
            "name":         query,
            "concept_type": None,
            "subject":      "General",
            "found_in_db":  False,
        }
