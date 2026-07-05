"""
SILF revision-story generation service (exam-centric, NCERT-figure-grounded).

PARALLEL to the existing comic story_service.py — that one is untouched.
Differences:
  • SILF 4-step structure (Anchor → Bottleneck → Resolution → Decontextualisation)
  • Visuals are REAL NCERT figures, not emoji/AI images. The LLM is given a figure
    catalog and may only *select* a db_mapping_id from it; we validate every id
    against the catalog and null out any hallucinations.

Uses Gemini (primary) with Azure OpenAI fallback, mirroring story_service.py.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "silf_story_prompt.txt"
_SYSTEM_PROMPT: str | None = None

_VALID_PHASES = ["The Anchor", "The Bottleneck", "The Resolution", "Decontextualisation"]

# ── Narrative formats (Hero-set) — the student is ALWAYS the protagonist ──────
# Each format is a story STRUCTURE the student can choose; the directive tells the
# writer how to build it while keeping the student the active hero.
FORMATS: dict[str, dict[str, str]] = {
    "detective": {
        "label": "Detective Case",
        "directive": "Format = DETECTIVE CASE. The student is the detective. The crisis is a mystery; "
                     "real-world observations are the clues; the NCERT concept is the deduction tool that cracks it. "
                     "Build suspense, gather evidence step by step, then reveal the 'culprit' (the scientific explanation).",
    },
    "broken_world": {
        "label": "Broken World",
        "directive": "Format = BROKEN WORLD. Something in the student's world has broken or gone wrong. The student must "
                     "apply the NCERT concept as the tool/fix to restore it before it's too late. Stakes = repair the failure.",
    },
    "race": {
        "label": "Race Against Time",
        "directive": "Format = RACE AGAINST TIME. A ticking deadline (a match, a contest, a rescue, a timer). The student must "
                     "ACTIVELY USE the concept to win or finish in time. Momentum and stakes drive every step.",
    },
    "apprentice": {
        "label": "Time-Traveler's Apprentice",
        "directive": "Format = TIME-TRAVELER'S APPRENTICE. The student is pulled into the moment the concept was first discovered "
                     "and becomes the scientist's apprentice — running the experiment and reasoning it out alongside them. "
                     "The student stays an active human helper, NEVER a passive observer and NEVER an abstract object.",
    },
}
DEFAULT_FORMAT = "detective"
_SUBJECT_DEFAULT_FORMAT = {
    "mathematics": "race", "maths": "race", "math": "race",
    "physics": "broken_world",
    "chemistry": "broken_world",
    "biology": "broken_world",
    "science": "detective",
}


def resolve_format(narrative_format: str | None, subject: str) -> str:
    """Validate a requested format id; else pick the best default for the subject."""
    if narrative_format in FORMATS:
        return narrative_format
    subj = (subject or "").strip().lower()
    for key, fmt in _SUBJECT_DEFAULT_FORMAT.items():
        if key in subj:
            return fmt
    return DEFAULT_FORMAT


# Slices of a student's OWN life — rotated per generation to force variety and keep
# the protagonist in a world the student actually lives (never a shop/job/stall).
_SCENARIO_DOMAINS = [
    "their own home kitchen, cooking or helping a parent prepare food",
    "the school science lab during a hands-on class experiment",
    "a school science-fair project they are building",
    "a messy bedroom or home after a rainy day",
    "the playground or a sports match (cricket, football, kabaddi)",
    "helping a younger sibling with something at home",
    "a family festival being prepared at home (Diwali, Holi, a birthday)",
    "a hobby — art and craft, building a model, or a school club",
    "a school picnic or trip with friends",
    "everyday chores at home like sorting, cleaning, or fixing something",
]


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT


def _validate(story: dict, *, catalog_ids: set[str], subject: str, topic: str, grade: int) -> dict:
    steps = story.get("storyboard_steps")
    if not isinstance(steps, list) or len(steps) < 3:
        raise ValueError(f"storyboard_steps must be a list of ~4 steps, got {type(steps)}")

    last_idx = len(steps) - 1
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"step {i} is not an object")
        step["step_number"] = i + 1
        if not step.get("step_phase"):
            step["step_phase"] = _VALID_PHASES[i] if i < len(_VALID_PHASES) else "Step"
        step.setdefault("narrative_content", "")
        step.setdefault("visual_asset_note", "")
        step.setdefault("animation_brief", None)
        step.setdefault("panel_brief", None)

        # ── chunked, scannable text (right side) ──
        lines = step.get("narration_lines")
        if not isinstance(lines, list) or not lines:
            lines = _sentences(step.get("narrative_content", ""))[:3]
        step["narration_lines"] = [str(x).strip() for x in lines if str(x).strip()][:3]
        kt = step.get("key_terms")
        step["key_terms"] = [str(x).strip() for x in kt if str(x).strip()][:4] if isinstance(kt, list) else []
        inq = step.get("inquiry")
        step["inquiry"] = (str(inq).strip() or None) if inq else None

        is_resolution = (step.get("step_phase") or "").startswith("The Resolution")
        is_exam = i == last_idx  # decontextualisation / exam anchor is always the final step

        if is_exam:
            # ONLY the exam step may carry a real NCERT figure, and only from the catalog.
            db_id = step.get("db_mapping_id")
            if db_id in catalog_ids:
                step["has_visual_asset"] = True
                step["asset_type"] = "NCERT_STATIC_IMAGE"
                step["db_mapping_id"] = db_id
            else:
                if db_id:
                    logger.warning("[SILF] dropped non-catalog figure id from LLM: %r", db_id)
                step["has_visual_asset"] = False
                step["asset_type"] = None
                step["db_mapping_id"] = None
            step["animation_brief"] = None
            step["panel_brief"] = None
            step["inquiry"] = None  # exam step uses cbse_exam_style_question instead
        elif is_resolution and step.get("animation_brief"):
            # The resolution step gets a generated looping animation (no static image).
            step["has_visual_asset"] = True
            step["asset_type"] = "ANIMATED_SIM"
            step["db_mapping_id"] = None
            step["panel_brief"] = None
        else:
            # Anchor / Bottleneck: a generated stylized SCENE PANEL on the left.
            step["has_visual_asset"] = True
            step["asset_type"] = "SCENE_PANEL"
            step["db_mapping_id"] = None
            step["animation_brief"] = None
            if not step.get("panel_brief"):
                step["panel_brief"] = step.get("narrative_content", "")[:300]

    md = story.setdefault("meta_data", {})
    md.setdefault("subject", subject)
    md.setdefault("topic", topic)
    md.setdefault("class_grade", f"Class {grade}")
    md.setdefault("narrator", {})

    _normalize_recap(story, steps)
    return story


def _normalize_recap(story: dict, steps: list) -> dict:
    """Guarantee a safe, present `recap` (closing consolidation). If the model
    omitted it, derive key_terms from the steps so a recap always exists — the
    frontend can rely on it for newly generated stories."""
    seen: set[str] = set()
    terms: list[str] = []
    for s in steps:
        for t in (s.get("key_terms") or []):
            k = str(t).strip().lower()
            if str(t).strip() and k not in seen:
                seen.add(k)
                terms.append(str(t).strip())

    r = story.get("recap") if isinstance(story.get("recap"), dict) else {}
    tk = r.get("takeaways")
    r["takeaways"] = [str(x).strip() for x in tk if str(x).strip()][:4] if isinstance(tk, list) else []
    r["headline"] = (str(r.get("headline") or "").strip() or "What you just learned")
    kt = r.get("key_terms") if isinstance(r.get("key_terms"), list) else terms
    r["key_terms"] = [str(x).strip() for x in kt if str(x).strip()][:5] or terms[:5]
    story["recap"] = r
    return story


def _fallback(topic: str, subject: str, grade: int, catalog: list[dict]) -> dict:
    # Reserve the one real figure for the exam step only.
    exam_fig = catalog[0]["id"] if catalog else None
    return {
        "meta_data": {
            "subject": subject,
            "topic": topic,
            "class_grade": f"Class {grade}",
            "story_format_used": "Single-Protagonist Mystery",
            "estimated_read_time_minutes": 5,
            "narrator": {"protagonist_name": "Aarav", "setting": "the school science lab", "story_format": "Single-Protagonist Mystery"},
        },
        "storyboard_steps": [
            {
                "step_number": 1, "step_phase": "The Anchor",
                "narrative_content": f"Aarav freezes in the lab — today's task hinges entirely on {topic}, and he is stuck.",
                "narration_lines": ["Aarav freezes in the lab.", f"Today's task needs {topic}.", "He is stuck."],
                "key_terms": [topic], "inquiry": "What am I missing here?",
                "has_visual_asset": True, "asset_type": "SCENE_PANEL", "db_mapping_id": None,
                "panel_brief": f"A Class {grade} student frozen at a lab bench, puzzled, an apparatus in front of him.",
                "animation_brief": None, "visual_asset_note": "Generated scene panel of the situation.",
            },
            {
                "step_number": 2, "step_phase": "The Bottleneck",
                "narrative_content": f"His first guess fails. {topic} needs the exact NCERT tools, introduced one by one.",
                "narration_lines": ["His first guess fails.", f"{topic} needs the right tools."],
                "key_terms": [topic], "inquiry": "Why didn't that work?",
                "has_visual_asset": True, "asset_type": "SCENE_PANEL", "db_mapping_id": None,
                "panel_brief": "The student's failed attempt — a confusing, not-working result on the bench.",
                "animation_brief": None, "visual_asset_note": "Generated scene panel of the failure.",
            },
            {
                "step_number": 3, "step_phase": "The Resolution",
                "narrative_content": f"Aarav applies the textbook idea of {topic} — and it finally works.",
                "narration_lines": [f"He applies {topic}.", "It finally works."],
                "key_terms": [topic], "inquiry": "So THIS is how it works?",
                "has_visual_asset": True, "asset_type": "ANIMATED_SIM", "db_mapping_id": None, "panel_brief": None,
                "animation_brief": f"A short looping animation showing the core mechanism of {topic} in motion for a Class {grade} {subject} student.",
                "visual_asset_note": "Generated animated explainer of the mechanism.",
            },
            {
                "step_number": 4, "step_phase": "Decontextualisation (THE EXAM ANCHOR)",
                "cbse_exam_style_question": f"Question: Explain {topic} as it appears in your NCERT chapter.",
                "narrative_content": "In the exam, identify this exact textbook figure to score full marks.",
                "narration_lines": ["Spot this exact figure in the exam.", "Name the concept for full marks."],
                "key_terms": [topic], "inquiry": None,
                "has_visual_asset": bool(exam_fig), "asset_type": "NCERT_STATIC_IMAGE" if exam_fig else None,
                "db_mapping_id": exam_fig, "animation_brief": None, "panel_brief": None,
                "visual_asset_note": "The official NCERT diagram — the exact exam graphic.",
            },
        ],
        "recap": {
            "headline": "What you just learned",
            "takeaways": [
                f"{topic} is the key idea that unlocked today's problem.",
                f"In the exam, name {topic} on its NCERT figure to score full marks.",
            ],
            "key_terms": [topic],
        },
        "standards_verification_report": {
            "cbse_ncert_alignment_score_out_of_10": 8,
            "cognitive_load_safety_score_out_of_10": 9,
            "readability_lexile_score_out_of_10": 9,
        },
    }


async def generate_silf_story(
    *,
    topic: str,
    subject: str,
    grade: int,
    chapter_key: str = "",
    transcript: str = "",
    ncert_content: str = "",
    figure_catalog: list[dict] | None = None,
    narrative_format: str | None = None,
) -> tuple[dict[str, Any], int]:
    """
    Generate a SILF 4-step revision story whose figures are real NCERT figures
    selected from `figure_catalog`. Returns (story_dict, generation_ms).
    """
    from app.services.ai import get_gemini_client, get_client
    from app.core.config import settings

    catalog = figure_catalog or []
    catalog_ids = {f["id"] for f in catalog}
    catalog_text = "\n".join(
        f'- id: "{f["id"]}" | figure {f.get("figure_number","?")} | {f.get("caption","")}'
        for f in catalog
    ) or "(no figures available — set has_visual_asset:false for every step)"

    # Force variety + a genuinely student-lived setting. Rotating the domain each
    # generation stops every story collapsing into the same cliché (e.g. a tea stall).
    domain = random.choice(_SCENARIO_DOMAINS)
    fmt_id = resolve_format(narrative_format, subject)
    fmt = FORMATS[fmt_id]

    user_message = f"""Generate the SILF revision story now.

