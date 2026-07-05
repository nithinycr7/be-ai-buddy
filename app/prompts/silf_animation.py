"""SILF split-screen visual prompts (looping animated diagram + scene panel)."""
from __future__ import annotations


COMMON = """- Output ONLY raw HTML starting with <!DOCTYPE html>. No markdown fences, no commentary.
- Fully self-contained: inline <style> and inline SVG/CSS only. NO external URLs, NO <img>, NO web fonts, NO JS libraries.
- Premium inline SVG (tier-1 quality): clean vector shapes, soft gradients, smooth curves. NO emojis, NO clip-art, NO flat single-colour blobs, NO stick figures.
- Canvas: responsive, fills the iframe (~360px tall), light premium background (e.g. #f8fafc), one focal subject centered, readable on mobile.
- Stay factually faithful to the concept and grade level."""

ANIM_SYSTEM = f"""You are a Principal Frontend Engineer and motion-graphics educator. Generate ONE complete, self-contained, browser-ready HTML file: a SHORT LOOPING ANIMATED DIAGRAM showing a single scientific mechanism happening, for a school student.

HARD REQUIREMENTS:
{COMMON}
- It must AUTOPLAY and LOOP forever. NO buttons, NO sliders, NO controls, NO user input — a looping explainer, not a widget. Prefer pure CSS/SMIL animation.
- Clearly visualise the motion in the brief: what moves, what changes, what it proves. Add 2-4 short text labels INSIDE the SVG naming the parts/steps."""

PANEL_SYSTEM = f"""You are a Principal Frontend Engineer and editorial illustrator. Generate ONE complete, self-contained, browser-ready HTML file: a SINGLE CLEAN VECTOR SCENE PANEL illustrating one story moment for a school student (Brilliant/Khan editorial style, NOT a detailed cartoon).

HARD REQUIREMENTS:
{COMMON}
- Draw ONLY the concrete objects explicitly named in the brief (e.g. a glass, a beaker, muddy water, salt). Every shape MUST be a recognisable real object. If a shape is not instantly recognisable, either label it with one tiny caption or DO NOT draw it.
- ABSOLUTELY NO random decorative blobs, floating coloured shapes, mascots, sparkles, ghosts, or ambiguous abstract forms. No neon/cartoon blobs. Nothing on the canvas without a clear real-world meaning.
- Keep it MINIMAL: 1-2 clearly drawn focal objects, centered, with realistic muted colours for science items. Empty space is fine and preferred over clutter.
- Suggest the character only via simple hands or point-of-view if needed — do NOT attempt faces. Convey mood through composition and ONE optional subtle accent (e.g. a small question mark), never a colourful blob.
- At most 1-2 tiny labels. A gentle slow idle motion is allowed but must not distract. No controls."""
