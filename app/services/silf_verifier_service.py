"""
Independent quality verification for SILF stories.

The story model self-reports `standards_verification_report` (always ~10/10) —
that is the model grading its own homework and is NOT trustworthy. This module
produces an HONEST score from two independent sources:

  1. Deterministic code checks   — real sentence length vs the grade's word cap,
     structure (4 steps, one animation, one valid NCERT figure on the exam step),
     and banned documentary openings. Cannot be gamed by the writer model.
  2. An independent LLM judge     — a fresh-context critic prompted to be strict
     and reserve 9-10 for exceptional work, scoring alignment / cognitive-load /
     relatability with concrete issues.

`verify_silf_story` merges both into a report with `passed` + `overall_score`,
used by the endpoint to gate (regenerate once) and to log/store honest numbers.
"""
from __future__ import annotations

import json
import logging
import re
from ..prompts.silf_verifier import JUDGE_SYSTEM

logger = logging.getLogger(__name__)

_BANNED_OPENINGS = ("imagine", "have you ever", "in science", "did you ever", "picture this")
_VENDOR_TERMS = ("tea stall", "chai", " stall", "shopkeeper", "customer", "vendor", "family business", "the shop", "his shop", "her shop")
_PASS_THRESHOLD = 7.0


def _word_cap(grade: int) -> int:
    if grade <= 5:
        return 10
    if grade <= 8:
        return 15
    return 18


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _deterministic(story: dict, *, grade: int, catalog_ids: set[str]) -> dict:
    steps = story.get("storyboard_steps", []) or []
    cap = _word_cap(grade)

    # readability: fraction of narration sentences over the grade word cap
    all_sents: list[str] = []
    for st in steps:
        all_sents += _sentences(st.get("narrative_content", ""))
    long = [s for s in all_sents if len(s.split()) > cap]
    pct_long = (len(long) / len(all_sents)) if all_sents else 0.0
    readability = max(0, round(10 * (1 - pct_long)))

    # structure
    anim_steps = [s for s in steps if s.get("asset_type") == "ANIMATED_SIM"]
    last = steps[-1] if steps else {}
    last_fig = last.get("db_mapping_id")
    figure_valid = (last_fig is None) or (last_fig in catalog_ids)
    # no NCERT figure may appear before the final step
    early_static = any(
        s.get("asset_type") == "NCERT_STATIC_IMAGE" for s in steps[:-1]
    )
    structure_ok = (3 <= len(steps) <= 4) and len(anim_steps) <= 1 and not early_static

    first_narr = (steps[0].get("narrative_content", "").strip().lower() if steps else "")
    banned_opening = any(first_narr.startswith(b) for b in _BANNED_OPENINGS)

    # vendor/commercial setting or the tea-stall cliché = not the student's own world
    blob = " ".join([
        str(story.get("meta_data", {}).get("narrator", {}).get("setting", "")),
        " ".join(s.get("narrative_content", "") for s in steps[:2]),
    ]).lower()
    vendor_setting = any(t in blob for t in _VENDOR_TERMS)

    issues = []
    if pct_long > 0.25:
        issues.append(f"{round(pct_long*100)}% of sentences exceed the {cap}-word cap for grade {grade}")
    if not figure_valid:
        issues.append(f"exam-step figure id '{last_fig}' is not in the NCERT catalog")
    if early_static:
        issues.append("a real NCERT figure appears before the exam step (should be exam-only)")
    if len(anim_steps) == 0:
        issues.append("no animated explainer on the resolution step")
    if banned_opening:
        issues.append("story opens with a banned documentary phrase")
    if vendor_setting:
        issues.append("setting is a shop/stall/vendor scene or the tea-stall cliché — not a student's own life")

    return {
        "readability": readability,
        "pct_long_sentences": round(pct_long, 2),
        "word_cap": cap,
        "step_count": len(steps),
        "anim_present": len(anim_steps) >= 1,
        "figure_valid": figure_valid,
        "structure_ok": structure_ok,
        "banned_opening": banned_opening,
        "vendor_setting": vendor_setting,
        "hard_fail": (not structure_ok) or (not figure_valid) or banned_opening,
        "issues": issues,
    }