### INPUT DATA VARIABLES
- Subject: {subject}
- Target Topic: {topic}
- Target Class: Class {grade}
- Raw Teacher's Transcript Data:
{transcript or "No transcript available."}
- NCERT Textbook Chapter Reference Data:
{ncert_content or "No NCERT excerpt available."}

### NARRATIVE FORMAT (student's chosen way of reading)
{fmt['directive']}
Apply the SUBJECT-FORMAT FIT & AUTO-ADAPTATION rules from your instructions so the format truly fits {subject}.
Set meta_data.story_format_used to "{fmt['label']}" and meta_data.story_format_requested to "{fmt['label']}".

### STORY SETTING DIRECTIVE (MANDATORY)
- Set the Anchor in THIS slice of a student's own life: {domain}
- The protagonist is a Class {grade} student doing this THEMSELVES — not watching an adult, not working a job, not running or helping at a shop/stall/business.
- BANNED settings: tea stall, chai shop, any shop/stall/cart/business, serving customers, a family business. BANNED cliché: do NOT use making/serving tea (chai) as the hook for a mixtures/separation topic — pick a fresher everyday example.
- It must feel like the student's real life so they think "this is literally me".

### AVAILABLE_NCERT_FIGURES (chapter: {chapter_key or "n/a"})
These are the ONLY images you may reference. Copy an `id` verbatim into db_mapping_id,
or use null. Never invent an id.
{catalog_text}

