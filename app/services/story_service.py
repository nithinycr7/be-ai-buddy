"""
Animated comic story generation service.
Uses Gemini (primary) with Azure OpenAI fallback.
Enforces the 5 story rules and strict JSON schema.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "story_prompt.txt"
_SYSTEM_PROMPT: str | None = None

VALID_EXPRESSIONS = {"neutral", "curious", "worried", "shocked", "aha", "happy"}
VALID_BEATS = {"normal_world", "problem", "attempt_fail", "aha_moment", "resolution"}


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT


def _validate(story: dict, grade: int) -> dict:
    panels = story.get("panels", [])
    if not isinstance(panels, list):
        raise ValueError("panels must be a list")

    expected = 4 if grade <= 4 else 5
    if len(panels) != expected:
        # Accept 4 or 5 panels regardless — LLM often generates close
        if len(panels) < 3:
            raise ValueError(f"Too few panels: {len(panels)}")

    beats = [p.get("beat") for p in panels]
    if "aha_moment" not in beats:
        raise ValueError("Missing aha_moment panel")

    for p in panels:
        # Coerce beat
        if p.get("beat") not in VALID_BEATS:
            p["beat"] = "normal_world"

        # Coerce expression
        if p.get("avatar_expression") not in VALID_EXPRESSIONS:
            p["avatar_expression"] = "neutral"

        # Enforce narration length
        l1 = p.get("narration_line_1") or ""
        l2 = p.get("narration_line_2") or None
        words1 = l1.split()
        if len(words1) > 15:
            p["narration_line_1"] = " ".join(words1[:12]) + "…"
        if l2:
            words2 = l2.split()
            if len(words2) > 15:
                p["narration_line_2"] = " ".join(words2[:12]) + "…"

        # aha_moment must have concept_callout
        if p.get("beat") == "aha_moment":
            if not p.get("concept_callout"):
                p["concept_callout"] = {
                    "emoji": "💡",
                    "term": story.get("setting", "Concept"),
                    "simple_definition": "An important concept you just discovered.",
                    "precise_definition": None,
                    "teacher_line": None,
                    "formula": None,
                }
        else:
            p["concept_callout"] = None

        # Grade 3-4: no choice panels
        if grade <= 4:
            p["is_choice_panel"] = False
            p["choices"] = None

        # Validate choices if present
        if p.get("is_choice_panel") and p.get("choices"):
            choices = p["choices"]
            for opt_key in ("option_a", "option_b"):
                opt = choices.get(opt_key, {})
                if not isinstance(opt, dict):
                    choices[opt_key] = {
                        "label": "Option",
                        "is_correct": opt_key == "option_b",
                        "consequence": None,
                        "consequence_expression": "neutral",
                    }

    # Concept highlights must be a list of 3
    highlights = story.get("concept_highlights", [])
    if not isinstance(highlights, list):
        highlights = []
    # Pad or trim to exactly 3
    while len(highlights) < 3:
        highlights.append({"emoji": "📌", "term": "Key Concept", "one_line": "An important idea from this lesson."})
    story["concept_highlights"] = highlights[:3]

    story.setdefault("completion_message", "You figured it out. It was in your world all along.")
    return story


def _fallback(topic: str, subject: str, grade: int) -> dict:
    is_upper = grade >= 5
    panels = [
        {
            "panel_index": 0, "beat": "normal_world", "avatar_expression": "neutral",
            "scene_context": "🏫📚",
            "narration_line_1": "Something in the school is not working right.",
            "narration_line_2": None,
            "dialogue": f"Wait — this has to do with {subject}!",
            "sound_effect": None, "is_choice_panel": False, "choices": None, "concept_callout": None,
        },
        {
            "panel_index": 1, "beat": "problem", "avatar_expression": "worried",
            "scene_context": "❓😬",
            "narration_line_1": "You stare at the problem. It makes no sense.",
            "narration_line_2": None,
            "dialogue": "Why is this happening?",
            "sound_effect": "DUN DUN DUN...", "is_choice_panel": False, "choices": None, "concept_callout": None,
        },
    ]
    if is_upper:
        panels.append({
            "panel_index": 2, "beat": "attempt_fail", "avatar_expression": "shocked",
            "scene_context": "❌😬",
            "narration_line_1": "You try the obvious solution. It fails.",
            "narration_line_2": None,
            "dialogue": "That made it worse somehow.",
            "sound_effect": "BZZT!", "is_choice_panel": True,
            "choices": {
                "prompt": "What do you try next?",
                "option_a": {"label": "Try the same thing again", "is_correct": False,
                             "consequence": "It fails again. Same result, more confusion.", "consequence_expression": "shocked"},
                "option_b": {"label": "Look for a clue", "is_correct": True, "consequence": None, "consequence_expression": "curious"},
            },
            "concept_callout": None,
        })
    panels.append({
        "panel_index": len(panels), "beat": "aha_moment", "avatar_expression": "aha",
        "scene_context": "💡✨",
        "narration_line_1": "You see it now. It was here all along.",
        "narration_line_2": "Everything clicks into place.",
        "dialogue": "Of course! That is how it works!",
        "sound_effect": "PING!", "is_choice_panel": False, "choices": None,
        "concept_callout": {
            "emoji": "💡",
            "term": topic,
            "simple_definition": f"A key idea in {subject} that explains what you just experienced.",
            "precise_definition": None if grade <= 4 else f"{topic} — the scientific explanation for what you observed.",
            "teacher_line": None,
            "formula": None,
        },
    })
    panels.append({
        "panel_index": len(panels), "beat": "resolution", "avatar_expression": "happy",
        "scene_context": "😊🌿",
        "narration_line_1": "You solved it. You feel the difference.",
        "narration_line_2": None,
        "dialogue": "Now I can explain this to anyone.",
        "sound_effect": None, "is_choice_panel": False, "choices": None, "concept_callout": None,
    })
    return {
        "personality_lens": "curious",
        "setting": "classroom",
        "panels": panels,
        "concept_highlights": [
            {"emoji": "💡", "term": topic, "one_line": f"The concept you discovered in today's {subject} lesson."},
            {"emoji": "🔍", "term": "Observation", "one_line": "Noticing what is different and asking why."},
            {"emoji": "✅", "term": "Understanding", "one_line": "When the explanation matches what you saw."},
        ],
        "completion_message": "You figured it out. It was in your world all along.",
    }


async def generate_story(
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
    Generate an animated comic story structured as JSON.
    Returns (story_dict, generation_ms).
    """
    from app.services.ai import get_gemini_client, get_client
    from app.core.config import settings

    summary_text = ", ".join(summary_focus) if summary_focus else "general understanding"
    beat_structure = (
        "normal_world → problem → aha_moment → resolution (4 panels, no attempt_fail, no choice panels)"
        if grade <= 4
        else "normal_world → problem → attempt_fail → aha_moment → resolution (5 panels, attempt_fail has is_choice_panel: true)"
    )

    user_message = f"""Generate the story now.

═══════════════════════════════════════════════════════
TODAY'S TOPIC: {topic}
═══════════════════════════════════════════════════════
The ENTIRE story must revolve around this exact topic.
The crisis in panel 1 must be a real-world situation
where understanding "{topic}" is the missing knowledge.
The aha moment must reveal "{topic}" — nothing else.
concept_callout.term and the three concept_highlights
must all be about "{topic}" or its sub-concepts.

If "{topic}" is about the Solar System, the story is about
celestial bodies, day/night, shadows, orbits, the sun, planets.
If "{topic}" is about gravity, the story is about things
falling, weight, attraction, why things stay on the ground.
If "{topic}" is about heat, the story is about temperature,
hot/cold, things warming or cooling.

DO NOT default to plants, photosynthesis, or gardens
unless "{topic}" is literally about plants.
═══════════════════════════════════════════════════════

Subject: {subject}
Grade: {grade}
Personality lens: {personality or "curious"}
Summary focus: {summary_text}
Beat structure: {beat_structure}

Teacher transcript (use for teacher_line quotes):
{transcript or "No transcript available."}

NCERT content (use for precise concepts in scope for this grade):
{ncert_content or "No NCERT content available."}

REMEMBER:
- The story is about "{topic}" — verify this before returning
- Use "you" in ALL narration — never any name
- Concept name ONLY in concept_callout.term — never in narration or dialogue
- narration_line_1 and narration_line_2: max 12 words each
- Panel 1 must open with an urgent crisis tied to "{topic}"
- concept_highlights: exactly 3 items, all about "{topic}"

Output only valid JSON."""

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
                    temperature=0.45,
                    response_mime_type="application/json",
                    system_instruction=system_prompt,
                    max_output_tokens=3000,
                ),
            )
            raw = (g_resp.text or "").strip()
            if g_resp.usage_metadata and g_resp.usage_metadata.total_token_count:
                usage = g_resp.usage_metadata.total_token_count
        except Exception as e:
            logger.warning(f"[STORY] Gemini failed, falling back to Azure: {e}")
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
                temperature=0.45,
                max_tokens=3000,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if resp.usage:
                usage = resp.usage.total_tokens
        except Exception as e:
            logger.error(f"[STORY] Azure fallback also failed: {e}")
            gen_ms = int((time.time() - start) * 1000)
            return _fallback(topic, subject, grade), gen_ms

    gen_ms = int((time.time() - start) * 1000)

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        story = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[STORY] JSON decode failed: {e}\nRaw: {raw[:400]}")
        return _fallback(topic, subject, grade), gen_ms

    try:
        story = _validate(story, grade)
    except ValueError as e:
        logger.error(f"[STORY] Validation failed: {e}")
        return _fallback(topic, subject, grade), gen_ms

    logger.info(f"[STORY] Generated '{topic}' grade={grade} in {gen_ms}ms tokens={usage}")
    return story, gen_ms