async def _judge(story: dict, *, topic: str, subject: str, grade: int, ncert_content: str) -> tuple[dict | None, dict]:
    """Returns (verdict_or_None, usage) where usage = {model, in, out}."""
    from app.services.ai import get_gemini_client, get_client
    from app.core.config import settings
    usage = {"model": None, "in": 0, "out": 0}

    steps = story.get("storyboard_steps", []) or []
    narrative = "\n".join(
        f"[{s.get('step_phase','')}] {s.get('narrative_content','')}"
        + (f"\nExam Q: {s.get('cbse_exam_style_question')}" if s.get("cbse_exam_style_question") else "")
        for s in steps
    )
    md = story.get("meta_data", {})
    user = f"""Topic: {topic} | Subject: {subject} | Target: Class {grade}
Protagonist/setting: {md.get('narrator', {})}

STORY TO JUDGE:
{narrative}

NCERT reference (ground truth for facts):
{ncert_content[:2500] or 'n/a'}

Judge it now. Return only JSON."""

    raw = None
    gemini = get_gemini_client()
    if gemini is not None:
        try:
            from google.genai import types as genai_types
            r = gemini.models.generate_content(
                model=settings.GEMINI_STORY_MODEL,
                contents=user,
                config=genai_types.GenerateContentConfig(
                    temperature=0.15, response_mime_type="application/json",
                    system_instruction=JUDGE_SYSTEM, max_output_tokens=6000,
                ),
            )
            raw = (r.text or "").strip()
            if r.usage_metadata:
                usage = {"model": settings.GEMINI_STORY_MODEL,
                         "in": r.usage_metadata.prompt_token_count or 0,
                         "out": r.usage_metadata.candidates_token_count or 0}
        except Exception as e:
            logger.warning(f"[SILF_VERIFY] Gemini judge failed: {e}")

    if not raw:
        try:
            client = get_client()
            r = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}],
                response_format={"type": "json_object"}, temperature=0.15, max_tokens=6000,
            )
            raw = (r.choices[0].message.content or "").strip()
            if r.usage:
                usage = {"model": settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                         "in": r.usage.prompt_tokens or 0, "out": r.usage.completion_tokens or 0}
        except Exception as e:
            logger.warning(f"[SILF_VERIFY] Azure judge failed: {e}")
            return None, usage

    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n", "", raw).rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw), usage
    except json.JSONDecodeError:
        logger.warning("[SILF_VERIFY] judge returned non-JSON")
        return None, usage


async def verify_silf_story(
    story: dict, *, topic: str, subject: str, grade: int, ncert_content: str, catalog_ids: set[str]
) -> dict:
    """Merge deterministic checks + an independent LLM judge into an honest report."""
    det = _deterministic(story, grade=grade, catalog_ids=catalog_ids)
    judge, judge_usage = await _judge(story, topic=topic, subject=subject, grade=grade, ncert_content=ncert_content)

    # A failed judge must NOT fabricate flattering scores. Mark it unverified so it
    # can never "pass" the gate and can never beat a really-scored story on retry.
    judge_ok = bool(judge) and any(
        k in judge for k in ("cbse_ncert_alignment", "cognitive_load_safety", "relatability")
    )
    judge = judge or {}

    def _clamp(v, default):
        try:
            return max(0, min(10, int(v)))
        except (TypeError, ValueError):
            return default

    neutral = 5
    relatability = _clamp(judge.get("relatability"), neutral)
    if det["vendor_setting"]:
        relatability = min(relatability, 4)  # deterministic veto on vendor/cliché scenes
    scores = {
        "cbse_ncert_alignment": _clamp(judge.get("cbse_ncert_alignment"), neutral),
        "cognitive_load_safety": _clamp(judge.get("cognitive_load_safety"), neutral),
        "relatability": relatability,
        "readability": det["readability"],  # deterministic, not judge
    }
    overall = round(sum(scores.values()) / len(scores), 1)
    issues = det["issues"] + [str(x) for x in (judge.get("issues") or [])]
    if not judge_ok:
        issues.append("independent judge unavailable — scores are provisional, needs manual review")
    # Only a successful judge with a real score and no hard structural failure passes.
    passed = judge_ok and (overall >= _PASS_THRESHOLD) and not det["hard_fail"]

    return {
        "source": "independent",
        "judge_ok": judge_ok,
        "scores": scores,
        "overall_score": overall,
        "passed": passed,
        "deterministic": {k: det[k] for k in (
            "readability", "pct_long_sentences", "word_cap", "step_count",
            "anim_present", "figure_valid", "structure_ok", "banned_opening",
            "vendor_setting", "hard_fail",
        )},
        "verdict": judge.get("verdict", ""),
        "issues": issues,
        "judged_by": "gemini/azure (independent)",
        "_usage": judge_usage,
    }