Output only valid JSON matching the schema."""

    system_prompt = _load_system_prompt()
    start = time.time()
    raw: str | None = None
    story_usage = {"model": None, "in": 0, "out": 0}

    # ── Gemini (primary) ─────────────────────────────────────────────────────
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
                    max_output_tokens=6000,
                ),
            )
            raw = (g_resp.text or "").strip()
            um = g_resp.usage_metadata
            if um:
                story_usage = {"model": settings.GEMINI_STORY_MODEL,
                               "in": um.prompt_token_count or 0, "out": um.candidates_token_count or 0}
        except Exception as e:
            logger.warning(f"[SILF] Gemini failed, falling back to Azure: {e}")
            raw = None

    # ── Azure OpenAI (fallback) ──────────────────────────────────────────────
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
                max_tokens=6000,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if resp.usage:
                story_usage = {"model": settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                               "in": resp.usage.prompt_tokens or 0, "out": resp.usage.completion_tokens or 0}
        except Exception as e:
            logger.error(f"[SILF] Azure fallback also failed: {e}")
            gen_ms = int((time.time() - start) * 1000)
            fb = _fallback(topic, subject, grade, catalog); fb["_usage"] = story_usage
            return fb, gen_ms

    gen_ms = int((time.time() - start) * 1000)

    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        story = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[SILF] JSON decode failed: {e}\nRaw: {raw[:400]}")
        fb = _fallback(topic, subject, grade, catalog); fb["_usage"] = story_usage
        return fb, gen_ms

    try:
        story = _validate(story, catalog_ids=catalog_ids, subject=subject, topic=topic, grade=grade)
    except ValueError as e:
        logger.error(f"[SILF] Validation failed: {e}")
        fb = _fallback(topic, subject, grade, catalog); fb["_usage"] = story_usage
        return fb, gen_ms

    story["_usage"] = story_usage
    logger.info(f"[SILF] Generated '{topic}' grade={grade} in {gen_ms}ms tokens={story_usage['in']+story_usage['out']}")
    return story, gen_ms
