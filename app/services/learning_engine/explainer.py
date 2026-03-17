from __future__ import annotations
import json
import logging
from openai import AzureOpenAI
from app.db.sqlite_db import get_sqlite_db
from app.core.config import settings
from app.prompts.learning_engine_prompts import (
    CONCEPT_CLASSIFICATION_PROMPT,
    EXPLANATION_GENERATION_PROMPT,
    MODE_INSTRUCTIONS,
    VISUAL_SCHEMA_PLACEHOLDER,
)

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


def classify_concept(concept_name: str, subject: str, grade: int) -> tuple[str, str]:
    """Call LLM to classify concept_type and suggest learning_mode."""
    client = get_client()
    prompt = CONCEPT_CLASSIFICATION_PROMPT.format(
        concept_name=concept_name, subject=subject, grade=grade
    )
    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("concept_type", "concept"), data.get("learning_mode", "diagram")


def generate_explanation(
    concept_name: str,
    concept_type: str,
    subject: str,
    grade: int,
    curriculum: str,
    learning_mode: str,
) -> dict:
    """Call LLM to generate full structured explanation."""
    client = get_client()

    mode_instructions = MODE_INSTRUCTIONS.get(learning_mode, "")
    visual_schema = VISUAL_SCHEMA_PLACEHOLDER.get(learning_mode, "{}")

    prompt = EXPLANATION_GENERATION_PROMPT.format(
        grade=grade,
        curriculum=curriculum,
        subject=subject,
        concept_name=concept_name,
        concept_type=concept_type,
        learning_mode=learning_mode,
        mode_specific_instructions=mode_instructions,
        visual_data_schema=visual_schema,
    )

    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert teacher for Indian school students. "
                    "Always return valid JSON only — no markdown, no code blocks. "
                    "Make all content engaging and perfectly suited for the student's grade."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
        max_tokens=2500,
    )

    return json.loads(resp.choices[0].message.content)


def get_cached_response(slug: str, grade: int, curriculum: str, mode: str) -> dict | None:
    with get_sqlite_db() as db:
        row = db.execute(
            """SELECT response_json FROM concept_cache
               WHERE concept_slug=? AND grade=? AND curriculum=? AND learning_mode=?
               AND (expires_at IS NULL OR expires_at > datetime('now'))""",
            (slug, grade, curriculum, mode)
        ).fetchone()
    if row:
        return json.loads(row["response_json"])
    return None


def cache_response(slug: str, grade: int, curriculum: str, mode: str,
                   data: dict, model_used: str):
    with get_sqlite_db() as db:
        db.execute(
            """INSERT OR REPLACE INTO concept_cache
               (concept_slug, grade, curriculum, learning_mode, response_json, model_used)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (slug, grade, curriculum, mode, json.dumps(data), model_used)
        )
