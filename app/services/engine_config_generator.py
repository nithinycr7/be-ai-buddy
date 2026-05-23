"""
Generate engine world configs via Gemini.

Reuses the existing lazy-singleton client from app.services.ai.get_gemini_client()
and the project's GEMINI_SIMULATION_MODEL setting.
"""
from __future__ import annotations

import json
import logging
import re
import time
import asyncio
from pathlib import Path
from typing import List

from app.core.config import settings
from app.services.ai import get_gemini_client

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "engine_prompt.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_prompt(topic: str, subject: str, grades: List[int], board: str) -> str:
    return (
        f"Generate the learning engine config for:\n\n"
        f"Topic:   {topic}\n"
        f"Subject: {subject}\n"
        f"Grades:  {grades}\n"
        f"Board:   {board}\n\n"
        "Output only the JSON config. No explanation. No markdown."
    )


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        # remove leading fence (```json or ```)
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1:]
        # remove trailing fence
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_LINE_COMMENT_RE  = re.compile(r"(^|[^:\"])//[^\n]*", re.MULTILINE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _repair_json(raw: str) -> str:
    """Best-effort fix for the common ways Gemini produces almost-JSON.

    Handles: stray // and /* */ comments, trailing commas before } or ].
    Does NOT attempt to fix unterminated strings or missing delimiters —
    those are signs of a deeper problem the caller should surface.
    """
    fixed = _BLOCK_COMMENT_RE.sub("", raw)
    fixed = _LINE_COMMENT_RE.sub(lambda m: m.group(1), fixed)
    fixed = _TRAILING_COMMA_RE.sub(r"\1", fixed)
    return fixed


async def generate_engine_config(
    topic: str,
    subject: str,
    grades: List[int],
    board: str = "CBSE",
) -> tuple[dict, int, str]:
    """Call Gemini and return (config_dict, generation_ms, model_name).

    Raises ValueError on invalid JSON, RuntimeError on missing API key or
    transport failure.
    """
    client = get_gemini_client()
    if client is None:
        raise RuntimeError(
            "GOOGLE_API_KEY is not configured — cannot generate engine config."
        )

    # Lazy import so the module loads even without google-genai installed
    from google.genai import types as genai_types

    user_prompt = _build_user_prompt(topic, subject, grades, board)
    model_name = settings.GEMINI_SIMULATION_MODEL

    start = time.time()
    max_attempts = 3
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            err_str = str(e)
            # Retry on transient Gemini errors (503 UNAVAILABLE, 429 rate-limit)
            is_transient = any(code in err_str for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            if is_transient and attempt < max_attempts:
                wait = 2 ** attempt  # 2s, 4s
                logger.warning(f"[ENGINE-CONFIG] Gemini attempt {attempt} failed ({err_str[:80]}), retrying in {wait}s…")
                await asyncio.sleep(wait)
            else:
                logger.error(f"[ENGINE-CONFIG] Gemini call failed after {attempt} attempt(s): {e}")
                raise RuntimeError(f"Gemini API error: {e}") from e
    if last_exc:
        raise RuntimeError(f"Gemini API error: {last_exc}") from last_exc

    elapsed_ms = int((time.time() - start) * 1000)
    raw = (resp.text or "").strip()
    raw = _strip_code_fences(raw)

    # Detect truncation early — gives a clearer error than "Expecting ','"
    finish_reason = None
    try:
        finish_reason = (resp.candidates[0].finish_reason or "").upper() if resp.candidates else None
    except Exception:
        finish_reason = None
    truncated = finish_reason in ("MAX_TOKENS", "LENGTH")

    try:
        config = json.loads(raw)
    except json.JSONDecodeError:
        # Attempt repair pass for the common Gemini drifts (trailing commas, comments)
        try:
            config = json.loads(_repair_json(raw))
            logger.warning("[ENGINE-CONFIG] Repaired malformed JSON from Gemini.")
        except json.JSONDecodeError as e2:
            # Log the FULL raw output so we can diagnose — error messages on the
            # client side only show the first 500 chars
            logger.error(
                "[ENGINE-CONFIG] Invalid JSON from Gemini. "
                "finish_reason=%s, length=%d, error=%s\nFULL RAW:\n%s",
                finish_reason, len(raw), e2, raw,
            )
            hint = (
                " (response was truncated at max_output_tokens — bump the limit "
                "or simplify the schema)" if truncated else ""
            )
            raise ValueError(
                f"Gemini returned invalid JSON: {e2}.{hint} "
                f"First 500 chars: {raw[:500]}"
            ) from e2

    return config, elapsed_ms, model_name
