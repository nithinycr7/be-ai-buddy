"""
Guru-Shishya dialogue story generation service.

Parallel to story_service.py — produces a 4-scene conversation between
a Guru and a Shishya rather than a 4/5-panel "you are the character" comic.

Output shape (see prompts/guru_shishya_prompt.txt for the full contract):

{
  "personality_lens": str,
  "topic_slug": str,
  "exchanges": [
    {
      "scene_index": 0..3,
      "scene_label": str,
      "scene_background": "normal" | "problem" | "aha" | "resolution",
      "lines": [{"speaker": "guru"|"shishya", "text": str,
                 "expression": str, "sfx": str|None}, ...],
      "concept_callout": {...} | None   # only on scene_index 2
    }, ...
  ],
  "concept_highlights": [{"emoji": str, "term": str, "one_line": str} x 3],
  "completion_message": str
}
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "guru_shishya_prompt.txt"
_SYSTEM_PROMPT: str | None = None

VALID_EXPRESSIONS = {"neutral", "curious", "worried", "shocked", "aha", "happy"}
VALID_BACKGROUNDS = ["normal", "problem", "aha", "resolution"]
VALID_SPEAKERS = {"guru", "shishya"}

# Per-scene line count bounds (from prompt's validation rules).
_LINE_BOUNDS = {
    0: (2, 4),
    1: (3, 5),
    2: (3, 5),
    3: (2, 3),
}

_SCENE_LABELS = {
    0: "The story begins",
    1: "The interesting question",
    2: "Why and how",
    3: "It lands",
}


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT


def _clip_words(text: str, max_words: int) -> str:
    words = (text or "").split()
    if len(words) <= max_words:
        return text or ""
    return " ".join(words[:max_words]) + "…"


def _coerce_line(line: Any, expected_speaker: str, max_words: int) -> dict:
    if not isinstance(line, dict):
        line = {}
    speaker = line.get("speaker")
    if speaker not in VALID_SPEAKERS:
        speaker = expected_speaker
    expression = line.get("expression")
    if expression not in VALID_EXPRESSIONS:
        expression = "neutral"
    text = line.get("text") or ""
    if not isinstance(text, str):
        text = str(text)
    text = _clip_words(text.strip(), max_words)
    sfx = line.get("sfx")
    if sfx is not None and not isinstance(sfx, str):
        sfx = None
    return {
        "speaker": speaker,
        "text": text,
        "expression": expression,
        "sfx": sfx,
    }


def _validate(story: dict, grade: int) -> dict:
    exchanges = story.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise ValueError("exchanges must be a non-empty list")

    # Per-line word limit by grade (mirrors prompt rules).
    max_words = 8 if grade <= 4 else (12 if grade <= 6 else 15)

    fixed_scenes: list[dict] = []
    for i in range(4):
        scene = exchanges[i] if i < len(exchanges) else {}
        if not isinstance(scene, dict):
            scene = {}

        lines_in = scene.get("lines")
        if not isinstance(lines_in, list):
            lines_in = []

        # Scene 3 starts with shishya; all others start with guru.
        first_speaker = "shishya" if i == 3 else "guru"
        min_lines, max_lines = _LINE_BOUNDS[i]

        # Coerce each line and force strict alternation starting from first_speaker.
        coerced: list[dict] = []
        for j, raw_line in enumerate(lines_in[:max_lines]):
            expected = (
                first_speaker
                if j % 2 == 0
                else ("guru" if first_speaker == "shishya" else "shishya")
            )
            coerced.append(_coerce_line(raw_line, expected, max_words))

        # Pad if too few — keep alternation.
        while len(coerced) < min_lines:
            j = len(coerced)
            expected = (
                first_speaker
                if j % 2 == 0
                else ("guru" if first_speaker == "shishya" else "shishya")
            )
            coerced.append(
                {
                    "speaker": expected,
                    "text": "…",
                    "expression": "neutral",
                    "sfx": None,
                }
            )

        scene_obj: dict = {
            "scene_index": i,
            "scene_label": scene.get("scene_label") or _SCENE_LABELS[i],
            "scene_background": VALID_BACKGROUNDS[i],
            "lines": coerced,
            "concept_callout": None,
        }

        if i == 2:
            callout = scene.get("concept_callout")
            if not isinstance(callout, dict):
                callout = {}
            scene_obj["concept_callout"] = {
                "emoji": callout.get("emoji") or "💡",
                "term": callout.get("term") or story.get("topic_slug") or "Concept",
                "simple_definition": callout.get("simple_definition"),
                "precise_definition": callout.get("precise_definition"),
                "teacher_line": callout.get("teacher_line"),
                "formula": callout.get("formula"),
            }
            # Grade-appropriate definition fallback.
            if grade <= 4:
                scene_obj["concept_callout"]["precise_definition"] = None
                if not scene_obj["concept_callout"]["simple_definition"]:
                    scene_obj["concept_callout"][
                        "simple_definition"
                    ] = "An idea you already felt — now it has a name."
            elif grade >= 7:
                if not scene_obj["concept_callout"]["precise_definition"]:
                    scene_obj["concept_callout"]["precise_definition"] = (
                        scene_obj["concept_callout"].get("simple_definition")
                        or "The concept your teacher explained today."
                    )

        fixed_scenes.append(scene_obj)

    story["exchanges"] = fixed_scenes

    # concept_highlights — pad/trim to exactly 3.
    highlights = story.get("concept_highlights")
    if not isinstance(highlights, list):
        highlights = []
    while len(highlights) < 3:
        highlights.append(
            {
                "emoji": "📌",
                "term": "Key idea",
                "one_line": "An important idea from today's class.",
            }
        )
    story["concept_highlights"] = highlights[:3]

    story.setdefault("personality_lens", "curious")
    story.setdefault("topic_slug", "")
    story.setdefault(
        "completion_message", "Guruji explained. Shishya understood. So did you."
    )
    return story


def _fallback(topic: str, subject: str, grade: int, personality: str) -> dict:
    """Minimal valid Guru-Shishya story when LLM is unavailable."""
    callout_term = topic or "Today's idea"
    return {
        "personality_lens": personality or "curious",
        "topic_slug": (topic or "").lower().replace(" ", "-"),
        "exchanges": [
            {
                "scene_index": 0,
                "scene_label": _SCENE_LABELS[0],
                "scene_background": "normal",
                "lines": [
                    {
                        "speaker": "guru",
                        "text": "Shishya. Come, sit. School over?",
                        "expression": "happy",
                        "sfx": None,
                    },
                    {
                        "speaker": "shishya",
                        "text": "Yes Guruji. Long day. Brain tired.",
                        "expression": "neutral",
                        "sfx": None,
                    },
                ],
                "concept_callout": None,
            },
            {
                "scene_index": 1,
                "scene_label": _SCENE_LABELS[1],
                "scene_background": "problem",
                "lines": [
                    {
                        "speaker": "guru",
                        "text": f"Tell me — your teacher spoke of {topic}. Why?",
                        "expression": "curious",
                        "sfx": None,
                    },
                    {
                        "speaker": "shishya",
                        "text": "Because… it was in the textbook?",
                        "expression": "worried",
                        "sfx": "HMMMM...",
                    },
                    {
                        "speaker": "guru",
                        "text": "Ah. But why is it in the textbook?",
                        "expression": "curious",
                        "sfx": None,
                    },
                ],
                "concept_callout": None,
            },
            {
                "scene_index": 2,
                "scene_label": _SCENE_LABELS[2],
                "scene_background": "aha",
                "lines": [
                    {
                        "speaker": "guru",
                        "text": "It is the name of something you already knew.",
                        "expression": "aha",
                        "sfx": "PING!",
                    },
                    {
                        "speaker": "shishya",
                        "text": "Wait. I already knew it?",
                        "expression": "shocked",
                        "sfx": None,
                    },
                    {
                        "speaker": "guru",
                        "text": "Yes. You felt it. You just had no word.",
                        "expression": "happy",
                        "sfx": None,
                    },
                ],
                "concept_callout": {
                    "emoji": "💡",
                    "term": callout_term,
                    "simple_definition": (
                        f"A key idea in {subject} that names something you have already felt."
                        if grade <= 4
                        else None
                    ),
                    "precise_definition": (
                        f"{callout_term} — the concept your teacher explained today in {subject}."
                        if grade >= 5
                        else None
                    ),
                    "teacher_line": None,
                    "formula": None,
                },
            },
            {
                "scene_index": 3,
                "scene_label": _SCENE_LABELS[3],
                "scene_background": "resolution",
                "lines": [
                    {
                        "speaker": "shishya",
                        "text": "So that is what teacher meant today!",
                        "expression": "happy",
                        "sfx": None,
                    },
                    {
                        "speaker": "guru",
                        "text": "Now go. Have your tiffin. Brain earned it.",
                        "expression": "happy",
                        "sfx": "HA!",
                    },
                ],
                "concept_callout": None,
            },
        ],
        "concept_highlights": [
            {
                "emoji": "💡",
                "term": callout_term,
                "one_line": f"The concept from today's {subject} lesson.",
            },
            {
                "emoji": "🔍",
                "term": "Why",
                "one_line": "Always start with why — the rest follows.",
            },
            {
                "emoji": "✅",
                "term": "Recognise",
                "one_line": "Revision is recognising what you already felt.",
            },
        ],
        "completion_message": "Guruji explained. Shishya understood. So did you.",
    }


async def generate_guru_shishya_story(
    *,
    topic: str,
    subject: str,
    grade: int,
    transcript: str = "",
    ncert_content: str = "",
    personality: str = "curious",
    summary_focus: list[str] | None = None,
) -> tuple[dict[str, Any], int]:
    """
    Generate a Guru-Shishya dialogue story.
    Returns (story_dict, generation_ms).
    """
    from app.services.ai import get_gemini_client, get_client
    from app.core.config import settings

    summary_text = ", ".join(summary_focus) if summary_focus else "general understanding"

    user_message = f"""Generate the Guru-Shishya story now.

