"""
Generated visuals for a SILF story's split-screen comic layout.

Two producers, both returning self-contained inline-SVG/CSS HTML rendered on the
frontend in an <iframe srcDoc> (same engine as the Explore sims: Gemini → Anthropic):

  • generate_scene_panel    — a stylized comic SCENE panel (steps 1-2: the situation
    and the failed attempt). Premium vector, Brilliant/Khan aesthetic.
  • generate_silf_animation — a SHORT LOOPING animated diagram of the mechanism
    (step 3: "how it actually happens").

Both wrap the blocking LLM call in asyncio.to_thread so the endpoint can generate
all of a story's visuals concurrently.
"""
from __future__ import annotations

import asyncio
import logging
import re
from ..prompts.silf_animation import ANIM_SYSTEM, PANEL_SYSTEM

logger = logging.getLogger(__name__)


def _has_visual(html: str | None) -> bool:
    """True only if the HTML actually contains a rendered drawing (not an empty shell)."""
    if not html:
        return False
    low = html.lower()
    if "<svg" not in low and "<canvas" not in low:
        return False
    shapes = len(re.findall(r"<(path|rect|circle|ellipse|polygon|polyline|line)\b", low))
    return shapes >= 3


def _strip_fences(html: str) -> str:
    html = html.strip()
    if html.startswith("```"):
        html = re.sub(r"^```[a-zA-Z]*\n", "", html)
        html = html.rsplit("```", 1)[0]
    idx = html.lower().find("<!doctype")
    if idx == -1:
        idx = html.lower().find("<html")
    return (html[idx:] if idx > 0 else html).strip()


def _gen_html_sync(system_prompt: str, user_message: str, model: str) -> tuple[str | None, dict]:
    """Blocking generation on the given Gemini model → Anthropic fallback.
    Returns (html_or_None, usage) where usage = {model, in, out}."""
    from app.services.ai import get_gemini_client
    from app.core.config import settings

    html: str | None = None
    usage = {"model": None, "in": 0, "out": 0}
    gemini = get_gemini_client()
    if gemini is not None:
        try:
            from google.genai import types as genai_types
            g_resp = gemini.models.generate_content(
                model=model,
                contents=user_message,
                config=genai_types.GenerateContentConfig(
                    temperature=0.6, max_output_tokens=9000, system_instruction=system_prompt,
                ),
            )
            html = (g_resp.text or "").strip() or None
            um = g_resp.usage_metadata
            if um:
                usage = {"model": model,
                         "in": um.prompt_token_count or 0, "out": um.candidates_token_count or 0}
        except Exception as e:
            logger.warning(f"[SILF_VISUAL] Gemini ({model}) failed, trying Anthropic: {e}")

    if html is None and settings.ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model=settings.ANTHROPIC_SIMULATION_MODEL,
                max_tokens=9000, temperature=0.6, system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            html = resp.content[0].text.strip()
            if resp.usage:
                usage = {"model": settings.ANTHROPIC_SIMULATION_MODEL,
                         "in": resp.usage.input_tokens or 0, "out": resp.usage.output_tokens or 0}
        except Exception as e:
            logger.warning(f"[SILF_VISUAL] Anthropic failed: {e}")

    if not html:
        return None, usage
    html = _strip_fences(html)
    return (html if "<" in html else None), usage


def _user_msg(topic: str, subject: str, grade: int, brief_label: str, brief: str, summary_text: str) -> str:
    grade_label = f"Class {grade}" if grade else "Middle School"
    return "\n".join([
        f"Topic: {topic}", f"Subject: {subject}", f"Target Grade Level: {grade_label}", "",
        f"{brief_label}:", brief,
        ("\nGrounded content (use only this for facts):\n" + summary_text) if summary_text else "",
        "\nGenerate the complete HTML now. Output ONLY raw HTML starting with <!DOCTYPE html>.",
    ])


async def _generate_visual(system: str, msg: str, models: list[str], label: str) -> tuple[str | None, dict]:
    """Try each model in turn (cheapest first) until one returns a HTML that actually
    renders a drawing. Sums token usage across all attempts. Returns (html_or_None, usage)."""
    usage = {"model": None, "in": 0, "out": 0}
    html = None
    for model in models:
        h, u = await asyncio.to_thread(_gen_html_sync, system, msg, model)
        usage["in"] += u.get("in", 0)
        usage["out"] += u.get("out", 0)
        if u.get("model"):
            usage["model"] = u["model"]
        if _has_visual(h):
            html = h
            break
        logger.warning(f"[{label}] {model} produced an empty/invalid panel — escalating")
    return html, usage


async def generate_silf_animation(
    *, topic: str, subject: str, grade: int, animation_brief: str, summary_text: str = "",
) -> tuple[str | None, dict]:
    """(html_or_None, usage) — looping animated HTML for the resolution step.
    Uses the richer simulation model (this is the high-value 'how it works' visual)."""
    from app.core.config import settings
    msg = _user_msg(topic, subject, grade, "ANIMATION BRIEF (what the looping animation must show)", animation_brief, summary_text)
    # pro twice — it's the premium visual, retry on the rare empty result
    html, usage = await _generate_visual(ANIM_SYSTEM, msg, [settings.GEMINI_SIMULATION_MODEL, settings.GEMINI_SIMULATION_MODEL], "SILF_ANIM")
    if html:
        logger.info(f"[SILF_ANIM] generated animation for '{topic}' ({len(html)} chars)")
    return html, usage


async def generate_scene_panel(
    *, topic: str, subject: str, grade: int, panel_brief: str, summary_text: str = "",
) -> tuple[str | None, dict]:
    """(html_or_None, usage) — stylized comic SCENE panel for an anchor/bottleneck step.
    Flash first (cheap); if flash returns an empty panel, escalate to pro so it never
    renders blank. Only pays for pro on the rare flash miss."""
    from app.core.config import settings
    msg = _user_msg(topic, subject, grade, "SCENE PANEL BRIEF (the single moment to illustrate)", panel_brief, summary_text)
    html, usage = await _generate_visual(
        PANEL_SYSTEM, msg, [settings.GEMINI_STORY_MODEL, settings.GEMINI_SIMULATION_MODEL], "SILF_PANEL"
    )
    if html:
        logger.info(f"[SILF_PANEL] generated scene panel for '{topic}' ({len(html)} chars)")
    return html, usage
