"""
Adaptive Intervention Engine
=============================
Given a student's WRONG quiz answers, infer the single root gap concept and
generate a short (2-3 min) targeted intervention + 3 verification questions.

Gap detection is LLM-inferred (no quiz-schema migration): we feed the wrong
questions + the student's wrong answers + the quiz topic to the model and ask
it to name the root gap and build same-concept / different-value verification
questions.

Primary model: Gemini (via the existing OpenAI-compatible get_chat_client()).
Fallback:      Anthropic claude-sonnet-4-6 (mirrors app/routers/ai.py).
Last resort:   a minimal generic intervention so the student flow never breaks.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..core.config import settings
from .ai import get_chat_client
from ..prompts.intervention import build_intervention_prompt

logger = logging.getLogger(__name__)


# Human-readable framing per tier — keeps the student experience encouraging.

def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce LLM output into our schema shape and stamp verification qids."""
    questions = []
    for i, q in enumerate(data.get("verification_questions", [])[:3], 1):
        options = []
        for opt in q.get("options", []) or []:
            if isinstance(opt, dict):
                options.append({
                    "key": str(opt.get("key", "")),
                    "description": str(opt.get("description", "")),
                })
        correct = q.get("correct", [])
        if isinstance(correct, str):
            correct = [correct]
        questions.append({
            "qid": f"v{i}",
            "question": str(q.get("question", "")),
            "question_type": str(q.get("question_type", "MCQ")).upper(),
            "difficulty": str(q.get("difficulty", "easy")).lower(),
            "options": options,
            "correct": correct,
            "explanation": q.get("explanation"),
        })
    return {
        "gap_concept": data.get("gap_concept") or "Core concept",
        "intervention_type": data.get("intervention_type") or "Concept Review",
        "explanation": data.get("explanation") or "",
        "worked_example": data.get("worked_example") or "",
        "verification_questions": questions,
    }


def _fallback(topic: str) -> Dict[str, Any]:
    """Last-resort intervention so the demo flow never breaks if no LLM is up."""
    return {
        "gap_concept": f"{topic} fundamentals",
        "intervention_type": "Concept Review",
        "explanation": (
            f"Let's quickly revisit the core idea behind {topic}. Take it one "
            "step at a time — focus on what each term means before combining them."
        ),
        "worked_example": "",
        "verification_questions": [],
    }


async def generate_intervention(*, wrong_questions: List[Dict[str, Any]],
                                topic: str, subject: str, class_no: int,
                                tier: str) -> Dict[str, Any]:
    """Infer the gap and generate intervention content + 3 verification questions."""
    prompt = build_intervention_prompt(wrong_questions, topic, subject, class_no, tier)
    system = (
        f"You are an expert, encouraging grade-{class_no} {subject} tutor. "
        "You diagnose the single root cause of a student's mistakes and remediate "
        "it concisely. Return only valid JSON."
    )

    # ── Primary: Gemini via OpenAI-compatible client ──────────────────────────
    try:
        client = get_chat_client()
        resp = client.chat.completions.create(
            model=settings.GEMINI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        return _normalize(json.loads(resp.choices[0].message.content))
    except Exception as e:
        logger.warning(f"[INTERVENTION] Gemini call failed, trying Anthropic: {e}")

    # ── Fallback: Anthropic Claude ────────────────────────────────────────────
    if settings.ANTHROPIC_API_KEY:
        try:
            import anthropic
            anth = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            resp = anth.messages.create(
                model=settings.ANTHROPIC_SIMULATION_MODEL,
                max_tokens=2000,
                temperature=0.4,
                system=system + " Respond with a single JSON object, no prose.",
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            # Strip ```json fences if present
            if text.startswith("```"):
                text = text.split("```", 2)[1].lstrip("json").strip("` \n")
            return _normalize(json.loads(text))
        except Exception as e:
            logger.warning(f"[INTERVENTION] Anthropic call failed, using fallback: {e}")

    return _fallback(topic)