═══════════════════════════════════════════════════════
TODAY'S TOPIC: {topic}
═══════════════════════════════════════════════════════
The ENTIRE conversation must revolve around this exact topic.
The Guru's WHY question in scene 1 must be a real-world
situation where understanding "{topic}" is the missing word.
The concept_callout reveals "{topic}" (or its precise sub-concept).
concept_callout.term and the three concept_highlights must
all be about "{topic}" or sub-concepts of it.
═══════════════════════════════════════════════════════

Subject: {subject}
Grade: {grade}
Personality lens: {personality or "curious"}
Summary focus: {summary_text}

Teacher transcript (use for concept_callout.teacher_line — exact quote):
{transcript or "No transcript available."}

NCERT content (use to keep the concept in scope for this grade):
{ncert_content or "No NCERT content available."}

REMEMBER:
- 4 scenes, scene_background in order: normal, problem, aha, resolution
- Lines alternate guru / shishya strictly. Scene 3 starts with shishya.
- The concept name NEVER appears in any line — only in concept_callout.term.
- Every Guru example must come from a Class {grade} student's own daily life.
- At least one genuinely funny moment from Guru.
- Shishya gives a logical wrong answer in scene 1 before scene 2's reveal.

Output only valid JSON matching the schema. No markdown. No backticks."""

    system_prompt = _load_system_prompt()
    start = time.time()
    raw: str | None = None
    usage = 0

    # ── Gemini (primary) ──────────────────────────────────────────────────────
    gemini = get_gemini_client()
    if gemini is not None:
        try:
            from google.genai import types as genai_types

            g_resp = gemini.models.generate_content(
                model=settings.GEMINI_STORY_MODEL,
                contents=user_message,
                config=genai_types.GenerateContentConfig(
                    temperature=0.55,
                    response_mime_type="application/json",
                    system_instruction=system_prompt,
                    max_output_tokens=3000,
                ),
            )
            raw = (g_resp.text or "").strip()
            if g_resp.usage_metadata and g_resp.usage_metadata.total_token_count:
                usage = g_resp.usage_metadata.total_token_count
        except Exception as e:
            logger.warning(f"[GURU_STORY] Gemini failed, falling back to Azure: {e}")
            raw = None

    # ── Azure OpenAI (fallback) ───────────────────────────────────────────────
    if not raw:
        try:
            client = get_client()
            resp = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.55,
                max_tokens=3000,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if resp.usage:
                usage = resp.usage.total_tokens
        except Exception as e:
            logger.error(f"[GURU_STORY] Azure fallback also failed: {e}")
            gen_ms = int((time.time() - start) * 1000)
            return _fallback(topic, subject, grade, personality), gen_ms

    gen_ms = int((time.time() - start) * 1000)

    # Strip markdown fences if the model added them.
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        story = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[GURU_STORY] JSON decode failed: {e}\nRaw: {raw[:400]}")
        return _fallback(topic, subject, grade, personality), gen_ms

    try:
        story = _validate(story, grade)
    except ValueError as e:
        logger.error(f"[GURU_STORY] Validation failed: {e}")
        return _fallback(topic, subject, grade, personality), gen_ms

    logger.info(
        f"[GURU_STORY] Generated '{topic}' grade={grade} in {gen_ms}ms tokens={usage}"
    )
    return story, gen_ms
