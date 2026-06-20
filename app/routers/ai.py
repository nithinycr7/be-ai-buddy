from __future__ import annotations
import logging
import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from ..core.security import get_tenant
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ..core.security import api_key_guard
from ..db.mongo import get_db
from ..models.schemas import Story, ContentPrefs
from ..services.ai import get_client, get_gemini_client
from ..services.rag import answer_with_rag
from ..core.config import settings

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(api_key_guard)])


# ─── TTS ──────────────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str
    voice: str = "en-IN-NeerjaNeural"
    # Azure Neural voice options (Indian English, kid-friendly):
    #   en-IN-NeerjaNeural   → warm, expressive female (great for stories)
    #   en-IN-PrabhatNeural  → clear male voice
    #   en-US-JennyNeural    → friendly female US English
    #   en-US-GuyNeural      → natural male US English

_SSML_TEMPLATE = """\
<speak version='1.0' xml:lang='en-IN' xmlns='http://www.w3.org/2001/10/synthesis'>
  <voice name='{voice}'>
    <prosody rate='0%' pitch='0%'>
      {text}
    </prosody>
  </voice>
</speak>"""

@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    """
    Converts text to natural-sounding MP3 audio using Azure AI Speech Service.
    Returns streaming audio/mpeg so the browser can play it immediately.
    Falls back to Azure OpenAI TTS if Speech Service is not configured.
    """
    import httpx, html

    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    logger = logging.getLogger(__name__)

    # ── Azure AI Speech Service — TTS (preferred) ─────────────────────────────
    if settings.AZURE_SPEECH_TTS_KEY and settings.AZURE_SPEECH_TTS_REGION:
        tts_url = (
            f"https://{settings.AZURE_SPEECH_TTS_REGION}.tts.speech.microsoft.com"
            "/cognitiveservices/v1"
        )
        ssml = _SSML_TEMPLATE.format(
            voice=req.voice,
            text=html.escape(req.text[:5000]),
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    tts_url,
                    content=ssml.encode("utf-8"),
                    headers={
                        "Ocp-Apim-Subscription-Key": settings.AZURE_SPEECH_TTS_KEY,
                        "Content-Type": "application/ssml+xml",
                        "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
                        "User-Agent": "mymedha-lxp",
                    },
                )
            if resp.status_code != 200:
                logger.error(f"[TTS] Azure Speech error {resp.status_code}: {resp.text[:200]}")
                raise HTTPException(status_code=502, detail=f"Azure Speech TTS failed: {resp.status_code}")

            audio_bytes = resp.content

            async def stream_bytes():
                chunk = 4096
                for i in range(0, len(audio_bytes), chunk):
                    yield audio_bytes[i : i + chunk]

            return StreamingResponse(
                stream_bytes(),
                media_type="audio/mpeg",
                headers={"Cache-Control": "no-store"},
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[TTS] Azure Speech exception: {e}")
            raise HTTPException(status_code=500, detail=f"TTS failed: {str(e)}")

    raise HTTPException(status_code=503, detail="TTS not configured: set AZURE_SPEECH_TTS_KEY and AZURE_SPEECH_TTS_REGION")

@router.get("/rag/answer")
async def rag_answer(query: str, class_no: int, subject: str):
    answer = await answer_with_rag(query, class_no, subject)
    return {"answer": answer}

# async def generate_story(topic: str, persona: str | dict | None, prefs: "ContentPrefs | None" = None) -> str:
#     client = get_client()

#     # Build a compact style string from prefs
#     style_parts = []
#     if prefs:
#         style_parts.append(f"Story format: {prefs.story_format}")
#         style_parts.append(f"Length: {prefs.story_length}")
#         style_parts.append(f"Tone: {prefs.tone}, Humor: {prefs.humor_level}")
#         style_parts.append(f"Examples: {', '.join(prefs.examples_type) or 'none'}")
#         if prefs.reference_figures:
#             style_parts.append(f"Reference figures: {', '.join(prefs.reference_figures)}")
#         style_parts.append(f"Language: {prefs.language}")
#         style_parts.append(f"Steps: {'yes' if prefs.include_steps else 'no'}")
#         style_parts.append(f"Summary: {prefs.include_summary}")
#         style_parts.append(f"Diagrams: {prefs.diagram_preference}")
#         style_parts.append(f"Explain as: {prefs.explanation_granularity} in {prefs.explanation_format}")
#     style = " | ".join(style_parts)

#     # prompt = f"Create a short motivational story (<=200 words) that teaches the concept: {topic}. "

#     prompt = (
#     f"Create an interactive comic-style story (<=200 words) that teaches: {topic}.\n"
#     f"Format Requirements:\n"
#     f"- Use comic panels (Panel 1, Panel 2...)\n"
#     f"- Add emojis and sound effects (e.g., ⚡💥🏏 Whoosh!)\n"
#     f"- Add 1 mascot sidekick\n"
#     f"- Insert 1 student question every 2–3 panels (multiple choice)\n"
#     f"- Keep language level adjustable based on prefs: {prefs.language if prefs else 'English'}\n"
#     f"- Age range: suitable for 7–14\n"
#     f"- End with a one-sentence summary.\n"
# )

    
#     if persona:
#         if isinstance(persona, dict):
#             # Format structured persona
#             style_desc = (
#                 f"Role: {persona.get('character_role', 'Explorer')}, "
#                 f"Tone: {persona.get('story_tone', 'Adventurous')}, "
#                 f"Themes: {', '.join(persona.get('themes', []))}, "
#                 f"Difficulty: {persona.get('difficulty', 'Balanced')}, "
#                 f"Format: {persona.get('format', 'Comic-style')}"
#             )
#             prompt += f"Style for a child who likes: {style_desc}. "
#         else:
#             # Legacy string persona
#             prompt += f"Style for a child who likes: {persona}. "

#     # prompt += (
#     #     f"Prefer the child's interests if given. Keep it safe for ages 8–12.\n\n"
#     #     f"Presentation prefs: {style or 'default'}"
#     # )

#     prompt += (
#     f"\nPrefer the child's interests if given. Keep it safe for ages 8–12.\n"
#     f"Presentation prefs: {style or 'default'}"
#     f"\nFollow the format rules strictly."
# )

#     resp = client.chat.completions.create(
#         model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
#         messages=[
#             {"role":"system","content":"You create kid-friendly educational stories. Respect the given presentation preferences strictly."},
#             {"role":"user","content":prompt},
#         ],
#         temperature=0.6,
#     )
#     return resp.choices[0].message.content.strip()


async def generate_story(topic: str, persona: str | dict | None, prefs: "ContentPrefs | None" = None) -> tuple[dict, str, int]:
    """
    Returns (structured_content_dict, plain_text_fallback, tokens_used).
    structured_content has: persona_theme, panels (5 beats), concept_highlights, mindmap_data, completion_message.
    """
    import json as _json
    logger = logging.getLogger(__name__)

    grade = getattr(prefs, "grade", None) if prefs else None
    language = prefs.language if prefs else "English"

    # Derive persona description for the prompt
    persona_desc = ""
    persona_theme = "adventure"
    if persona:
        if isinstance(persona, dict):
            themes = persona.get("themes", [])
            persona_theme = themes[0].lower() if themes else persona.get("character_role", "adventure").lower()
            persona_desc = (
                f"Character role: {persona.get('character_role', 'Explorer')}, "
                f"Tone: {persona.get('story_tone', 'Adventurous')}, "
                f"Themes: {', '.join(themes)}, "
                f"Difficulty: {persona.get('difficulty', 'Balanced')}"
            )
        else:
            persona_theme = str(persona).lower().split()[0]
            persona_desc = f"Student interest: {persona}"

    prompt = f"""You are creating a structured visual comic story for a student (grade {grade or '6-9'}) to learn: "{topic}".
Persona/interest context: {persona_desc or 'general curiosity'}
Language: {language}

CRITICAL RULE: The topic "{topic}" may contain MULTIPLE sub-concepts (e.g. "Newton's Laws of Motion" has 3 laws; "Photosynthesis" has multiple stages). You MUST teach ALL of them across the panels — do NOT focus on only one sub-concept.

Create a story with enough panels to cover every sub-concept. Use this structure:
- Panel 1 (normal_world): Student in their interest world — introduce the challenge
- Panel 2 (problem): The problem that needs knowledge to solve
- For EACH major sub-concept: add one panel with beat "aha_moment" that teaches that concept with a concept_callout
- Second-to-last panel (attempt_fail): They struggle applying partial knowledge
- Last panel (resolution): They master ALL concepts and succeed

This means:
- If topic has 1 concept → 5 panels total
- If topic has 2 concepts → 6 panels total
- If topic has 3 concepts → 7 panels total
- If topic has 4+ concepts → 8 panels total

Rules:
- Set all scenes in the student's interest world (cricket = stadium; space = spaceship; cooking = kitchen)
- Keep narration 2-3 sentences, age-appropriate, fun
- Dialogue is 1 punchy sentence
- Every aha_moment panel MUST have a concept_callout explaining that specific sub-concept
- Sound effects are optional but encouraged

Return ONLY valid JSON:
{{
  "persona_theme": "{persona_theme}",
  "panels": [
    {{
      "panel_number": 1,
      "beat": "normal_world",
      "scene_emoji": "<2-3 scene emojis>",
      "character_emoji": "<1-2 character emojis>",
      "narration": "<2-3 sentences>",
      "dialogue": "<1 punchy sentence>",
      "sound_effect": "<optional or null>",
      "concept_callout": null
    }},
    {{
      "panel_number": 2,
      "beat": "problem",
      "scene_emoji": "...", "character_emoji": "...", "narration": "...", "dialogue": "...", "sound_effect": null, "concept_callout": null
    }},
    {{
      "panel_number": 3,
      "beat": "aha_moment",
      "scene_emoji": "...", "character_emoji": "...", "narration": "...", "dialogue": "...", "sound_effect": null,
      "concept_callout": {{"term": "<first sub-concept name>", "highlight": "<clear one-sentence explanation>"}}
    }},
    "... add more aha_moment panels for each additional sub-concept ...",
    {{
      "panel_number": -2,
      "beat": "attempt_fail",
      "scene_emoji": "...", "character_emoji": "...", "narration": "...", "dialogue": "...", "sound_effect": null, "concept_callout": null
    }},
    {{
      "panel_number": -1,
      "beat": "resolution",
      "scene_emoji": "...", "character_emoji": "...", "narration": "...", "dialogue": "...", "sound_effect": null, "concept_callout": null
    }}
  ],
  "concept_highlights": [
    {{"term": "<each sub-concept>", "definition": "<simple definition>", "emoji": "<1 emoji>"}}
  ],
  "mindmap_data": {{
    "center": "<main topic>",
    "branches": [
      {{"label": "<sub-concept 1>", "emoji": "<emoji>"}},
      {{"label": "<sub-concept 2>", "emoji": "<emoji>"}},
      {{"label": "<sub-concept 3>", "emoji": "<emoji>"}}
    ]
  }},
  "completion_message": "<celebrate what was learned, name ALL sub-concepts covered>",
  "try_it_widget": <choose ONE widget type based on the topic and fill it completely>
}}

Widget rules — pick the BEST type for the topic:
- If topic involves scientific TRENDS or properties that change with position/condition (Periodic Table trends, atomic radius, electronegativity, ionization energy, temperature effects, density changes, pressure-volume relationships) → ALWAYS use "slider_simulation" with a predict_prompt so students predict before exploring
- If topic has a formula with multiple interacting variables (Newton's Laws: F=ma, Ohm's Law: V=IR, speed/distance/time) → use "parameter_simulation" — add predict_prompt if there's an intuitive prediction to make
- If topic has a formula with ONE main variable to explore (area of circle, simple percentage, single-variable relationships) → use "slider_simulation"
- If topic has a STRICT real-world sequence where every step has one clear position (life cycles: egg→larva→pupa→butterfly; digestive system stages; water cycle steps) → use "drag_sequence"
- If topic involves solving equations or reasoning step by step → use "step_builder"
- If topic is about matching concepts (rulers to achievements, terms to definitions, cause to effect) or has NO strict sequence → use "step_builder" with conceptual questions, NOT drag_sequence

CRITICAL — DO NOT use drag_sequence for:
- Historical achievements/contributions (they overlap in time)
- Cultural, political, or social developments (no single correct order)
- Any topic where multiple orderings could be defensible
- Rulers, empires, dynasties (use step_builder with factual questions instead)

CRITICAL — DO NOT use step_builder for:
- Topics that involve visual trends, observable changes, or parameter relationships — use slider_simulation instead
- Asking "what happens to X when Y changes?" — this is always a slider_simulation with predict_prompt

Widget schemas:

For "slider_simulation":
{{
  "widget_type": "slider_simulation",
  "title": "<e.g. Explore Atomic Radius Trends>",
  "instruction": "<fun 1-sentence prompt for student>",
  "formula": "<e.g. Atomic radius increases down a group>",
  "predict_prompt": "<optional: question to ask BEFORE showing the slider, e.g. 'What do you think happens to atom size as you go DOWN Group 1?'>",
  "predict_options": ["<option A>", "<option B>", "<option C>"],
  "predict_correct": <0-based index of correct option>,
  "predict_explain": "<short explanation shown after student predicts, e.g. 'Correct! More electron shells = bigger atom.'>",
  "variables": [
    {{"name": "<var_name>", "label": "<display label>", "min": <number>, "max": <number>, "default": <number>, "unit": "<unit>", "emoji": "<emoji>"}}
  ],
  "outputs": [
    {{"name": "<out_name>", "label": "<display label>", "expression": "<JS math expression using variable names>", "unit": "<unit>", "emoji": "<emoji>", "decimals": 2}}
  ],
  "visual_type": "circle"
}}

For "parameter_simulation":
{{
  "widget_type": "parameter_simulation",
  "title": "<e.g. Newton's Second Law>",
  "instruction": "<fun 1-sentence prompt>",
  "formula": "<e.g. F = m × a>",
  "predict_prompt": "<optional: intuitive question before sliders, e.g. 'If you push harder, what happens to acceleration?'>",
  "predict_options": ["<option A>", "<option B>", "<option C>"],
  "predict_correct": <0-based index>,
  "predict_explain": "<short explanation shown after prediction>",
  "variables": [
    {{"name": "<var1>", "label": "<label>", "min": <n>, "max": <n>, "default": <n>, "unit": "<unit>", "emoji": "<emoji>"}},
    {{"name": "<var2>", "label": "<label>", "min": <n>, "max": <n>, "default": <n>, "unit": "<unit>", "emoji": "<emoji>"}}
  ],
  "outputs": [
    {{"name": "<out>", "label": "<label>", "expression": "<JS expression>", "unit": "<unit>", "emoji": "<emoji>", "decimals": 2}}
  ],
  "visual_type": "motion",
  "motion_driver": "<exact name from variables[] or outputs[] that logically controls the animation speed. E.g. for F=ma use 'acceleration' if it's an input; for V=IR use 'current'; for speed=distance/time use 'speed' output>",
  "visual_emoji": "<emoji for the moving object — pick based on topic: 📦 physics box, 🚗 vehicle, 💧 liquid, ⚡ electricity, 🏃 runner, 🚀 rocket>"
}}

For "drag_sequence":
{{
  "widget_type": "drag_sequence",
  "title": "<e.g. Order the Water Cycle>",
  "instruction": "Tap a stage, then tap its correct slot to place it.",
  "items": [
    {{"id": "1", "label": "<stage name>", "emoji": "<emoji>", "correct_position": 1}},
    {{"id": "2", "label": "<stage name>", "emoji": "<emoji>", "correct_position": 2}},
    {{"id": "3", "label": "<stage name>", "emoji": "<emoji>", "correct_position": 3}},
    {{"id": "4", "label": "<stage name>", "emoji": "<emoji>", "correct_position": 4}}
  ]
}}

For "step_builder":
{{
  "widget_type": "step_builder",
  "title": "<e.g. Solve: 2x + 4 = 10>",
  "instruction": "Choose the correct next step each time.",
  "steps": [
    {{"prompt": "Step 1: ...", "options": ["<correct>", "<wrong1>", "<wrong2>"], "correct": 0, "explanation": "<why this step>"}},
    {{"prompt": "Step 2: ...", "options": ["<correct>", "<wrong1>", "<wrong2>"], "correct": 0, "explanation": "<why>"}}
  ]
}}

IMPORTANT: Replace the placeholder strings above with ACTUAL content. panel_number must be sequential integers starting from 1."""

    system_instruction = "You are an educational story designer for children aged 7-14. Always return valid JSON only, no extra text."
    raw = None
    usage = 0

    # ── Google Gemini (primary): JSON output via response_mime_type ────────────
    gemini = get_gemini_client()
    if gemini is not None:
        try:
            from google.genai import types as genai_types
            g_resp = gemini.models.generate_content(
                model=settings.GEMINI_STORY_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.65,
                    response_mime_type="application/json",
                    system_instruction=system_instruction,
                ),
            )
            raw = (g_resp.text or "").strip()
            if g_resp.usage_metadata and g_resp.usage_metadata.total_token_count:
                usage = g_resp.usage_metadata.total_token_count
        except Exception as e:
            logger.warning(f"[STORY] Gemini call failed, falling back to Azure: {e}")
            raw = None

    # ── Azure OpenAI (fallback) ────────────────────────────────────────────────
    if not raw:
        client = get_client()
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.65,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
        usage = resp.usage.total_tokens if resp.usage else 0

    try:
        structured = _json.loads(raw)
    except Exception:
        structured = {}

    # Validate and auto-correct try_it_widget (structure → semantic → step enhancement)
    if structured.get("try_it_widget"):
        fixed_widget, had_issues = _fix_widget(structured["try_it_widget"])
        wtype = fixed_widget.get("widget_type", "")
        # Semantic repair: always for drag_sequence (high error rate), or when structure fix found issues
        if had_issues or wtype in ("drag_sequence", "step_builder"):
            fixed_widget = await _semantic_fix_widget(fixed_widget)
        # Math step enhancement: replace placeholder options with realistic distractors
        if wtype == "step_builder":
            fixed_widget = await _enhance_step_builder(fixed_widget)
        structured["try_it_widget"] = fixed_widget

    # Build plain text fallback from panels for backward compat
    plain_parts = []
    for panel in structured.get("panels", []):
        plain_parts.append(f"Panel {panel.get('panel_number', '')}: {panel.get('narration', '')} \"{panel.get('dialogue', '')}\"")
    plain_text = "\n\n".join(plain_parts) if plain_parts else raw

    return structured, plain_text, usage


def _fix_widget(widget: dict) -> tuple:
    """
    Structural validation and auto-correction of try_it_widget.
    Returns (corrected_widget, had_issues).
    had_issues=True triggers the downstream semantic LLM repair pass.
    """
    import copy
    w = copy.deepcopy(widget)
    wtype = w.get("widget_type")
    had_issues = False

    if wtype == "drag_sequence":
        items = w.get("items", [])
        if not items:
            return w, False

        positions = [item.get("correct_position") for item in items]
        expected = list(range(1, len(items) + 1))
        has_duplicates = len(set(positions)) < len(positions)
        is_non_sequential = sorted(p for p in positions if isinstance(p, int)) != expected

        if has_duplicates or is_non_sequential:
            had_issues = True
            try:
                sortable = all(isinstance(p, int) for p in positions)
                if sortable and not has_duplicates:
                    order = sorted(range(len(items)), key=lambda i: items[i]["correct_position"])
                    for rank, idx in enumerate(order, start=1):
                        items[idx]["correct_position"] = rank
                elif has_duplicates:
                    for rank, item in enumerate(items, start=1):
                        item["correct_position"] = rank
            except Exception:
                for rank, item in enumerate(items, start=1):
                    item["correct_position"] = rank

        if "instruction" not in w or not w["instruction"]:
            w["instruction"] = "Tap a stage, then tap its correct slot to place it."
            had_issues = True

        w["items"] = items

    elif wtype == "parameter_simulation":
        driver = w.get("motion_driver")
        var_names = [v.get("name") for v in w.get("variables", [])]
        out_names = [o.get("name") for o in w.get("outputs", [])]
        all_names = var_names + out_names

        if driver and driver not in all_names and all_names:
            had_issues = True
            priority_keywords = ["acceleration", "speed", "velocity", "current", "force", "power"]
            matched = next(
                (n for n in all_names if any(kw in n.lower() for kw in priority_keywords)),
                all_names[0]
            )
            w["motion_driver"] = matched

        if not w.get("visual_emoji"):
            w["visual_emoji"] = "📦"

    elif wtype == "step_builder":
        for step in w.get("steps", []):
            opts = step.get("options", [])
            correct = step.get("correct", 0)
            if not isinstance(correct, int) or correct >= len(opts):
                step["correct"] = 0
                had_issues = True

    elif wtype == "slider_simulation":
        for v in w.get("variables", []):
            if v.get("min") is None:
                v["min"] = 0
                had_issues = True
            if v.get("max") is None:
                v["max"] = 100
                had_issues = True
            if v.get("default") is None:
                v["default"] = (v["min"] + v["max"]) / 2
                had_issues = True

    return w, had_issues


_SEMANTIC_REPAIR_PROMPT = """You are an expert educational content validator and corrector.

Your task is to FIX ONLY the "try_it_widget" inside the given JSON, focusing on semantic correctness (real-world accuracy and educational validity).

STRICT RULES:
1. DO NOT modify anything outside "try_it_widget"
2. DO NOT change overall JSON structure
3. Preserve fields, ids, and format as much as possible
4. Only make minimal necessary corrections
5. Output MUST be valid JSON only (no extra text)

SEMANTIC VALIDATION RULES:

For drag_sequence:
- Items MUST have a real-world logical order (timeline, steps, process, ranking)
- If no real sequence exists → convert to "match_pairs"
- Ensure correct_position reflects true factual order
- Do NOT just renumber — FIX the actual order

For parameter_simulation:
- motion_driver MUST match a valid variable or output
- If unclear or incorrect → fix to a scientifically valid variable
- Do NOT guess randomly — choose safest valid option

For step_builder:
- Steps must be logically ordered
- Correct step index must point to actual correct step

For slider_simulation:
- Values must make sense (min < default < max)
- Must reflect real-world meaning (not arbitrary numbers)

INSTRUCTION CONSISTENCY:
- Instruction must match widget_type exactly
- Fix if mismatched

DECISION STRATEGY:
1. Try minimal correction first
2. If concept is invalid for widget_type → change ONLY widget_type and adapt items minimally
3. If content is factually incorrect → fix based on real-world knowledge

OUTPUT FORMAT:
Return full JSON with corrected try_it_widget.
Include a meta field INSIDE try_it_widget:
"meta": {
  "semantic_fix": true/false,
  "issue_detected": "...",
  "fix_applied": "...",
  "confidence": 0.0-1.0
}

IMPORTANT: Do NOT leave incorrect educational content. Prefer correctness over minimal change if they conflict."""


async def _semantic_fix_widget(widget: dict) -> dict:
    """
    LLM-based semantic validation pass — called after _fix_widget() for high-risk widgets.
    Uses a low temperature to stay conservative and factually accurate.
    """
    import json as _json
    logger = logging.getLogger(__name__)
    client = get_client()

    user_msg = (
        _SEMANTIC_REPAIR_PROMPT
        + "\n\nHere is the widget JSON to validate and fix:\n"
        + _json.dumps({"try_it_widget": widget}, ensure_ascii=False, indent=2)
    )

    try:
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are an educational content validator. Return valid JSON only, no extra text."},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.15,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
        result = _json.loads(raw)
        fixed = result.get("try_it_widget", widget)
        meta = fixed.get("meta", {})
        logger.info(f"[WIDGET_SEMANTIC] issue={meta.get('issue_detected')} fix={meta.get('fix_applied')} confidence={meta.get('confidence')}")
        return fixed
    except Exception as e:
        logger.error(f"[WIDGET_SEMANTIC] Failed, keeping structural fix: {e}")
        return widget  # safe fallback — structural fix is still applied


_STEP_OPTIONS_PROMPT = """You are an expert educational tutor creating interactive, step-based learning questions for students aged 8-14.

Your task is to generate high-quality answer options for the CURRENT STEP of a problem.
This works across ALL subjects: Mathematics, Physics, Chemistry, Biology, History, Geography, etc.

STRICT RULES:
1. DO NOT use placeholder text like "Correct", "Wrong1", "Wrong2", "Option A", etc.
2. Each option must be a REAL, subject-appropriate step, action, or reasoning choice.
3. Include exactly 1 correct option and 2-3 incorrect options (distractors).
4. Distractors MUST represent realistic student mistakes for the subject:
   - Mathematics: sign errors, wrong operation order (BODMAS), skipping steps, incorrect simplification
   - Physics: wrong formula, wrong unit, missing quantity, sign/direction error
   - Chemistry: wrong product, wrong balancing, incorrect equation, reaction type confusion
   - Biology: wrong sequence in a process, mixing up structures/functions
   - History: wrong date, wrong ruler/leader, wrong cause/effect, confusion with similar events
   - Geography: wrong continent/region, wrong climate, mixing up similar terms
5. All options must look plausible, be similar in structure/length, and require thinking.
6. Language must be simple, clear, student-friendly (age 8-14).
7. DO NOT reveal the correct answer in the option text.

STEP AWARENESS:
- Options must match the CURRENT STEP only, not the full answer.
- Focus only on "What should the student do/know next?"

OUTPUT FORMAT (JSON ONLY):
{
  "options": [
    {"text": "...", "is_correct": true,  "feedback": "..."},
    {"text": "...", "is_correct": false, "feedback": "..."},
    {"text": "...", "is_correct": false, "feedback": "..."}
  ]
}

FEEDBACK RULES:
- Correct option: briefly explain WHY it is correct
- Incorrect options: explain WHAT mistake the student is making (short and educational)

QUALITY CHECK (mandatory before output):
- All options are meaningful subject steps (no placeholders)
- Distractors reflect real student mistakes for the subject
- Only ONE option is correct
- Options align with the current step
- Factually and academically accurate

IMPORTANT: This is a LEARNING SYSTEM. Prioritize conceptual understanding. Avoid trivial or obviously wrong distractors."""


async def _enhance_step_builder(widget: dict) -> dict:
    """
    For step_builder widgets: replaces each step's options with high-quality
    math distractors generated by the LLM math tutor prompt.
    Runs per-step so each step gets contextually appropriate options.
    """
    import json as _json, copy
    logger = logging.getLogger(__name__)
    client = get_client()

    steps = widget.get("steps", [])
    if not steps:
        return widget

    enhanced_steps = []
    for step in steps:
        prompt_text = step.get("prompt", "")
        existing_opts = step.get("options", [])

        # Skip if options look genuinely good (not placeholders)
        placeholder_signals = {"correct", "wrong", "option a", "option b", "distractor"}
        is_placeholder = any(
            any(sig in str(o).lower() for sig in placeholder_signals)
            for o in existing_opts
        )
        if not is_placeholder and len(existing_opts) >= 3:
            enhanced_steps.append(step)
            continue

        step_idx = steps.index(step)
        user_msg = (
            _STEP_OPTIONS_PROMPT
            + f"\n\nSubject/Topic: {widget.get('subject', widget.get('title', ''))}"
            + f"\nProblem title: {widget.get('title', '')}"
            + f"\nCurrent step prompt: {prompt_text}"
            + (f"\nPrevious steps completed: {[s.get('prompt') for s in steps[:step_idx]]}" if step_idx > 0 else "")
        )

        try:
            resp = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are a math tutor. Return valid JSON only, no extra text."},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content.strip()
            result = _json.loads(raw)
            options_data = result.get("options", [])

            if options_data:
                # Rebuild options/correct/feedback in step_builder format
                new_opts = [o["text"] for o in options_data]
                correct_idx = next((i for i, o in enumerate(options_data) if o.get("is_correct")), 0)
                new_step = copy.deepcopy(step)
                new_step["options"] = new_opts
                new_step["correct"] = correct_idx
                new_step["feedback"] = [o.get("feedback", "") for o in options_data]
                enhanced_steps.append(new_step)
                logger.info(f"[STEP_ENHANCE] Step '{prompt_text[:40]}' → {len(new_opts)} options generated")
            else:
                enhanced_steps.append(step)

        except Exception as e:
            logger.error(f"[STEP_ENHANCE] Failed for step '{prompt_text[:40]}': {e}")
            enhanced_steps.append(step)

    result_widget = copy.deepcopy(widget)
    result_widget["steps"] = enhanced_steps
    return result_widget


def _merge_prefs(school_doc, student_doc) -> ContentPrefs | None:
    school_p = school_doc.get("content_prefs") if school_doc else None
    student_p = student_doc.get("content_prefs") if student_doc else None
    if not school_p and not student_p:
        return None
    base = ContentPrefs(**school_p) if school_p else ContentPrefs()
    return ContentPrefs(**{**base.model_dump(), **(student_p or {})})

from bson import ObjectId

@router.post("/story", response_model=Story)
async def story_for_student(daily_id: str, student_id: str, tenant: str = Depends(get_tenant)):
    logger = logging.getLogger(__name__)
    logger.info(f"[STORY] Starting story generation for daily_id={daily_id}, student_id={student_id}")
    
    try:
        db = await get_db()
        logger.info("[STORY] Database connection established")
        
        if not ObjectId.is_valid(daily_id):
            logger.error(f"[STORY] Invalid daily_id format: {daily_id}")
            raise HTTPException(status_code=400, detail="Invalid daily_id format")
        
        d = await db.classes_daily.find_one({"_id": ObjectId(daily_id), "tenant": tenant})
        logger.info(f"[STORY] Daily class lookup result: {d is not None}")
        if not d:
            logger.error(f"[STORY] Daily class not found for daily_id={daily_id}")
            raise HTTPException(status_code=404, detail="Daily class not found")

        s = await db.students.find_one({"student_id": student_id, "tenant": tenant})
        logger.info(f"[STORY] Student lookup result: {s is not None}")
        
        school = await db.schools.find_one({"tenant": s.get("school_tenant")}) if s and s.get("school_tenant") else None
        logger.info(f"[STORY] School lookup result: {school is not None}")

        # Get current persona
        persona_data = s.get("story_persona") if s else None
        logger.info(f"[STORY] Persona data: {persona_data}")
        
        # Check for existing story
        existing_story = await db.stories.find_one({
            "daily_id": daily_id,
            "student_id": student_id
        }, sort=[("created_at", -1)])
        logger.info(f"[STORY] Existing story found: {existing_story is not None}")

        if existing_story:
            prev_persona = existing_story.get("persona_used")
            if prev_persona == persona_data:
                logger.info("[STORY] Returning cached story (persona unchanged)")
                # Convert ObjectId to string and remove _id
                if "_id" in existing_story:
                    existing_story["id"] = str(existing_story.pop("_id"))
                # Ensure persona_used is string for response model if it's a dict
                if isinstance(existing_story.get("persona_used"), dict):
                    existing_story["persona_used"] = str(existing_story["persona_used"])
                return Story(**existing_story)

        # Generate new story
        topic = ", ".join(d.get("topics", [])) if d else "today's topic"
        logger.info(f"[STORY] Generating story for topic: {topic}")
        
        prefs = _merge_prefs(school, s)
        logger.info(f"[STORY] Merged prefs: {prefs}")
        
        logger.info("[STORY] Calling generate_story...")
        structured_content, text, tokens_used = await generate_story(topic, persona_data, prefs=prefs)
        logger.info(f"[STORY] Story generated successfully, tokens_used={tokens_used}")

        from datetime import datetime
        now = datetime.utcnow().isoformat() + "Z"

        # Calculate generation count for this persona
        count = await db.stories.count_documents({
            "daily_id": daily_id,
            "student_id": student_id,
            "persona_used": persona_data
        })
        generation_count = count + 1
        logger.info(f"[STORY] Generation count: {generation_count}")

        res = await db.stories.insert_one({
            "daily_id": daily_id, "student_id": student_id,
            "persona_used": persona_data,
            "text": text,
            "structured_content": structured_content,
            "tokens_used": tokens_used,
            "generation_count": generation_count,
            "created_at": now
        })
        logger.info("[STORY] Story inserted into database")
        
        story_id = str(res.inserted_id)
    
        # Auto-track story generation in progress
        progress = await db.student_progress.find_one({
            "student_id": student_id,
            "daily_id": daily_id,
            "tenant": tenant
        })
        
        if not progress:
            # Create new progress document
            progress = {
                "student_id": student_id,
                "daily_id": daily_id,
                "tenant": d.get("tenant", "demo-school"),
                "date": d["date"],
                "class_no": d["class_no"],
                "section": d["section"],
                "subject": d["subject"],
                "summary_viewed": False,
                "story_generated": False,
                "quiz_taken": False,
                "quiz_attempts": 0,
                "completion_percentage": 0.0,
                "is_completed": False,
                "created_at": now,
                "updated_at": now
            }
        
        # Update story fields
        progress["story_generated"] = True
        progress["story_id"] = story_id
        progress["story_generated_at"] = now
        progress["updated_at"] = now
        
        # Recalculate completion
        completion = 0.0
        if progress.get("summary_viewed"):
            completion += 25.0
        if progress.get("story_generated"):
            completion += 25.0
        if progress.get("quiz_best_score") is not None:
            completion += (progress["quiz_best_score"] / 100.0) * 50.0
        
        progress["completion_percentage"] = completion
        progress["is_completed"] = completion >= 75.0
        
        if progress["is_completed"] and not progress.get("completed_at"):
            progress["completed_at"] = now
        
        # Upsert progress
        await db.student_progress.update_one(
            {"student_id": student_id, "daily_id": daily_id, "tenant": tenant},
            {"$set": progress},
            upsert=True
        )
        logger.info("[STORY] Progress updated")
        
        # Convert persona_data to string for response model if needed
        persona_str = str(persona_data) if persona_data else None
        
        logger.info(f"[STORY] Returning story with id={story_id}")
        return Story(
            id=story_id,
            daily_id=daily_id,
            student_id=student_id,
            persona_used=persona_str,
            text=text,
            structured_content=structured_content or None,
            tokens_used=tokens_used,
            generation_count=generation_count
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[STORY] Unhandled error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Story generation failed: {str(e)}")


# ─── SIMULATION ────────────────────────────────────────────────────────────────

# _SIMULATION_TEMPLATE_V1 (archived — v1 used empty JS stubs; replaced by v2 which
# mandates fully functional updateTextOnly / renderCanvasChanges / runSimulation bodies
# and requires real viewport SVG markup instead of the bare canvas placeholder)
#
# _SIMULATION_TEMPLATE_V1 = """<!DOCTYPE html>
# ...base shell with empty JS hooks and no viewport graphics injection...
# """

# v2: enforces complete JS implementation and real viewport markup
# (archived — superseded by v3 cozy-storyboard prompt; kept here for easy rollback by
# swapping the variable referenced in _build_simulation_prompt)
_SIMULATION_TEMPLATE_V2 = """You are a Principal Frontend Engineer, Full-Stack Educator, and Interactive UX Architect. Your sole task is to take a given educational topic and target grade level, and generate a fully functional, highly engaging, self-contained interactive simulation widget.

You must output a single, complete HTML document using the provided base layout template. You are required to maintain the structural classes, IDs, and the 3-step navigation state engine exactly. However, you MUST completely write and implement the custom visual assets, theme-specific text copy, and the JavaScript runtime execution logic from scratch. Empty functions, abbreviated code blocks, or placeholder comments are strictly forbidden.

--- REASONING & EXECUTION STEPS (HOW TO PROCESS) ---
1. TARGET GRADE AUDIENCE ADAPTATION: Analyze the requested grade level. Adjust the depth of explanations, vocabulary complexity, and user interface labels to match the student's cognitive group (e.g., simpler analogies and bold elements for Class 3; rigorous technical vocabulary, formula structures, or real data values for Class 11).
2. INTRO TAB GRAPHIC: Design a premium, highly detailed theme-specific inline SVG illustration (minimum 5 complex paths, vibrant colors, clear outlines) representing the core topic. Place it inside the `.intro-graphic-wrapper`.
3. CONCEPT TAB CARD POPULATION: Identify the 2 foundational variables, dependencies, or historical drivers of this system. Map them into the two `.anatomy-grid` containers with informative descriptions.
4. VIEWPORT INITIALIZATION: Inside `#viewport-canvas`, generate the base SVG container or rich HTML structures that will transform visually when the user interacts with the control panel.
5. PERFORMANCE-COUPLED RUNTIME LOGIC: Write complete, functional JavaScript inside the template hooks:
   - In `updateTextOnly()`, read input values and instantly map them to descriptive, live text indicators inside the `.slider-header` label selectors.
   - In `renderCanvasChanges()`, read input values and instantly modify the visual nodes inside `#viewport-canvas` (e.g., mutating scales, coordinates, rotations, paths, opacity, or positions).
   - In `runSimulation()`, evaluate the configuration using explicit conditional math or state matrices, then print a dynamic, scaffolded execution breakdown inside the `#lab-feedback` container.

--- CRITICAL MATHEMATICAL, HISTORICAL & VISUAL FIDELITY RULES ---
1. DYNAMIC ELEMENT MAPPING:
   - Identify the exact variables represented by the UI inputs (e.g., speed/size for Science, coefficients/angles for Math, timeline years/resource allocation for History, population/altitude for Geography).
   - Every single UI input MUST directly alter visual nodes inside `#viewport-canvas`. Static, non-reactive graphics are strictly forbidden.

2. ZERO HARDCODING IN EVALUATION ENGINE:
   - The `runSimulation()` function must actively calculate states using real JavaScript logic operators (`===`, `>`, `<`, `&&`, `||`, `+`, `-`, `*`) applied to live values.
   - You are forbidden from writing static placeholder text inside results. The text inside `#lab-feedback` must dynamically compute its summary strings based on the specific permutation of the sliders.

3. GEOMETRIC ACCURACY & COORDINATE INTEGRITY:
   - If the topic requires rendering multiple shapes, paths, data charts, or split-screen components, they must be cleanly separated using explicit coordinate spacing so they never overlap or compress illegibly.
   - All generated shape vertices, path strings, and calculations must be fully written out. Do not write truncation comments like "// code here".

4. VISUAL POLISH, LAYERING & MODERN INTERACTIVE DESIGN:
   - Flat, basic geometric primitive shapes (e.g., simple flat rectangles for land layers, plain stick-figure lines) are forbidden. The canvas must look like a modern dashboard asset.
   - ADVANCED SVG PATHING & PATTERNS: Use rich linear or radial gradients (`<linearGradient>`), masks, clipping paths, and drop-shadow/glow filters (`filter="drop-shadow(...)"`) to provide premium depth.
   - FLUID REACTION PARTICLES & REWARD STATES: Whenever a simulation executes or hits an optimal metric threshold, dynamically display animated thematic visual feedback assets (e.g., floating bubbles, flowing trade routes, moving energy waves, expanding historic borders, or flashing target lines).

--- MASTER HTML BOILERPLATE CONTAINER ---
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Premium Simulation Engine</title>
    <style>
        :root {
            --sky-blue: #e0f2fe; --rock-dark: #334155; --primary-accent: #f97316;
            --bg-soft: #fff7ed; --text-main: #1e293b; --container-border: #fdba74; --panel-bg: #fffaf5;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Quicksand', 'Lexend', system-ui, sans-serif; -webkit-tap-highlight-color: transparent; }
        body { background: var(--bg-soft); color: var(--text-main); min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 12px; }
        header { text-align: center; margin: 10px 0 15px 0; }
        header h1 { font-size: 1.6rem; color: #9a3412; margin-bottom: 4px; }
        header p { font-size: 0.9rem; color: #c2410c; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; }
        .app-container { width: 100%; max-width: 900px; background: white; border-radius: 20px; box-shadow: 0 10px 30px rgba(154, 52, 18, 0.06); border: 2px solid var(--container-border); overflow: hidden; display: flex; flex-direction: column; }
        .nav-tabs { display: flex; background: #ffedd5; border-bottom: 2px solid var(--container-border); }
        .tab-btn { flex: 1; padding: 14px 10px; border: none; background: none; font-size: 0.95rem; font-weight: bold; color: #a3a3a3; cursor: pointer; border-bottom: 3px solid transparent; }
        .tab-btn.active { color: #9a3412; background: white; border-bottom: 3px solid var(--primary-accent); }
        .panel { display: none; padding: 24px; min-height: 480px; animation: panelFadeIn 0.3s ease-out forwards; background: white; }
        .panel.active { display: flex; flex-direction: column; }
        @keyframes panelFadeIn { from { opacity: 0; } to { opacity: 1; } }
        #panel-intro { align-items: center; justify-content: flex-start; text-align: center; padding: 30px 20px; }
        .intro-graphic-wrapper { margin-bottom: 20px; display: flex; justify-content: center; align-items: center; width: 100%; min-height: 130px; }
        .intro-content-box { max-width: 600px; width: 100%; border: 1px solid #ffedd5; background: var(--panel-bg); padding: 24px; border-radius: 16px; margin-bottom: 20px; }
        .intro-content-box h2 { color: #9a3412; font-size: 1.4rem; margin-bottom: 12px; }
        .intro-content-box p { font-size: 0.95rem; line-height: 1.6; color: #475569; margin-bottom: 12px; }
        .anatomy-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; width: 100%; margin-bottom: 20px; }
        .anatomy-card { background: var(--panel-bg); border-radius: 14px; padding: 20px; border: 1px solid var(--container-border); }
        .anatomy-card h3 { color: #2e1065; font-size: 1.1rem; margin-bottom: 8px; }
        .anatomy-card p { font-size: 0.88rem; color: #475569; line-height: 1.5; }
        .fluid-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; color: white; margin-top: 12px; text-transform: uppercase; }
        .workbench { display: grid; grid-template-columns: 1fr; gap: 20px; width: 100%; }
        @media (min-width: 768px) { .workbench { grid-template-columns: 1.1fr 0.9fr; } }
        .simulation-view { background: #0f172a; border: 3px solid #44403c; border-radius: 20px; height: 360px; position: relative; overflow: hidden; display: flex; justify-content: center; align-items: center; width: 100%; }
        .control-panel { background: var(--panel-bg); border: 1px solid var(--container-border); border-radius: 16px; padding: 18px; display: flex; flex-direction: column; justify-content: space-between; }
        .deck-section h3 { font-size: 0.9rem; color: #9a3412; text-transform: uppercase; margin-bottom: 12px; letter-spacing: 0.5px; border-bottom: 1px solid #fed7aa; padding-bottom: 4px; }
        .slider-wrapper { background: white; border: 1px solid #fed7aa; padding: 12px; border-radius: 12px; margin-bottom: 12px; }
        .slider-header { display: flex; justify-content: space-between; font-size: 0.85rem; font-weight: bold; margin-bottom: 6px; color: #1e293b; }
        .input-range { width: 100%; -webkit-appearance: none; height: 10px; border-radius: 20px; background: #ffedd5; outline: none; }
        .input-range::-webkit-slider-thumb { -webkit-appearance: none; width: 22px; height: 22px; border-radius: 50%; background: var(--primary-accent); border: 3px solid white; cursor: pointer; }
        .terminal-log { background: white; border-left: 4px solid var(--primary-accent); padding: 12px; border-radius: 8px; font-size: 0.88rem; line-height: 1.45; min-height: 100px; color: #334155; }
        .action-btn { background: var(--primary-accent); color: white; border: none; padding: 12px 32px; font-size: 1rem; font-weight: bold; border-radius: 30px; cursor: pointer; transition: all 0.2s; align-self: center; display: inline-flex; align-items: center; gap: 8px; }
        .action-btn:hover { background: #9a3412; transform: translateY(-1px); }
    </style>
</head>
<body>
    <header>
        <h1>[INJECT ENGINE TITLE]</h1>
        <p>[INJECT SUBTITLE LEVEL/SUBJECT DESCRIPTION]</p>
    </header>
    <div class="app-container">
        <nav class="nav-tabs">
            <button class="tab-btn active" id="btn-intro" onclick="openTab('intro')">1. Introduction</button>
            <button class="tab-btn" id="btn-concept" onclick="openTab('concept')">2. Core Concepts</button>
            <button class="tab-btn" id="btn-lab" onclick="openTab('lab')">3. Interactive Lab</button>
        </nav>

        <section id="panel-intro" class="panel active">
            <div class="intro-graphic-wrapper">
                </div>
            <div class="intro-content-box">
                <h2>[Hook Title Text]</h2>
                <p>[Intro grade-appropriate background paragraph 1]</p>
                <p>[Intro grade-appropriate background paragraph 2]</p>
            </div>
            <button class="action-btn" onclick="openTab('concept')">Next Step &rarr;</button>
        </section>

        <section id="panel-concept" class="panel">
            <h2>[Concept Framework Structural Header]</h2>
            <p class="concept-subtitle">[Dynamic context setter instructions]</p>
            <div class="anatomy-grid">
                <div class="anatomy-card">
                    <h3>[Variable 1 Core Name]</h3>
                    <p>[Variable 1 mechanics and relational impact explanation block]</p>
                    <span class="fluid-badge" style="background: var(--rock-dark);">Factor A</span>
                </div>
                <div class="anatomy-card">
                    <h3>[Variable 2 Core Name]</h3>
                    <p>[Variable 2 mechanics and relational impact explanation block]</p>
                    <span class="fluid-badge" style="background: var(--rock-dark);">Factor B</span>
                </div>
            </div>
            <button class="action-btn" onclick="openTab('lab')">Explore Dashboard &rarr;</button>
        </section>

        <section id="panel-lab" class="panel">
            <div class="workbench">
                <div class="simulation-view" id="viewport-canvas">
                    </div>
                <div class="control-panel">
                    <div>
                        <div class="deck-section">
                            <h3>1. Tune System Settings</h3>
                            <div class="slider-wrapper">
                                <div class="slider-header">
                                    <span>[Parameter 1 Explicit Label]</span>
                                    <span id="txt-param1">[Default State Tracking Node]</span>
                                </div>
                                <input type="range" class="input-range" id="input-param1" min="0" max="100" value="20"
                                       oninput="updateTextOnly()" onchange="renderCanvasChanges()">
                            </div>
                            <div class="slider-wrapper">
                                <div class="slider-header">
                                    <span>[Parameter 2 Explicit Label]</span>
                                    <span id="txt-param2">[Default State Tracking Node]</span>
                                </div>
                                <input type="range" class="input-range" id="input-param2" min="0" max="100" value="50"
                                       oninput="updateTextOnly()" onchange="renderCanvasChanges()">
                            </div>
                        </div>
                    </div>
                    <button class="action-btn" style="margin-bottom: 12px; width: 100%; justify-content: center;" onclick="runSimulation()">Execute Engine Call &rarr;</button>
                    <div class="terminal-log" id="lab-feedback">
                        <strong>System Guard Status:</strong> Simulation initialized. Adjust structural parameters above to analyze mathematical or system modifications.
                    </div>
                </div>
            </div>
        </section>
    </div>
    <script>
        function openTab(tabId) {
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('panel-' + tabId).classList.add('active');
            document.getElementById('btn-' + tabId).classList.add('active');
            if(tabId === 'lab') { updateTextOnly(); renderCanvasChanges(); }
        }

        // COMPLETE, HIGH-PERFORMANCE FUNCTIONAL JAVASCRIPT EXECUTIONS ONLY
        function updateTextOnly() {
            // Read inputs, apply contextual thresholds, and sync text descriptors directly into labels instantly
        }
        function renderCanvasChanges() {
            // Apply advanced structural visual mutations directly to elements inside #viewport-canvas via styles, coordinates, and gradient fills
        }
        function runSimulation() {
            updateTextOnly();
            renderCanvasChanges();
            // Execute real math validation trees and append responsive, dynamic string reports into #lab-feedback log box
        }
    </script>
</body>
</html>

--- OUTPUT SUMMARY EXECUTION ---
Process the input subject/grade parameter context. Map the educational constraints cleanly into the boilerplate structure. Return ONLY the complete executable file output wrapped inside a single markdown code block window."""


# v3: cozy-storyboard narrative engine with physics simulation specialist focus —
# adds data-driven state matrix, banished-flat-shapes rule, and interactive particle
# engine pipelines on top of the hand-drawn classroom board-game aesthetic

_SIMULATION_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cozy Storyboard Simulation Engine</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@300..700&family=Lexend:wght@100..900&family=Quicksand:wght@300..700&display=swap" rel="stylesheet">
    <style>
        :root {
            --sky-blue: #e0f2fe; --rock-dark: #334155; --primary-accent: #f97316;
            --bg-soft: #fffbeb; --text-main: #1e293b; --container-border: #b45309; --panel-bg: #fffdf5;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Fredoka', 'Quicksand', system-ui, sans-serif; -webkit-tap-highlight-color: transparent; }
        body { background: var(--bg-soft); color: var(--text-main); min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 16px; }

        header { text-align: center; margin: 10px 0 20px 0; }
        header h1 { font-size: 2rem; color: #78350f; margin-bottom: 6px; text-shadow: 2px 3px 0px #fef3c7; }
        header p { font-size: 0.95rem; color: #b45309; font-weight: bold; text-transform: uppercase; letter-spacing: 0.8px; }

        /* Board-Written Comic Style Container Layout */
        .app-container {
            width: 100%;
            max-width: 900px;
            background: white;
            border-radius: 24px 20px 22px 24px;
            box-shadow: 0 12px 0px var(--container-border);
            border: 4px solid var(--container-border);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .nav-tabs { display: flex; background: #fef3c7; border-bottom: 4px solid var(--container-border); }
        .tab-btn { flex: 1; padding: 16px 10px; border: none; background: none; font-size: 1.05rem; font-weight: bold; color: #a1a1aa; cursor: pointer; border-bottom: 4px solid transparent; transition: all 0.2s; }
        .tab-btn.active { color: #78350f; background: white; border-bottom: 4px solid var(--primary-accent); font-weight: 800; }

        .panel { display: none; padding: 24px; min-height: 490px; animation: panelFadeIn 0.25s ease-out forwards; background: white; }
        .panel.active { display: flex; flex-direction: column; }
        @keyframes panelFadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

        #panel-intro { align-items: center; justify-content: flex-start; text-align: center; padding: 32px 20px; }
        .intro-graphic-wrapper { margin-bottom: 18px; display: flex; justify-content: center; align-items: center; width: 100%; min-height: 140px; }

        /* Hand-Sketched Note Style Content Boxes */
        .intro-content-box {
            max-width: 620px;
            width: 100%;
            border: 3px dashed #fcd34d;
            background: var(--panel-bg);
            padding: 24px;
            border-radius: 20px 18px 22px 16px;
            box-shadow: 4px 4px 0px #fef3c7;
            margin-bottom: 25px;
        }
        .intro-content-box h2 { color: #78350f; font-size: 1.6rem; margin-bottom: 12px; }
        .intro-content-box p { font-size: 1.05rem; line-height: 1.6; color: #475569; margin-bottom: 12px; }

        .anatomy-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; width: 100%; margin-bottom: 24px; }
        .anatomy-card { background: var(--panel-bg); border-radius: 20px 24px 18px 22px; padding: 22px; border: 3px solid #fed7aa; box-shadow: 4px 4px 0px #ffedd5; }
        .anatomy-card h3 { color: #4c1d95; font-size: 1.3rem; margin-bottom: 10px; }
        .anatomy-card p { font-size: 0.98rem; color: #475569; line-height: 1.5; }
        .fluid-badge { display: inline-block; padding: 6px 16px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; color: white; margin-top: 14px; text-transform: uppercase; letter-spacing: 0.5px; }

        /* Interactive Laboratory Workbench split screen configuration */
        .workbench { display: grid; grid-template-columns: 1fr; gap: 24px; width: 100%; }
        @media (min-width: 768px) { .workbench { grid-template-columns: 1.1fr 0.9fr; } }

        /* Premium Immersive Comic Sandbox Viewport Canvas */
        .simulation-view { background: #0f172a; border: 4px solid var(--container-border); border-radius: 24px 22px 26px 20px; height: 370px; position: relative; overflow: hidden; display: flex; justify-content: center; align-items: center; width: 100%; }

        /* Control Panel Surface Elements */
        .control-panel { background: var(--panel-bg); border: 3px solid #fed7aa; border-radius: 22px; padding: 20px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 4px 4px 0px #ffedd5; }
        .deck-section h3 { font-size: 1rem; color: #78350f; text-transform: uppercase; margin-bottom: 14px; letter-spacing: 0.6px; border-bottom: 3px dashed #fcd34d; padding-bottom: 6px; }

        .slider-wrapper { background: white; border: 2px solid #fcd34d; padding: 14px; border-radius: 16px; margin-bottom: 14px; box-shadow: inset 0 2px 4px rgba(0,0,0,0.02); }
        .slider-header { display: flex; justify-content: space-between; font-size: 0.98rem; font-weight: bold; margin-bottom: 8px; color: #1e293b; }

        /* Freehand Rounded Slider Elements */
        .input-range { width: 100%; -webkit-appearance: none; height: 12px; border-radius: 20px; background: #fef3c7; outline: none; }
        .input-range::-webkit-slider-thumb { -webkit-appearance: none; width: 26px; height: 26px; border-radius: 50%; background: var(--primary-accent); border: 3px solid white; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.15); transition: transform 0.1s; }
        .input-range::-webkit-slider-thumb:hover { transform: scale(1.15); }

        /* Hand-written Blackboard style text frame output logs */
        .terminal-log { background: white; border: 3px dashed var(--primary-accent); padding: 16px; border-radius: 16px; font-size: 1rem; line-height: 1.5; min-height: 110px; color: #334155; }

        /* Playful Thick Comic Button Action Triggers */
        .action-btn {
            background: var(--primary-accent);
            color: white;
            border: 3px solid var(--container-border);
            padding: 14px 38px;
            font-size: 1.15rem;
            font-weight: bold;
            border-radius: 40px;
            cursor: pointer;
            box-shadow: 0 6px 0px var(--container-border);
            transition: all 0.1s;
            align-self: center;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .action-btn:hover { background: #ea580c; }
        .action-btn:active { transform: translateY(4px); box-shadow: 0 2px 0px var(--container-border); }

        /* Interactive dynamic board particles asset anchors */
        .board-particle { position: absolute; font-size: 1.6rem; pointer-events: none; animation: popParticle 1.4s ease-out forwards; }
        @keyframes popParticle { 0% { transform: translate(0,0) scale(1) rotate(0deg); opacity: 1; } 100% { transform: translate(var(--pX), var(--pY)) scale(0.4) rotate(180deg); opacity: 0; } }
    </style>
</head>
<body>
    <header>
        <h1>[INJECT IMMERSIVE ENGINE TITLE]</h1>
        <p>[INJECT GRADE LEVEL & EXCURSION SUBTITLE]</p>
    </header>
    <div class="app-container">
        <nav class="nav-tabs">
            <button class="tab-btn active" id="btn-intro" onclick="openTab('intro')">1. The Journey</button>
            <button class="tab-btn" id="btn-concept" onclick="openTab('concept')">2. Mission Map</button>
            <button class="tab-btn" id="btn-lab" onclick="openTab('lab')">3. Storyboard Sandbox</button>
        </nav>

        <section id="panel-intro" class="panel active">
            <div class="intro-graphic-wrapper">
                [INJECT AN INLINE COZY THEMATIC MULTI-LAYERED SVG ILLUSTRATION WITH GRADIENTS AND OUTLINES HERE]
            </div>
            <div class="intro-content-box">
                <h2>[Hook Narrative Comic Header]</h2>
                <p>[Immersive storytelling context written directly in character persona welcoming the student block 1]</p>
                <p>[Immersive storytelling context written directly in character persona welcoming the student block 2]</p>
            </div>
            <button class="action-btn" onclick="openTab('concept')">Read Mission Map &rarr;</button>
        </section>

        <section id="panel-concept" class="panel">
            <h2>[Story Blueprint Hand-drawn Header]</h2>
            <p class="concept-subtitle" style="margin-bottom: 22px; color: #475569;">Review your interactive goals before tuning the storyboard knobs:</p>
            <div class="anatomy-grid">
                <div class="anatomy-card">
                    <h3>[Thematic Parameter 1 Name]</h3>
                    <p>[Immersive structural explanation of parameter behaviors and narrative effects written entirely in character tone]</p>
                    <span class="fluid-badge" style="background: var(--primary-accent);">Component Alpha</span>
                </div>
                <div class="anatomy-card">
                    <h3>[Thematic Parameter 2 Name]</h3>
                    <p>[Immersive structural explanation of parameter behaviors and narrative effects written entirely in character tone]</p>
                    <span class="fluid-badge" style="background: #2563eb;">Component Beta</span>
                </div>
            </div>
            <button class="action-btn" onclick="openTab('lab')">Open Sandbox Board &rarr;</button>
        </section>

        <section id="panel-lab" class="panel">
            <div class="workbench">
                <div class="simulation-view" id="viewport-canvas">
                    [INJECT HIGH-FIDELITY INTERACTIVE GRAPHICS LAYER HERE - REQUIRING EITHER A RICH INLINE MULTI-LAYERED SVG ELEMENT WITH FILTERS AND COORD GRADIENTS, OR AN ACTIVE RESPONSIVE HTML5 CANVAS CONTEXT LAYER]
                </div>
                <div class="control-panel">
                    <div>
                        <div class="deck-section">
                            <h3>1. Live Board Controls</h3>
                            <div class="slider-wrapper">
                                <div class="slider-header">
                                    <span>[Parameter 1 Explicit Label]</span>
                                    <span id="txt-param1" style="color: var(--primary-accent);">[Live Narrative Modifier]</span>
                                </div>
                                <input type="range" class="input-range" id="input-param1" min="1" max="10" value="3"
                                       oninput="updateTextOnly()">
                            </div>
                            <div class="slider-wrapper">
                                <div class="slider-header">
                                    <span>[Parameter 2 Explicit Label]</span>
                                    <span id="txt-param2" style="color: #2563eb;">[Live Narrative Modifier]</span>
                                </div>
                                <input type="range" class="input-range" id="input-param2" min="1" max="10" value="4"
                                       oninput="updateTextOnly()">
                            </div>
                        </div>
                    </div>
                    <button class="action-btn" style="margin-bottom: 12px; width: 100%; justify-content: center;" onclick="runSimulation()">Activate Matrix Calculation &rarr;</button>
                    <div class="terminal-log" id="lab-feedback">
                        [INJECT INITIAL GUIDE CHARACTER SPEECH GREETING AND COZY SANDBOX MISSION OBJECTIVE TEXT HERE]
                    </div>
                </div>
            </div>
        </section>
    </div>
    <script>
        // Centralized data-driven model representation layer
        let simState = {
            param1: 3,
            param2: 4,
            isActive: false
        };

        function openTab(tabId) {
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('panel-' + tabId).classList.add('active');
            document.getElementById('btn-' + tabId).classList.add('active');
            if(tabId === 'lab') { updateTextOnly(); }
        }

        // [INJECT COMPLETE JAVASCRIPT LOGICAL FUNCTIONS HERE]
        // You must provide functional implementations for:
        // - updateTextOnly(): Sync slider values to state and labels.
        // - renderCanvasChanges(): Update vector parameters inside #viewport-canvas.
        // - runSimulation(): Trigger animations, rewards, and feedback logs.
    </script>
</body>
</html>
"""


# v3: cinematic scene-renderer prompt — adds mandatory Q1–Q4 topic analysis, real
# domain formulas, layered SVG scene rules with gradient-fill enforcement, embedded
# particle-system reference code, and a final quality-gate checklist. Designed to fix
# the "labeled flat circle" failure mode of the cozy-storyboard prompt.
_SIMULATION_TEMPLATE_V3 = """You are a Principal Educational Game Designer for Indian K-12 students. Your task: take a topic and grade level, and generate ONE complete, self-contained HTML interactive learning widget that looks like a polished classroom mini-game.

You must output a single complete HTML document. No truncation. No placeholder comments. Every function fully implemented.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE DESIGN PHILOSOPHY — READ BEFORE WRITING ANY CODE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Use EMOJIS as the primary visual language. NOT inline SVG paths. NOT geometric shapes.

Why: emojis render perfectly across all browsers, are universally recognizable, and look polished. Hand-coded SVG illustrations of plants/animals/people typically look broken or geometric. Use emojis instead.

Emoji palette by topic:
  • Biology/Nature: 🌱 🌿 🌳 🌻 🌼 🍂 🐹 🦋 🐦 🐟 🐝 🌍 🦠
  • Physics: 🛹 ⚽ 🎈 🧲 🚀 ⚙️ 🪂 🔆 ⚡ 💡
  • Chemistry: ⚗️ 🧪 🧊 💧 🔥 ⚛️ 💨
  • Earth/Sky: ☀️ ☁️ ⛅ 🌧️ 🌈 ❄️ 🌊 🏔️ 🌋 🏝️
  • Math: 🔺 ⚖️ 📐 📊 ➕ ➖ ✖️ ➗ 🎲 🧮
  • History: ⚔️ 🏛️ 📜 🗺️ 🏰 ⚓ 👑
  • People: 🧑‍🔬 👨‍🚀 🧑‍🌾 🧑‍🏫 👩‍⚕️ 🧑‍🎨

FORBIDDEN (automatic failures):
  ✗ Inline SVG <path> trying to draw a plant, animal, person, sun, leaf, soil, water
  ✗ <text> elements labeling scene objects (e.g., a "Soil" text on empty background)
  ✗ A bare colored circle representing a complex object
  ✗ Empty viewport that fails to render the scene
  ✗ Static scene that doesn't visibly mutate when sliders move
  ✗ Function bodies with only comments / TODOs / "// implement here"

REQUIRED (all must be present):
  ✓ Themed, playful title — examples: "The Biosphere Balance Lab", "Super Force Skatepark", "The Fraction Pizzeria", "Newton's Bowling Alley". NEVER use generic ("Photosynthesis Simulator").
  ✓ Scene = CSS layered gradient background + emoji elements positioned absolutely
  ✓ At least 4 visible emojis in the lab scene, each with a unique id
  ✓ Emoji size/position/transform/opacity changes when sliders move
  ✓ runSimulation() computes a REAL domain formula with actual math operators
  ✓ Two gauge cards showing computed values with units (e.g., "65%", "12.4 g")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DESIGN STEPS (think internally before writing)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1 — THEMED TITLE: invent a playful, memorable name.
  Photosynthesis → "The Biosphere Balance Lab"
  Newton's Laws → "Super Force Skatepark"
  Fractions → "The Pizza Slice Factory"
  Water Cycle → "Cloud Catcher Quest"
  Acids/Bases → "Color Drop Chemistry"
  WW2 → "The Alliance Map Room"
  Compound Interest → "The Money Tree Vault"

Step 2 — SCENE EMOJIS: choose 4-8 emojis matching the topic. Assign each a role.
  Photosynthesis: ☀️ ⛅ 🌱 💧 🌿 🦋
  Force: 🛹 ⛰️ 💨 ✋
  Water cycle: ☀️ ☁️ 🌧️ 🌊 🏔️
  Acids: ⚗️ 🧪 💧 🔥

Step 3 — TWO VARIABLES (sliders): real domain names with units.
  Photosynthesis: "Sunlight (%)" + "Water (%)"
  Force: "Push Strength (N)" + "Surface Friction (μ)"
  Compound Interest: "Interest Rate (%)" + "Years (yr)"
  Projectile: "Launch Angle (°)" + "Initial Velocity (m/s)"

Step 4 — DOMAIN FORMULA: the real equation that produces the gauge values.
  Photosynthesis: glucose_rate = min(sunlight, water) × 0.5
  Force: F = m × a  (with m fixed, a computed from push)
  Compound Interest: A = P × (1 + r/100)^t
  Projectile range: R = v² × sin(2θ) / 9.8

Step 5 — VISUAL MUTATIONS: how each emoji changes per slider value.
  Sunlight slider: sun font-size grows, cloud opacity drops, plant scale grows, sky gradient brightens
  Water slider: water droplet opacity rises, plant color saturation rises

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HTML TEMPLATE — fill every bracket with real, topic-specific content
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>[THEMED TITLE]</title>
<style>
:root {
  --primary: [TOPIC_COLOR — biology #16a34a, physics #2563eb, chemistry #f97316, math #8b5cf6, history #b45309];
  --primary-dark: [DARKER_SHADE of primary];
  --bg: [SOFT_BG_TINT matching topic];
  --border: [BORDER_COLOR matching topic, slightly darker than bg];
  --text-dark: [DARK_HEADING_COLOR];
  --text-body: #475569;
}
* { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Quicksand', system-ui, sans-serif; }
body { background: var(--bg); color: var(--text-body); min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 12px; }
header { text-align: center; margin: 10px 0 15px; }
header h1 { font-size: 1.6rem; color: var(--text-dark); margin-bottom: 4px; font-weight: 800; }
header p { font-size: 0.88rem; color: var(--text-body); font-weight: 600; }
.app-container { width: 100%; max-width: 600px; background: white; border-radius: 22px; box-shadow: 0 12px 40px rgba(0,0,0,0.08); border: 2px solid var(--border); overflow: hidden; }
.nav-tabs { display: flex; background: var(--bg); border-bottom: 2px solid var(--border); }
.tab-btn { flex: 1; padding: 14px 8px; border: none; background: none; font-size: 0.9rem; font-weight: 700; color: #94a3b8; cursor: pointer; border-bottom: 3px solid transparent; }
.tab-btn.active { color: var(--text-dark); background: white; border-bottom: 3px solid var(--primary); }
.panel { display: none; padding: 22px; min-height: 480px; }
.panel.active { display: flex; flex-direction: column; }
#panel-intro { align-items: center; text-align: center; }
.hero-emoji { font-size: 5rem; margin: 16px 0; line-height: 1; }
.intro-card { background: var(--bg); border: 1px solid var(--border); border-radius: 14px; padding: 20px; margin-bottom: 16px; }
.intro-card h2 { color: var(--text-dark); font-size: 1.3rem; margin-bottom: 10px; }
.intro-card p { font-size: 0.95rem; line-height: 1.6; color: var(--text-body); margin-bottom: 10px; }
.anatomy-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; margin-bottom: 16px; }
.anatomy-card { background: var(--bg); border: 1px solid var(--border); border-radius: 14px; padding: 18px; }
.anatomy-card h3 { color: var(--text-dark); font-size: 1.05rem; margin-bottom: 8px; }
.anatomy-card p { font-size: 0.88rem; color: var(--text-body); line-height: 1.5; }
.formula-pill { background: var(--bg); padding: 10px; border-radius: 8px; font-weight: 700; color: var(--text-dark); text-align: center; margin: 12px 0; font-size: 0.95rem; }

/* SCENE — critical visual area */
.scene {
  position: relative;
  width: 100%;
  height: 240px;
  border-radius: 14px;
  overflow: hidden;
  border: 2px solid var(--border);
  background: [SCENE_BACKGROUND_GRADIENT — examples:
    sky+soil: linear-gradient(to bottom, #87ceeb 0%, #b0e0ff 60%, #8b4513 60%, #654321 100%);
    sky+grass: linear-gradient(to bottom, #87ceeb 0%, #b0e0ff 70%, #90c860 70%, #4a7c2c 100%);
    ocean: linear-gradient(to bottom, #87ceeb 0%, #4a90d9 50%, #1e3a8a 100%);
    space: linear-gradient(to bottom, #0c0a3e 0%, #1e0a3e 100%);
    lab: linear-gradient(to bottom, #f0f9ff 0%, #e0e7ef 100%);
  ];
  margin-bottom: 14px;
  transition: background 0.4s ease;
}
.scene-emoji {
  position: absolute;
  transition: all 0.4s ease;
  line-height: 1;
}
.gauge-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0; }
.gauge-card { background: white; border: 1px solid var(--border); border-radius: 10px; padding: 12px; text-align: center; }
.gauge-label { font-size: 0.78rem; color: var(--text-body); font-weight: 600; }
.gauge-value { font-size: 1.4rem; color: var(--primary); font-weight: 800; margin-top: 4px; }
.slider-wrapper { background: var(--bg); padding: 12px; border-radius: 12px; border: 1px solid var(--border); margin-bottom: 10px; }
.slider-header { display: flex; justify-content: space-between; font-size: 0.9rem; font-weight: 700; margin-bottom: 6px; color: var(--text-dark); }
.slider-header span:last-child { color: var(--primary); }
input[type=range] { width: 100%; -webkit-appearance: none; height: 8px; border-radius: 4px; background: white; outline: none; cursor: pointer; }
input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 20px; height: 20px; border-radius: 50%; background: var(--primary); cursor: pointer; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
.run-btn { background: var(--primary); color: white; border: none; padding: 12px; font-size: 0.95rem; font-weight: 800; border-radius: 12px; cursor: pointer; width: 100%; margin: 10px 0; transition: background 0.2s; }
.run-btn:hover { background: var(--primary-dark); }
.feedback { background: white; border-left: 4px solid var(--primary); padding: 12px; border-radius: 8px; font-size: 0.9rem; line-height: 1.5; color: var(--text-dark); min-height: 80px; transition: border-color 0.3s; }
.action-btn { background: var(--primary); color: white; border: none; padding: 11px 26px; font-size: 0.95rem; font-weight: 700; border-radius: 22px; cursor: pointer; align-self: center; transition: background 0.2s; }
.action-btn:hover { background: var(--primary-dark); }
</style>
</head>
<body>
<header>
  <h1>[THEMED TITLE from Step 1]</h1>
  <p>Class [N] [SUBJECT]: [WITTY SUBTITLE describing what student explores]</p>
</header>
<div class="app-container">
  <nav class="nav-tabs">
    <button class="tab-btn active" id="btn-intro" onclick="openTab('intro')">1. [TAB_1_LABEL e.g. The Setup]</button>
    <button class="tab-btn" id="btn-concept" onclick="openTab('concept')">2. [TAB_2_LABEL e.g. How It Works]</button>
    <button class="tab-btn" id="btn-lab" onclick="openTab('lab')">3. [TAB_3_LABEL e.g. Run It]</button>
  </nav>

  <section id="panel-intro" class="panel active">
    <div class="hero-emoji">[1-3 EMOJIS representing topic e.g. 🌱☀️💧]</div>
    <div class="intro-card">
      <h2>[HOOK — engaging question or bold statement]</h2>
      <p>[PARAGRAPH 1 — narrative voice, sets up the scene/mystery]</p>
      <p>[PARAGRAPH 2 — introduces the 2 control variables, hints at what they discover]</p>
    </div>
    <button class="action-btn" onclick="openTab('concept')">[NEXT_LABEL e.g. See How It Works] →</button>
  </section>

  <section id="panel-concept" class="panel">
    <h2 style="color:var(--text-dark);margin-bottom:6px;font-size:1.3rem;">[CONCEPT SECTION TITLE]</h2>
    <p style="margin-bottom:14px;color:var(--text-body);font-size:0.9rem;">[ONE LINE introducing the two factor cards]</p>
    <div class="anatomy-grid">
      <div class="anatomy-card">
        <h3>[VAR_1_EMOJI] [VARIABLE 1 NAME]</h3>
        <p>[3-4 sentences: what it is, how it affects the system, what happens at extremes, real-world example]</p>
      </div>
      <div class="anatomy-card">
        <h3>[VAR_2_EMOJI] [VARIABLE 2 NAME]</h3>
        <p>[3-4 sentences: what it is, how it affects the system, what happens at extremes, real-world example]</p>
      </div>
    </div>
    <div class="formula-pill">[FORMULA from Step 4, written clearly e.g. Rate = min(Sun, Water) × 0.5]</div>
    <button class="action-btn" onclick="openTab('lab')">[NEXT_LABEL e.g. Open the Lab] →</button>
  </section>

  <section id="panel-lab" class="panel">
    <div class="scene" id="scene">
      <!-- INSERT 4-8 POSITIONED EMOJI ELEMENTS WITH UNIQUE IDS. Examples:
        <div class="scene-emoji" id="e-sun" style="font-size:2.5rem;top:8%;right:10%;">☀️</div>
        <div class="scene-emoji" id="e-cloud" style="font-size:2rem;top:12%;left:18%;opacity:0.7;">☁️</div>
        <div class="scene-emoji" id="e-plant" style="font-size:3.5rem;left:42%;bottom:18%;">🌱</div>
        <div class="scene-emoji" id="e-water" style="font-size:1.4rem;left:60%;top:55%;">💧</div>
        <div class="scene-emoji" id="e-leaf" style="font-size:1.6rem;left:30%;bottom:30%;">🌿</div>
        <div class="scene-emoji" id="e-bug" style="font-size:1.4rem;left:70%;top:30%;">🦋</div>
      -->
      [PLACE 4-8 EMOJI ELEMENTS HERE — each must have unique id, absolute position, base font-size]
    </div>

    <div class="gauge-grid">
      <div class="gauge-card">
        <div class="gauge-label">[GAUGE_1_LABEL e.g. Oxygen (O₂)]</div>
        <div class="gauge-value" id="gauge1">[INITIAL_VALUE with unit]</div>
      </div>
      <div class="gauge-card">
        <div class="gauge-label">[GAUGE_2_LABEL e.g. Glucose Made]</div>
        <div class="gauge-value" id="gauge2">[INITIAL_VALUE with unit]</div>
      </div>
    </div>

    <div class="slider-wrapper">
      <div class="slider-header">
        <span>[VAR_1_EMOJI] [VARIABLE 1 NAME] ([unit])</span>
        <span id="txt-p1">[INITIAL_DESCRIPTOR]</span>
      </div>
      <input type="range" id="p1" min="0" max="100" value="40" oninput="updateScene()">
    </div>
    <div class="slider-wrapper">
      <div class="slider-header">
        <span>[VAR_2_EMOJI] [VARIABLE 2 NAME] ([unit])</span>
        <span id="txt-p2">[INITIAL_DESCRIPTOR]</span>
      </div>
      <input type="range" id="p2" min="0" max="100" value="60" oninput="updateScene()">
    </div>

    <button class="run-btn" onclick="runSimulation()">🔬 Run Analysis →</button>
    <div class="feedback" id="feedback">[INITIAL_MESSAGE inviting student to adjust sliders]</div>
  </section>
</div>

<script>
function openTab(id) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + id).classList.add('active');
  document.getElementById('btn-' + id).classList.add('active');
  if (id === 'lab') updateScene();
}

function updateScene() {
  const v1 = +document.getElementById('p1').value;
  const v2 = +document.getElementById('p2').value;

  // FULLY IMPLEMENT ALL FOUR BLOCKS BELOW. No TODO. No empty bodies.

  // 1. Update slider descriptor labels with topic-specific vocabulary
  //    Example: const labels = ['Pitch Dark','Dim','Soft','Bright','Brilliant','Blazing'];
  //             document.getElementById('txt-p1').textContent = labels[Math.min(5, Math.floor(v1/20))];

  // 2. Compute and update both gauge values with units
  //    Example: document.getElementById('gauge1').textContent = Math.round(min(v1,v2)*0.5) + ' g';

  // 3. Mutate AT LEAST 3 emoji styles (size, position, opacity, or transform)
  //    Example: document.getElementById('e-sun').style.fontSize = (1.8 + v1/30) + 'rem';
  //             document.getElementById('e-plant').style.transform = 'scale(' + (0.5 + Math.min(v1,v2)/120) + ')';
  //             document.getElementById('e-cloud').style.opacity = (1 - v1/120);

  // 4. Optionally update scene background based on slider state
  [WRITE ALL FOUR BLOCKS — real code, not comments]
}

function runSimulation() {
  const v1 = +document.getElementById('p1').value;
  const v2 = +document.getElementById('p2').value;
  updateScene();

  // FULLY IMPLEMENT — character-voice narrative with real math.

  // 1. Compute the real domain formula from Step 4 using v1 and v2
  // 2. Determine tier: high/medium/low based on result
  // 3. Set feedback border-color: green #16a34a / amber #d97706 / red #dc2626
  // 4. Set feedback.innerHTML with 4 parts (use <strong> for labels):
  //    - Conditions: what the sliders are set to
  //    - Formula: the equation with real numbers substituted
  //    - Result: the computed value with units
  //    - What this means: grade-appropriate explanation in narrative voice
  [WRITE ALL FOUR BLOCKS — real math and real strings]
}

window.addEventListener('DOMContentLoaded', updateScene);
</script>
</body>
</html>
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GRADE-LEVEL LANGUAGE CALIBRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Class 3-4:   Very simple words, max 12 words/sentence. Lots of emojis. No formulas shown. Whimsical titles.
Class 5-6:   Clear language. Key terms with one-line definitions. Simple formulas shown.
Class 7-8:   Standard academic vocabulary. Show formulas with variables. Cause-and-effect explanations.
Class 9-10:  Full scientific terminology. Real data values. Formulas with brief derivation hints.
Class 11-12: Rigorous depth. Numeric datasets. Edge cases and real-world implications discussed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL CHECKLIST — verify ALL before outputting
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

□ Title is themed and playful (NOT "X Simulator" or "Understanding X")
□ Hero emoji(s) shown on intro tab
□ Lab scene contains AT LEAST 4 positioned emoji elements with unique ids
□ ZERO inline SVG <path> elements depicting natural objects
□ ZERO <text> elements naming scene objects on the scene
□ Both sliders fire updateScene() on oninput
□ updateScene() mutates at least 3 emoji styles total
□ updateScene() updates both gauge values with units
□ runSimulation() uses real domain formula with actual math operators
□ Feedback log uses narrative voice with formula and substituted numbers
□ ALL function bodies fully implemented (zero TODOs, zero empty bodies)
□ Output is one complete HTML file, no external dependencies

NOW GENERATE THE COMPLETE HTML FILE.
Output ONLY the HTML, starting directly with <!DOCTYPE html>. Nothing before or after."""


def _extract_summary_text(summary_blocks, summary_raw: str | None) -> str:
    """Convert summary_blocks (or raw summary) into a plain-text grounded context string."""
    if not summary_blocks and not summary_raw:
        return ""
    if not summary_blocks:
        return (summary_raw or "")[:2000]

    parts = []
    for block in summary_blocks:
        btype = block.get("type")
        if btype == "concept":
            parts.append(f"Concept: {block.get('title', '')}\n{block.get('content', '')}")
        elif btype == "steps":
            steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(block.get("steps", [])))
            parts.append(f"Steps — {block.get('title', '')}:\n{steps}")
        elif btype == "terms":
            terms = "\n".join(f"- {t['term']}: {t.get('meaning', '')}" for t in block.get("items", []))
            parts.append(f"Key Terms:\n{terms}")
        elif btype == "formula":
            parts.append(f"Formula: {block.get('label', '')} = {block.get('expression', '')}")
        elif btype == "analogy":
            parts.append(f"Analogy: {block.get('content', '')}")
        elif btype == "fact":
            facts = "\n".join(f"- {f}" for f in block.get("items", []))
            parts.append(f"Facts:\n{facts}")

    combined = "\n\n".join(parts)
    return combined[:3000]


# LATEST: engine-selection prompt — picks Canvas 2D / SVG / hybrid renderer based on
# subject type, includes per-engine code patterns (gradient helpers, bezier shapes,
# rAF physics loop, SVG mutation), mandatory particle system, and 4-part feedback.
_SIMULATION_TEMPLATE_LATEST = """You are a Principal Frontend Engineer and Interactive Education Architect. Generate ONE complete, self-contained, browser-ready HTML simulation file.

No truncation. No placeholder comments. No empty function bodies. Every function fully implemented. Output only raw HTML starting with <!DOCTYPE html>.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 0 — RENDERING STRATEGY SELECTION (decide this first)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Read the topic and subject, then select ONE rendering engine from below.
This decision governs how you build the entire canvas section.

┌─────────────────────────────────────────────────────────────────┐
│ SUBJECT / TOPIC TYPE          → RENDERING ENGINE                │
├─────────────────────────────────────────────────────────────────┤
│ Biology, Nature, Science      → CANVAS 2D (drawScene)           │
│   (plants, cells, ecosystems, │   ctx.bezierCurveTo for organic  │
│   organisms, photosynthesis)  │   shapes. Gradient fills.        │
│                               │   Particle DOM overlay.          │
├─────────────────────────────────────────────────────────────────┤
│ Physics, Motion, Forces       → CANVAS 2D + rAF PHYSICS LOOP    │
│   (projectile, pendulum,      │   requestAnimationFrame loop.    │
│   waves, electricity, optics) │   Real physics equations per     │
│                               │   frame. Trail rendering.        │
├─────────────────────────────────────────────────────────────────┤
│ Mathematics, Graphs           → CANVAS 2D (drawScene)           │
│   (functions, geometry,       │   Draw axes, tick marks, curve   │
│   calculus, statistics,       │   via ctx.beginPath. Label key   │
│   algebra, trigonometry)      │   points. Shade regions.         │
├─────────────────────────────────────────────────────────────────┤
│ Chemistry, Molecules          → CANVAS 2D (drawScene + rAF)     │
│   (atoms, bonds, reactions,   │   Circles for atoms with radial  │
│   periodic table, solutions)  │   gradient fills. Orbit arcs.    │
│                               │   Electron animation via rAF.    │
├─────────────────────────────────────────────────────────────────┤
│ History, Geography, Maps      → SVG (inline, mutable)           │
│   (battles, borders, trade    │   Path-based country fills.      │
│   routes, timelines, climate) │   Arrow markers for movement.    │
│                               │   Timeline bar at bottom.        │
├─────────────────────────────────────────────────────────────────┤
│ Economics, Data, Commerce     → CANVAS 2D (drawScene)           │
│   (supply/demand, GDP,        │   Draw live axes and curves.     │
│   inflation, market, trade)   │   Shade surplus/deficit areas.   │
│                               │   Moving equilibrium point.      │
├─────────────────────────────────────────────────────────────────┤
│ Social Studies, Psychology    → CANVAS 2D — civic infographic   │
│   (media, democracy, civics,  │   Network graphs, bar charts,    │
│   sociology, psychology,      │   pie charts, flow diagrams      │
│   political science)          │   drawn with ctx.beginPath +     │
│                               │   ctx.bezierCurveTo + gradients. │
│                               │   NEVER flat HTML <div> as the   │
│                               │   primary scene element.         │
└─────────────────────────────────────────────────────────────────┘

ABSOLUTE RULE — no exceptions:
The #viewport-canvas MUST contain a <canvas> OR an <svg> element.
A bare <div> with HTML children (boxes, labels) is REJECTED. The lab scene
is a real drawn illustration — never structural CSS divs labelled with the
topic name. This is the #1 failure mode and is automatically rejected.

After selecting the engine, resolve these 4 questions mentally:

Q1 — SCENE OBJECTS: List 8–12 real objects that visually represent this topic.
     Every object on the list MUST be rendered in the canvas.

Q2 — SLIDER VARIABLES: The 2 most important student-controllable variables.
     Use real domain-accurate names with units. Never "Level" or "Intensity" alone.

Q3 — VISUAL MUTATION MAP: For each slider, list 5+ things that change visually
     when it moves.

Q4 — DOMAIN FORMULA: The real governing equation used in runSimulation().

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — ENGINE-SPECIFIC IMPLEMENTATION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ ENGINE A — CANVAS 2D (drawScene)
  Used for: Biology, Math, Economics, Chemistry (static view)

  Architecture:
  ```
  const canvas = document.getElementById('labCanvas');
  const ctx    = canvas.getContext('2d');

  function drawScene(v1, v2) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    // Draw in layer order — each layer a clearly labelled block:
    // LAYER 1: Background (sky/grid/space gradient)
    // LAYER 2: Environment (ground, axes, atmosphere, terrain)
    // LAYER 3: Main subject (plant, curve, molecule, chart)
    // LAYER 4: Detail overlays (labels, veins, tick marks, arrows)
    // LAYER 5: Output indicator (progress bar, gauge, meter)
  }

  function onSlider() {
    const v1 = +document.getElementById('p1').value;
    const v2 = +document.getElementById('p2').value;
    updateTextOnly(v1, v2);
    drawScene(v1, v2);          // full redraw on every drag
    restartParticles(v1, v2);
  }
  ```

  Canvas gradient helpers — use for EVERY fill:
  ```
  // Linear gradient
  const g = ctx.createLinearGradient(x1, y1, x2, y2);
  g.addColorStop(0, '#color1'); g.addColorStop(1, '#color2');
  ctx.fillStyle = g;

  // Radial gradient (for sun, atom cores, glows)
  const r = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
  r.addColorStop(0, '#bright'); r.addColorStop(1, 'transparent');
  ctx.fillStyle = r;
  ```

  Organic bezier shapes (use for ALL natural/curved forms):
  ```
  ctx.beginPath();
  ctx.moveTo(startX, startY);
  ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, endX, endY);
  ctx.bezierCurveTo(cp3x, cp3y, cp4x, cp4y, startX, startY);
  ctx.fill(); // or ctx.stroke()
  ```

  Rounded rect helper (use for bars, cards, labels):
  ```
  function rRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y);
    ctx.arcTo(x+w, y, x+w, y+r, r); ctx.lineTo(x+w, y+h-r);
    ctx.arcTo(x+w, y+h, x+w-r, y+h, r); ctx.lineTo(x+r, y+h);
    ctx.arcTo(x, y+h, x, y+h-r, r); ctx.lineTo(x, y+r);
    ctx.arcTo(x, y, x+r, y, r); ctx.closePath();
  }
  ```

  Color interpolation helper:
  ```
  function lerp(h1, h2, t) {
    const p = x => [parseInt(x.slice(1,3),16), parseInt(x.slice(3,5),16), parseInt(x.slice(5,7),16)];
    const [r1,g1,b1] = p(h1), [r2,g2,b2] = p(h2);
    return '#' + [r1+(r2-r1)*t, g1+(g2-g1)*t, b1+(b2-b1)*t]
      .map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
  }
  ```

  FORBIDDEN in Engine A:
  ✗ Flat solid ctx.fillStyle = '#hexcolor' on any major scene element
  ✗ ctx.fillRect for the main subject (use bezierCurveTo paths)
  ✗ Static canvas — drawScene() must be called on every oninput

────────────────────────────────────────────────────
■ ENGINE B — CANVAS 2D + requestAnimationFrame PHYSICS LOOP
  Used for: Physics, Motion, Chemistry (animated molecules)

  Architecture:
  ```
  let animId = null;
  let state  = {};   // all physics state lives here

  function initState(v1, v2) {
    // Build initial state from slider values
    // e.g. state = { x: 0, y: 0, vx: ..., vy: ..., t: 0 }
  }

  function physicsStep(dt) {
    // Apply real physics equations each frame
    // e.g. state.vy += GRAVITY * dt;
    //      state.x  += state.vx * dt;
    //      state.y  += state.vy * dt;
    // Handle bounce / collision / stop conditions
  }

  function renderFrame() {
    ctx.clearRect(0, 0, CW, CH);
    drawBackground();      // static environment
    drawSubject(state);    // position-dependent subject
    drawTrail(state);      // motion trail if applicable
    drawHUD(state);        // velocity / energy / angle readout
  }

  function loop(ts) {
    const dt = Math.min((ts - (loop.last || ts)) / 1000, 0.05);
    loop.last = ts;
    physicsStep(dt);
    renderFrame();
    if (!state.done) animId = requestAnimationFrame(loop);
  }

  function startSim() {
    if (animId) cancelAnimationFrame(animId);
    initState(+p1.value, +p2.value);
    animId = requestAnimationFrame(loop);
  }

  function onSlider() {
    updateTextOnly(+p1.value, +p2.value);
    if (animId) cancelAnimationFrame(animId);
    initState(+p1.value, +p2.value);
    renderFrame();   // static preview while not animating
  }
  ```

  runSimulation() for Engine B:
  - Calls startSim() to launch the animation loop
  - Also computes the theoretical result using the real formula
  - Displays it in #lab-feedback after a short delay (setTimeout 400ms)

────────────────────────────────────────────────────
■ ENGINE C — SVG (inline, mutable via JS)
  Used for: History, Geography, Maps

  Architecture:
  ```html
  <!-- SVG inside #viewport-canvas, ALL elements have IDs -->
  <svg id="mainSvg" viewBox="0 0 380 390"
       xmlns="http://www.w3.org/2000/svg"
       style="position:absolute;top:0;left:0;width:100%;height:100%">
    <defs>
      <!-- ALL gradients defined here with unique IDs -->
      <!-- ALL filters (glow, shadow) defined here -->
    </defs>
    <!-- Elements in layer order, each with a unique id="..." -->
  </svg>
  ```

  JS mutation pattern:
  ```
  function renderCanvasChanges(v1, v2) {
    // Mutate gradient stops
    document.querySelector('#gradId stop:first-child')
      .setAttribute('stop-color', lerp('#color1','#color2', v1/100));

    // Mutate element geometry
    document.getElementById('elemId').setAttribute('r', 10 + v1 * 0.3);
    document.getElementById('elemId').style.opacity = 0.3 + v2 * 0.007;

    // Mutate path fill via gradient
    document.getElementById('pathId').setAttribute('fill', 'url(#gradId)');

    // Restart particles
    restartParticles(v1, v2);
  }
  ```

  SVG rules:
  ✓ Every <rect>, <circle>, <ellipse>, <path> fill = url(#gradientId)
  ✓ Light sources use <filter><feGaussianBlur/></filter>
  ✓ Country/region fills use <linearGradient> with era-appropriate palette
  ✓ Movement arrows use <marker> arrowhead definitions
  ✓ Timeline bar at bottom with <rect> segments and <text> year labels
  ✓ Minimum 10 distinct SVG elements

────────────────────────────────────────────────────
■ ENGINE D — CANVAS 2D CIVIC INFOGRAPHIC
  Used for: Social Studies, Media, Democracy, Civics, Sociology, Psychology, Economics

  THIS ENGINE USES THE SAME ARCHITECTURE AS ENGINE A.
  The viewport contains a single <canvas id="labCanvas" width="380" height="390"></canvas>
  with the same drawScene(v1, v2) → onSlider() pattern. There are NO structural HTML
  divs inside #viewport-canvas. The entire scene is drawn with ctx.* calls.

  Topic-to-visual mapping — pick the closest pattern for your topic:

  • Media / Press / Journalism → NETWORK GRAPH
      Draw 4-6 labelled circle nodes (Citizens, TV, Newspaper, Internet, Government,
      Advertisers) connected by curved bezier edges. Edge stroke width = slider value.
      Node fill = radial gradient. Use ctx.fillText for short labels (1 word).
      Animated dots travel along edges via the particle system.

  • Democracy / Voting / Civics → STACKED VOTE CHART
      Draw a horizontal stacked bar showing party color blocks (red/blue/green segments
      drawn as gradient-filled rRect's). Above it, draw a row of ballot icons as
      rounded rectangles. Below it, a turnout meter (gradient-filled arc). Slider 1
      = participation %, Slider 2 = polarization.

  • Sociology / Demographics → POPULATION PYRAMID
      Two mirrored gradient-filled bar charts (male left, female right) for age bands,
      drawn as rRect's with linear gradients. Center axis labels via ctx.fillText.
      Sliders mutate band widths (population per age group).

  • Psychology / Behavior → DUAL-DIAL DASHBOARD
      Two arc gauges drawn with ctx.arc + radial gradient strokes (mood, energy /
      stress, focus). A central illustrated figure built from bezierCurveTo paths
      (head circle + body curves). Sliders mutate gauge angles and figure color tint.

  • Economics / Trade → SUPPLY-DEMAND CHART
      Draw X/Y axes via ctx.lineTo, two curves (supply ascending, demand descending)
      via bezierCurveTo with gradient strokes. Mark equilibrium point as a radial-
      gradient circle. Shade surplus/deficit regions with gradient fills.

  Architecture (identical to Engine A):
  ```
  const canvas = document.getElementById('labCanvas');
  const ctx    = canvas.getContext('2d');

  function drawScene(v1, v2) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    // LAYER 1: Background gradient (warm civic tones for media, cool for civics)
    // LAYER 2: Axes / chart frame / network grid
    // LAYER 3: Main data — nodes + edges, bars, curves, pyramid bands
    // LAYER 4: Labels via ctx.fillText (1-2 words per element, NOT entire phrases)
    // LAYER 5: Animated indicator (current value pointer, equilibrium dot, etc.)
  }
  ```

  FORBIDDEN in Engine D (same as A, plus):
  ✗ HTML <div> elements inside #viewport-canvas (use only <canvas>)
  ✗ A scene built from two labelled colored rectangles — this is rejected on sight
  ✗ ctx.fillRect with a single solid color as the main subject
  ✗ Treating the topic as "draw a box for concept A and a box for concept B"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — PARTICLE SYSTEM (mandatory for ALL engines)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Always uses DOM particles positioned over the canvas container.
Choose particle symbol by topic:

  Biology / Nature    → 'O₂'  '○'  'H₂O'  '●'       color: #7dd3fc
  Physics / Energy    → '✦'   '⚡'  '→'    '∿'        color: #fbbf24
  Chemistry           → 'e⁻'  '⊕'  '○'   molecule    color: #a78bfa
  Math                → 'x²'  '∑'  '·'   '∞'         color: #34d399
  History / Geography → '∘'   '▶'  '⚑'               color: #fb923c
  Economics           → '◈'   '↑'  '%'   '$'         color: #4ade80
  Social / Psychology → '◉'   '→'  '↔'               color: #60a5fa

Particle system implementation (same for all engines):
```javascript
let _pids = [];
function clearParticles() { _pids.forEach(clearInterval); _pids = []; }

function spawnStream(containerId, x, yStart, symbol, color, rateMs, floatUp) {
  const wrap = document.getElementById(containerId);
  const anim = floatUp ? 'simFloat' : 'simSink';
  const id = setInterval(() => {
    const p    = document.createElement('div');
    const ox   = x + (Math.random() * 28 - 14);
    const dur  = (1.4 + Math.random() * 1.2).toFixed(2);
    p.style.cssText = [
      'position:absolute',
      `left:${ox}px`,
      `top:${yStart}px`,
      `color:${color}`,
      'font-size:' + (9 + Math.random() * 4).toFixed(0) + 'px',
      'font-weight:800',
      'pointer-events:none',
      'z-index:20',
      `text-shadow:0 0 5px ${color}`,
      `animation:${anim} ${dur}s ease-out forwards`
    ].join(';');
    p.textContent = symbol;
    wrap.appendChild(p);
    setTimeout(() => { if (p.parentNode) p.parentNode.removeChild(p); }, dur * 1000 + 200);
  }, rateMs);
  _pids.push(id);
}

function restartParticles(v1, v2) {
  clearParticles();
  // Call spawnStream() with topic-appropriate args
  // Rate = Math.max(250, 2200 - (v1 * 10 + v2 * 8))
  // Higher slider values = faster particle emission
}
```

CSS for particles (include in <style>):
```css
@keyframes simFloat {
  0%   { opacity:0; transform:translateY(0)    scale(0.5); }
  15%  { opacity:1; }
  85%  { opacity:0.9; }
  100% { opacity:0; transform:translateY(-185px) scale(1.1); }
}
@keyframes simSink {
  0%   { opacity:0; transform:translateY(0); }
  20%  { opacity:0.9; }
  100% { opacity:0; transform:translateY(90px); }
}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — JAVASCRIPT FUNCTION SPECS (all engines)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▸ updateTextOnly(v1, v2) — fires on every oninput
  Maps slider values to domain-accurate qualitative labels.
  Use 10-element arrays indexed by Math.floor(value/10):
  ```
  const labels1 = ['label0','label1','label2',...,'label9'];
  document.getElementById('txt-p1').textContent =
    labels1[Math.min(9, Math.floor(v1/10))];
  ```
  Labels must use proper subject vocabulary for the topic and grade.

▸ renderCanvasChanges(v1, v2) OR drawScene(v1, v2) — fires on every oninput
  For Engines A/B/D: call drawScene() which redraws everything.
  For Engine C (SVG): mutate ≥5 SVG attributes per slider.
  In ALL cases: call restartParticles(v1, v2).

▸ runSimulation() — fires on button click
  1. Read v1 = +p1.value, v2 = +p2.value
  2. Apply the real domain formula from Step 0 Q4
  3. Compute result with actual JS math (no hardcoded strings)
  4. Determine tier: optimal / moderate / critical
  5. Write to #lab-feedback with this exact 4-part structure:
  ```
  fb.innerHTML = `
    <strong>[STATUS EMOJI + STATUS LABEL]</strong><br><br>
    <span style="color:#9ca3af;font-size:0.78rem;">━ CONDITIONS ━</span><br>
    [Variable 1 name]: <b>[v1 value + unit]</b> | [Variable 2 name]: <b>[v2 value + unit]</b><br><br>
    <span style="color:#9ca3af;font-size:0.78rem;">━ [FORMULA NAME] ━</span><br>
    [Formula with values substituted]: <b>[computed result + unit]</b><br>
    [Key derived metric label]: <b>[value]</b><br><br>
    <span style="color:#9ca3af;font-size:0.78rem;">━ OUTPUT ━</span><br>
    [Output metric 1]: <b>[value]</b> | [Output metric 2]: <b>[value]</b><br><br>
    <span style="font-size:0.82rem;">[Grade-appropriate interpretation, 1–2 sentences]</span>
  `;
  ```
  6. Set fb.style.borderLeftColor:
     Optimal  → '#16a34a'   Moderate → '#d97706'   Critical → '#dc2626'

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — INTRO TAB ILLUSTRATION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For Canvas 2D engines (A, B, D):
  Use a second <canvas id="introCanvas" width="680" height="280">
  Draw the topic scene statically using the same drawing techniques.
  Call a self-invoking function: (function drawIntro() { ... })();
  Must show ALL scene objects from Q1. Labels using ctx.fillText().

For SVG engine (C — History/Geography):
  Inline SVG viewBox="0 0 680 280" with full scene.
  Same gradient and filter rules as the lab SVG.
  Static — no JS needed for the intro illustration.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — HTML SHELL (fill all brackets, change nothing else)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[TOPIC] Interactive Simulation</title>
  <style>
    :root {
      --accent:  [PRIMARY_COLOR];
      --accent2: [DARKER_SHADE];
      --bg:      [SOFT_BACKGROUND];
      --border:  [BORDER_COLOR];
      --panel:   [PANEL_BG];
      --canvas-bg: #071a2e;
    }
    * { box-sizing:border-box; margin:0; padding:0;
        font-family:'Quicksand',system-ui,sans-serif;
        -webkit-tap-highlight-color:transparent; }
    body { background:var(--bg); color:#1e293b; min-height:100vh;
           display:flex; flex-direction:column; align-items:center; padding:10px; }

    header { text-align:center; margin:8px 0 14px; }
    header h1 { font-size:1.55rem; font-weight:800; color:var(--accent2); margin-bottom:2px; }
    header p  { font-size:0.82rem; color:var(--accent); font-weight:700;
                text-transform:uppercase; letter-spacing:1px; }

    .app-container { width:100%; max-width:920px; background:white;
                     border-radius:22px; border:2px solid var(--border);
                     box-shadow:0 12px 40px rgba(0,0,0,0.08); overflow:hidden; }

    .nav-tabs { display:flex; background:[TAB_BG]; border-bottom:2px solid var(--border); }
    .tab-btn  { flex:1; padding:13px 8px; border:none; background:none;
                font-size:0.92rem; font-weight:700; color:#a3a3a3; cursor:pointer;
                border-bottom:3px solid transparent; font-family:inherit; transition:all 0.2s; }
    .tab-btn.active { color:var(--accent2); background:white; border-bottom:3px solid var(--accent); }

    .panel        { display:none; padding:22px; min-height:500px;
                    background:white; animation:fadeIn 0.3s ease; }
    .panel.active { display:flex; flex-direction:column; }
    @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }

    /* INTRO */
    #panel-intro { align-items:center; text-align:center; padding:24px 18px; }
    .intro-canvas-wrap { width:100%; max-width:680px; margin-bottom:18px;
                         border-radius:18px; overflow:hidden;
                         box-shadow:0 4px 24px rgba(0,0,0,0.1); line-height:0; }
    .intro-canvas-wrap canvas,
    .intro-canvas-wrap svg { display:block; width:100%; height:auto; }
    .intro-text-box { max-width:640px; background:var(--bg);
                      border:1px solid var(--border); border-radius:16px;
                      padding:22px; margin-bottom:18px; }
    .intro-text-box h2 { color:var(--accent2); font-size:1.25rem; margin-bottom:10px; }
    .intro-text-box p  { font-size:0.93rem; line-height:1.65; color:#374151; margin-bottom:8px; }
    .formula-box { background:var(--bg); border-radius:10px; padding:10px;
                   font-size:0.88rem; color:var(--accent2); font-weight:700; }

    /* CONCEPT */
    #panel-concept h2 { color:var(--accent2); font-size:1.2rem; margin-bottom:4px; }
    .concept-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
                    gap:16px; margin:16px 0; }
    .c-card     { background:var(--bg); border:1px solid var(--border);
                  border-radius:16px; padding:20px; }
    .c-card h3  { color:var(--accent2); font-size:1.05rem; margin-bottom:8px; }
    .c-card p   { font-size:0.87rem; color:#374151; line-height:1.55; }
    .c-tag      { display:inline-block; margin-top:10px; padding:3px 12px;
                  border-radius:20px; font-size:0.72rem; font-weight:700; color:white;
                  background:var(--accent); text-transform:uppercase; }

    /* LAB */
    .workbench  { display:grid; grid-template-columns:1fr; gap:18px; width:100%; }
    @media(min-width:720px) { .workbench { grid-template-columns:1.2fr 0.8fr; } }

    #viewport-canvas { position:relative; overflow:hidden;
                       background:var(--canvas-bg); border-radius:18px;
                       height:390px; border:2px solid #1e3a5f; line-height:0; }
    #viewport-canvas canvas { display:block; width:100%; height:100%; }

    .ctrl-panel { background:var(--panel); border:1px solid var(--border);
                  border-radius:16px; padding:16px;
                  display:flex; flex-direction:column; gap:12px; }
    .ctrl-panel > h3 { font-size:0.8rem; color:var(--accent2); text-transform:uppercase;
                       letter-spacing:0.5px; border-bottom:1px solid var(--border);
                       padding-bottom:6px; }

    .slider-wrap { background:white; border:1px solid var(--border);
                   padding:12px; border-radius:12px; }
    .slider-head { display:flex; justify-content:space-between;
                   font-size:0.83rem; font-weight:700; margin-bottom:6px; color:#1f2937; }
    .slider-head span:last-child { color:var(--accent); }

    input[type=range] { width:100%; -webkit-appearance:none; height:9px;
                        border-radius:20px; background:var(--bg); outline:none; cursor:pointer; }
    input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; width:20px; height:20px;
      border-radius:50%; background:var(--accent); border:3px solid white;
      box-shadow:0 2px 6px rgba(0,0,0,0.2); cursor:pointer; }

    .run-btn { background:linear-gradient(135deg, var(--accent), var(--accent2));
               color:white; border:none; padding:12px; font-size:0.95rem; font-weight:700;
               border-radius:30px; cursor:pointer; font-family:inherit; transition:all 0.2s;
               box-shadow:0 3px 12px rgba(0,0,0,0.15); }
    .run-btn:hover { transform:translateY(-1px); }

    .feedback { background:white; border-left:4px solid var(--accent);
                padding:12px; border-radius:8px; font-size:0.83rem;
                line-height:1.55; min-height:90px; color:#374151; transition:border-color 0.4s; }

    .action-btn { background:linear-gradient(135deg, var(--accent), var(--accent2));
                  color:white; border:none; padding:11px 28px; font-size:0.95rem;
                  font-weight:700; border-radius:30px; cursor:pointer;
                  font-family:inherit; align-self:center; transition:all 0.2s; }
    .action-btn:hover { transform:translateY(-1px); }

    /* PARTICLES */
    @keyframes simFloat {
      0%  { opacity:0; transform:translateY(0)     scale(0.5); }
      15% { opacity:1; }
      85% { opacity:0.9; }
      100%{ opacity:0; transform:translateY(-185px) scale(1.1); }
    }
    @keyframes simSink {
      0%  { opacity:0; transform:translateY(0); }
      20% { opacity:0.9; }
      100%{ opacity:0; transform:translateY(90px); }
    }

    /* TOPIC-SPECIFIC additions go here */
    [TOPIC_SPECIFIC_CSS]
  </style>
</head>
<body>

<header>
  <h1>[EMOJI] [TOPIC NAME]</h1>
  <p>[SUBJECT AREA] · [GRADE LABEL] · Interactive Simulation</p>
</header>

<div class="app-container">
  <nav class="nav-tabs">
    <button class="tab-btn active" id="btn-intro"   onclick="openTab('intro')">1. Introduction</button>
    <button class="tab-btn"        id="btn-concept" onclick="openTab('concept')">2. Core Concepts</button>
    <button class="tab-btn"        id="btn-lab"     onclick="openTab('lab')">3. Interactive Lab</button>
  </nav>

  <!-- ══════════════════════════ TAB 1 — INTRODUCTION ══════════════════════════ -->
  <section id="panel-intro" class="panel active">
    <div class="intro-canvas-wrap">
      [INTRO_ILLUSTRATION]
      <!-- Canvas engines: <canvas id="introCanvas" width="680" height="280"></canvas> -->
      <!-- SVG engine:     <svg viewBox="0 0 680 280" ...> full scene </svg>           -->
    </div>
    <div class="intro-text-box">
      <h2>[HOOK_TITLE — engaging question or bold statement]</h2>
      <p>[PARAGRAPH_1 — grade-appropriate explanation: what the topic is and why it matters]</p>
      <p>[PARAGRAPH_2 — how the two key variables connect to this topic]</p>
      <p class="formula-box">[DOMAIN_FORMULA — written out clearly with variable names]</p>
    </div>
    <button class="action-btn" onclick="openTab('concept')">Explore Core Concepts →</button>
  </section>

  <!-- ══════════════════════════ TAB 2 — CORE CONCEPTS ═════════════════════════ -->
  <section id="panel-concept" class="panel">
    <h2>[CONCEPT_SECTION_TITLE]</h2>
    <p style="font-size:0.88rem;color:#6b7280;margin-bottom:4px;">[CONTEXT_SETTER — 1 sentence]</p>
    <div class="concept-grid">
      <div class="c-card">
        <h3>[VARIABLE_1_NAME with emoji]</h3>
        <p>[3–4 sentences: what it is, how it affects the system, extremes, real example]</p>
        <span class="c-tag">Factor A — [SHORT_LABEL]</span>
      </div>
      <div class="c-card">
        <h3>[VARIABLE_2_NAME with emoji]</h3>
        <p>[3–4 sentences: what it is, how it affects the system, extremes, real example]</p>
        <span class="c-tag">Factor B — [SHORT_LABEL]</span>
      </div>
    </div>
    [OPTIONAL_CONCEPT_DIAGRAM — small SVG or canvas showing variable interaction]
    <button class="action-btn" onclick="openTab('lab')">Launch Interactive Lab →</button>
  </section>

  <!-- ══════════════════════════ TAB 3 — INTERACTIVE LAB ═══════════════════════ -->
  <section id="panel-lab" class="panel">
    <div class="workbench">

      <div id="viewport-canvas">
        [LAB_CANVAS_OR_SVG]
        <!-- Engine A/B: <canvas id="labCanvas" width="380" height="390"></canvas> -->
        <!-- Engine C:   Full SVG with all elements having id attributes             -->
        <!-- Engine D:   <canvas id="labCanvas" width="380" height="390"></canvas> (same as A) -->
        <!-- Particles appended here by JS -->
      </div>

      <div class="ctrl-panel">
        <h3>⚙️ Tune Conditions</h3>

        <div class="slider-wrap">
          <div class="slider-head">
            <span>[VARIABLE_1_LABEL with unit]</span>
            <span id="txt-p1">[DEFAULT_LABEL_1]</span>
          </div>
          <input type="range" id="p1" min="1" max="100" value="30"
            oninput="onSlider()">
        </div>

        <div class="slider-wrap">
          <div class="slider-head">
            <span>[VARIABLE_2_LABEL with unit]</span>
            <span id="txt-p2">[DEFAULT_LABEL_2]</span>
          </div>
          <input type="range" id="p2" min="1" max="100" value="50"
            oninput="onSlider()">
        </div>

        <button class="run-btn" onclick="runSimulation()">🔬 Run Analysis →</button>

        <div class="feedback" id="lab-feedback">
          [INITIAL_FEEDBACK — topic-specific instruction for the student]
        </div>
      </div>

    </div>
  </section>
</div>

<script>
/* ── TAB NAVIGATION ─────────────────────────────────────── */
function openTab(id) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + id).classList.add('active');
  document.getElementById('btn-' + id).classList.add('active');
  if (id === 'lab') onSlider();
}

/* ── COLOUR HELPERS ─────────────────────────────────────── */
function lerp(h1, h2, t) {
  const p = x => [parseInt(x.slice(1,3),16), parseInt(x.slice(3,5),16), parseInt(x.slice(5,7),16)];
  const [r1,g1,b1] = p(h1), [r2,g2,b2] = p(h2);
  return '#' + [r1+(r2-r1)*t, g1+(g2-g1)*t, b1+(b2-b1)*t]
    .map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
}

/* ── ROUNDED RECT (Canvas helper) ───────────────────────── */
function rRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y);
  ctx.arcTo(x+w, y, x+w, y+r, r); ctx.lineTo(x+w, y+h-r);
  ctx.arcTo(x+w, y+h, x+w-r, y+h, r); ctx.lineTo(x+r, y+h);
  ctx.arcTo(x, y+h, x, y+h-r, r); ctx.lineTo(x, y+r);
  ctx.arcTo(x, y, x+r, y, r); ctx.closePath();
}

/* ── PARTICLE SYSTEM ────────────────────────────────────── */
let _pids = [];
function clearParticles() { _pids.forEach(clearInterval); _pids = []; }
function spawnStream(containerId, x, yStart, symbol, color, rateMs, floatUp) {
  const wrap = document.getElementById(containerId);
  const anim = floatUp !== false ? 'simFloat' : 'simSink';
  const id = setInterval(() => {
    const p   = document.createElement('div');
    const ox  = x + (Math.random() * 28 - 14);
    const dur = (1.4 + Math.random() * 1.2).toFixed(2);
    p.style.cssText = [
      'position:absolute', `left:${ox}px`, `top:${yStart}px`,
      `color:${color}`, `font-size:${(9 + Math.random()*4)|0}px`,
      'font-weight:800', 'pointer-events:none', 'z-index:20',
      `text-shadow:0 0 5px ${color}`,
      `animation:${anim} ${dur}s ease-out forwards`
    ].join(';');
    p.textContent = symbol;
    wrap.appendChild(p);
    setTimeout(() => { if (p.parentNode) p.parentNode.removeChild(p); }, +dur * 1000 + 200);
  }, rateMs);
  _pids.push(id);
}
function restartParticles(v1, v2) {
  clearParticles();
  [PARTICLE_SPAWN_CALLS]
  /* Example:
     const rate = Math.max(250, 2200 - (v1*10 + v2*8));
     if (v1 > 10 && v2 > 10)
       spawnStream('viewport-canvas', 150, 185, 'O₂', '#7dd3fc', rate, true);
  */
}

/* ── UPDATE TEXT LABELS (fires on every drag) ───────────── */
function updateTextOnly(v1, v2) {
  [FULL_LABEL_IMPLEMENTATION]
  /* Template:
     const L1 = ['label0','label1','label2','label3','label4',
                 'label5','label6','label7','label8','label9'];
     document.getElementById('txt-p1').textContent = L1[Math.min(9, (v1/10)|0)];
  */
}

/* ── DRAW / RENDER (fires on every drag) ────────────────── */
[ENGINE_SPECIFIC_DRAW_CODE]
/*
  Engine A/D: function drawScene(v1, v2) { ... }
  Engine B:   function initState(v1,v2){} function physicsStep(dt){} function renderFrame(){}
              function startSim(){} let animId=null;
  Engine C:   function renderCanvasChanges(v1, v2) { ... }
*/

/* ── UNIFIED SLIDER HANDLER ─────────────────────────────── */
function onSlider() {
  const v1 = +document.getElementById('p1').value;
  const v2 = +document.getElementById('p2').value;
  updateTextOnly(v1, v2);
  [DRAW_CALL]   // drawScene(v1,v2) | renderCanvasChanges(v1,v2) | renderFrame()
  restartParticles(v1, v2);
}

/* ── RUN SIMULATION ─────────────────────────────────────── */
function runSimulation() {
  const v1 = +document.getElementById('p1').value;
  const v2 = +document.getElementById('p2').value;
  [FULL_SIMULATION_MATH_AND_OUTPUT]
  /*
    1. Compute real formula result using v1, v2
    2. Determine tier (optimal/moderate/critical)
    3. Set document.getElementById('lab-feedback').style.borderLeftColor
    4. Set document.getElementById('lab-feedback').innerHTML with 4-part structure
    For Engine B: also call startSim() to launch animation
  */
}

/* ── INTRO CANVAS DRAW (Engine A/B/D only) ──────────────── */
[INTRO_DRAW_CODE]
/* Self-invoking: (function drawIntro() { const c=document.getElementById('introCanvas'); ... })(); */

/* ── INIT ───────────────────────────────────────────────── */
window.addEventListener('DOMContentLoaded', () => {
  [INTRO_INIT]   // drawIntro() call if canvas-based intro
  onSlider();
});
</script>
</body>
</html>
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6 — GRADE LANGUAGE CALIBRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Apply to ALL text — intro, cards, labels, feedback:

  Class 3–4   Simple words. Max 12-word sentences. Fun analogies. No formulas. Use emoji.
  Class 5–6   Clear language. Key terms defined inline. Everyday examples.
  Class 7–8   Academic vocabulary. Formulas introduced gently. Cause-and-effect.
  Class 9–10  Full scientific terminology. Show formulas with definitions. Real-world data.
  Class 11–12 Rigorous depth. Derive formulas. Numerical datasets. Discuss edge cases.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL QUALITY GATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

□ Rendering engine chosen matches the subject type from the table in Step 0
□ Intro illustration shows ALL 8–12 scene objects from Q1
□ All canvas fills use createLinearGradient / createRadialGradient (no flat hex fills on major elements)
□ All SVG fills (Engine C) reference a <linearGradient> or <radialGradient> ID
□ Both sliders fire onSlider() on oninput — changes happen while dragging
□ drawScene() / renderCanvasChanges() mutates the canvas visibly per slider value
□ Particle system running with topic-appropriate symbols
□ updateTextOnly() uses domain-accurate vocabulary, not generic labels
□ runSimulation() computes real domain formula, outputs all 4 result parts
□ No [BRACKET] placeholders remain in the output
□ No empty function bodies, no '// TODO', no '// add code here'
□ One complete self-contained HTML file — no external CDN dependencies

NOW GENERATE THE COMPLETE HTML FILE.
Topic: {topic}
Grade: {grade}
Output only raw HTML. Start with <!DOCTYPE html>. End with </html>. Nothing before or after.
"""


def _build_simulation_prompt(
    topic: str,
    subject: str,
    class_no,
    persona,
    summary_text: str
) -> str:

    grade_label = f"Class {class_no}" if class_no else "Middle School"

    persona_desc = ""
    if persona:
        if isinstance(persona, dict):
            themes = persona.get("themes", [])
            persona_desc = (
                f"Character role: {persona.get('character_role', 'Explorer')}, "
                f"Tone: {persona.get('story_tone', 'Curious')}, "
                f"Themes: {', '.join(themes)}"
            )
        else:
            persona_desc = f"Student interest: {persona}"

    grounded_section = f"""=== AUTHORITATIVE EDUCATIONAL INPUTS ===
Topic          : {topic}
Subject Area   : {subject}
Target Grade   : {grade_label}
""" + (f"Student Persona: {persona_desc}\n" if persona_desc else "") + f"""
=== GROUNDED CONTENT ===
{summary_text if summary_text else f"Standard {subject} topic for {grade_label} students."}
=== END GROUNDED CONTENT ===

CONTENT RULES:
1. All factual claims, definitions, and formulas MUST come from Grounded Content above.
2. If Grounded Content is silent on a detail, omit it rather than invent it.
3. EXCEPTION — Visual inference IS required: SVG/Canvas scene composition, gradient
   colors, bezier coordinates, particle symbols, and animation design are your
   responsibility as the designer. Infer everything needed to make "{topic}" look
   like "{topic}" — not a generic diagram.

"""

    instructions = f"""=== TASK ===
Populate the Application Shell Template below to produce one complete, self-contained,
browser-ready HTML simulation for the topic and grade above.

=== RENDERING ENGINE SELECTION ===
Step 0 of the template requires you to select the correct rendering engine based on
the subject type. Do this FIRST — it governs the entire canvas implementation.

Subject: {subject}
Topic:   {topic}

Match to the engine table in Step 0 and implement accordingly.
Do NOT default to SVG for science/biology/physics/math topics.
Those topics MUST use Canvas 2D for reliable, cinematic output.

=== VISUAL QUALITY MANDATE ===
FORBIDDEN:
  ✗ Flat solid ctx.fillStyle = '#hex' on any major scene element
  ✗ Plain colored circles/rectangles as the main visual subject
  ✗ Static canvas that ignores slider input
  ✗ Empty functions or placeholder comments
  ✗ Truncated code — any abbreviated section fails the output

REQUIRED:
  ✓ Every canvas fill: createLinearGradient or createRadialGradient
  ✓ Every SVG fill: url(#gradientId) referencing a defined <linearGradient>
  ✓ drawScene(v1,v2) redraws full canvas on every oninput
  ✓ Particle system with topic-appropriate symbols, running continuously
  ✓ updateTextOnly() uses domain vocabulary matching {grade_label}
  ✓ runSimulation() computes real formula, 4-part structured output
  ✓ Intro illustration shows all 8–12 topic scene objects

=== STRUCTURAL RULES ===
  • Keep every CSS class, HTML ID, and function signature from the Shell exactly.
  • Fill only the marked [BRACKET] slots.
  • Do not add external CDN links or dependencies.

=== APPLICATION SHELL ===
"""

    output_command = f"""
=== SELF-CHECK BEFORE OUTPUT ===
□ Engine chosen matches subject "{subject}" in the Step 0 table
□ Intro illustration renders all topic scene objects
□ All gradient fills implemented (no flat hex on major elements)
□ Both sliders reactive on oninput
□ Particle system active with correct topic symbols
□ runSimulation() uses real domain formula
□ All 4 output parts present in feedback
□ No [BRACKET] placeholders remain
□ No empty or stub function bodies
□ File ends with </html>

=== OUTPUT ===
Return ONLY raw HTML. Start with <!DOCTYPE html>. End with </html>.
No markdown fences. No explanation. No text before or after.
Do NOT stop early — output the complete file.
"""

    return grounded_section + instructions + _SIMULATION_TEMPLATE_LATEST + output_command

def _build_simulation_prompt_v2(topic: str, subject: str, class_no, persona, summary_text: str) -> str:
    grade_label = f"Class {class_no}" if class_no else "Middle School"

    persona_desc = ""
    if persona:
        if isinstance(persona, dict):
            themes = persona.get("themes", [])
            persona_desc = (
                f"Character role: {persona.get('character_role', 'Explorer')}, "
                f"Tone: {persona.get('story_tone', 'Curious')}, "
                f"Themes: {', '.join(themes)}"
            )
        else:
            persona_desc = f"Student interest: {persona}"

    grounded_section = (
        "=== EDUCATIONAL INPUTS ===\n"
        f"Topic: {topic}\n"
        f"Subject: {subject}\n"
        f"Target Grade Level: {grade_label}\n"
        + (f"Student Learning Persona: {persona_desc}\n" if persona_desc else "")
        + "\n=== GROUNDED CONTENT (authoritative source — use ONLY this for explanations, do NOT invent facts) ===\n"
        + (summary_text if summary_text else f"This is a standard {subject} topic for {grade_label} students.")
        + "\n=== END OF GROUNDED CONTENT ===\n\n"
    )

    instructions = (
        "You are a specialized Educational Content Pipeline Engine. Your sole task is to generate a "
        "premium, single-file interactive simulation component by populating the pre-stabilized Application Shell below.\n\n"
        "--- STRUCTURAL COMPLIANCE REQUIREMENTS ---\n"
        "1. VIEWPORT CANVAS RENDERING: Inside the `#viewport-canvas` element you must generate the complete SVG "
        "structure or HTML component layout needed to represent the active visual simulation. "
        "No plain text emojis are allowed as core actors.\n"
        "2. JAVASCRIPT LOGIC IMPLEMENTATION: You must write complete, functional code for every placeholder block:\n"
        "   - `updateTextOnly()`: Read the range values (#input-param1, etc.) and immediately update text innerText labels.\n"
        "   - `renderCanvasChanges()`: Manipulate styles, dimensions, transforms, positions, or visibility transitions "
        "of the graphics inside #viewport-canvas based on input variables.\n"
        "   - `runSimulation()`: Execute step-by-step state changes, dynamic logs, and calculation metrics matching the topic.\n"
        "   Leaving any of these functions empty or using mock comments is STRICTLY FORBIDDEN.\n\n"
        "ADDITIONAL RULES:\n"
        "- Ground ALL explanatory text in the GROUNDED CONTENT provided above. Do not invent facts outside that content.\n"
        "- Preserve every CSS class and layout rule exactly as written in the shell.\n\n"
        "--- STRICT KV-CACHEABLE BOILERPLATE TEMPLATE TO POPULATE ---\n"
    )

    output_command = (
        "\n\n=== OUTPUT EXECUTION COMMAND ===\n"
        "Inject data variables and visual assets from the EDUCATIONAL INPUTS and GROUNDED CONTENT into the template slots. "
        "Keep the base CSS structure exactly constant. "
        "Completely replace [INJECT LOGIC] and [INJECT THE FULL VIEWPORT MARKUP GRAPHICS HERE] with actual "
        "functional content and script execution routines. "
        "Return ONLY the raw complete executable HTML — no markdown code fences, no ```html wrapper, no explanations. "
        "Start your response directly with <!DOCTYPE html>."
    )

    return grounded_section + instructions + _SIMULATION_TEMPLATE + output_command


def _build_simulation_prompt_v3(
    topic: str,
    subject: str,
    class_no,
    persona,
    summary_text: str
) -> str:

    # ── Grade label ────────────────────────────────────────────────────────────
    grade_label = f"Class {class_no}" if class_no else "Middle School"

    # ── Persona descriptor ─────────────────────────────────────────────────────
    persona_desc = ""
    if persona:
        if isinstance(persona, dict):
            themes = persona.get("themes", [])
            persona_desc = (
                f"Character role: {persona.get('character_role', 'Explorer')}, "
                f"Tone: {persona.get('story_tone', 'Curious')}, "
                f"Themes: {', '.join(themes)}"
            )
        else:
            persona_desc = f"Student interest: {persona}"

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — GROUNDED CONTENT
    # PURPOSE: Give Claude authoritative facts so it never invents content.
    # CHANGE FROM V2: Added explicit hierarchy instruction — V2 had no rule
    # about what to do when grounded content conflicts with Claude's training.
    # Also added the "scene inference" instruction so Claude knows it IS allowed
    # to invent visual detail (SVG paths, gradients, scene composition) even
    # while being restricted from inventing factual claims.
    # ══════════════════════════════════════════════════════════════════════════
    grounded_section = f"""=== AUTHORITATIVE EDUCATIONAL INPUTS ===
Topic          : {topic}
Subject Area   : {subject}
Target Grade   : {grade_label}
""" + (f"Student Persona: {persona_desc}\n" if persona_desc else "") + f"""
=== GROUNDED CONTENT (single source of truth for all factual claims) ===
{summary_text if summary_text else f"This is a standard {subject} topic for {grade_label} students."}
=== END GROUNDED CONTENT ===

CONTENT HIERARCHY RULES:
1. Every factual claim, definition, formula, and explanation in the HTML output
   MUST be derived from the Grounded Content above — never from Claude's general
   training data alone.
2. If Grounded Content is silent on a detail, omit that claim rather than invent it.
3. EXCEPTION — Visual/Creative inference IS permitted and required:
   SVG scene composition, gradient color choices, particle symbols, bezier path
   coordinates, animation timing, and layout decisions are visual design choices,
   not factual claims. Claude must infer and fully implement these from the topic
   name and subject area even if Grounded Content does not describe them.
   A topic about "{topic}" should produce a scene that looks like "{topic}" —
   not a generic diagram.

"""

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — INSTRUCTIONS
    # PURPOSE: Tell Claude its role, what to produce, and the non-negotiable rules.
    # CHANGE FROM V2: V2 instructions were vague ("write complete functional code").
    # V3 instructions are specific about WHAT cinematic quality means, explicitly
    # forbid the lazy patterns Claude defaults to, and reference the V3 template
    # sections by name so Claude knows the template is the authority on structure.
    # The "visual inference" permission is repeated here to prevent Claude from
    # using vague Grounded Content as an excuse to produce a bare-bones canvas.
    # ══════════════════════════════════════════════════════════════════════════
    instructions = f"""=== PIPELINE ROLE & TASK ===
You are a Principal Frontend Engineer and Interactive Education Architect.
Your task: populate the Application Shell Template below to produce ONE complete,
self-contained, browser-ready HTML simulation for the topic and grade above.

=== CINEMATIC VISUAL QUALITY MANDATE ===
The single most common failure mode is producing a canvas with plain geometric
shapes (circles, rectangles) instead of a real illustrated scene. This is
FORBIDDEN. The canvas must look like a professional educational illustration.

HARD FORBIDDEN — output will be rejected if any of these appear:
  ✗ A solid-color circle or rectangle as the main visual subject
  ✗ Any SVG fill without a linearGradient or radialGradient
  ✗ A static #viewport-canvas that does not change when sliders are dragged
  ✗ Empty function bodies or functions containing only comments
  ✗ Placeholder text: "// add code here", "// TODO", "// draw scene here"
  ✗ Abbreviated JS blocks with "// ... rest of logic"
  ✗ Any factual claim not present in the Grounded Content above

REQUIRED — every output must contain all of these:
  ✓ Intro SVG illustration: viewBox 680×280, ≥10 distinct elements,
    ALL fills use gradients, light sources use feGaussianBlur glow filter,
    SVG <text> labels identify key scene components
  ✓ Lab canvas SVG: viewBox 360×380, dark background (#071a2e),
    scene layered as: background → environment → main subject → detail → particles
    ALL elements have IDs for JavaScript mutation
  ✓ Particle emitter: topic-appropriate symbols, JS setInterval spawner,
    CSS @keyframes simFloat animation, rate controlled by slider values
  ✓ updateTextOnly(): fires on oninput, uses domain-accurate vocabulary for labels
  ✓ renderCanvasChanges(): fires on oninput, mutates ≥5 SVG attributes per slider,
    uses interpolateColor() for smooth background atmosphere transitions
  ✓ runSimulation(): computes real domain formula, outputs 4-part structured result
    (Conditions / Formula with substituted values / Computed output / Interpretation)
  ✓ Grade language calibration: all text (labels, cards, feedback) matches {grade_label}

=== STRUCTURAL COMPLIANCE ===
  • Preserve every CSS class name and HTML ID exactly as written in the Shell.
  • The Shell's layout, tab system, and CSS rules must not be modified.
  • Only fill the marked [INJECT ...] slots — do not restructure the Shell.
  • The JavaScript function signatures (updateTextOnly, renderCanvasChanges,
    runSimulation, openTab, interpolateColor, spawnParticleStream) must be kept
    exactly — only their bodies are written by you.

=== VISUAL SCENE INFERENCE PERMISSION ===
The Grounded Content above describes facts about {topic}. It does NOT need to
describe the visual scene — that is YOUR job as the designer. You must infer:
  • What physical or conceptual objects exist in a "{topic}" scene
  • What SVG bezier paths, gradients, and glow effects make them look realistic
  • What particles logically float, drift, or pulse in this topic's context
  • What two variables a student would most want to control in this simulation
Do NOT use vague Grounded Content as justification for a sparse canvas.
Sparse canvas = silent failure of this pipeline.

=== APPLICATION SHELL TEMPLATE ===
"""

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — OUTPUT COMMAND
    # PURPOSE: Final instruction that appears after the template, telling Claude
    # exactly what to emit and how to format it.
    # CHANGE FROM V2: V2's output command was 2 sentences and said "replace
    # [INJECT LOGIC]". V3's command is explicit about WHAT constitutes complete
    # implementation, repeats the no-truncation rule, and adds the self-check
    # list that Claude reads immediately before generating output.
    # Critical addition: "Do not stop early" — V2 had no such instruction and
    # Claude frequently truncated long simulations.
    # ══════════════════════════════════════════════════════════════════════════
    output_command = f"""
=== FINAL SELF-CHECK (verify mentally before writing the first character) ===
Before outputting, confirm:
  □ Intro SVG has ≥10 elements, all with gradient fills, glow filters on light sources
  □ Lab SVG canvas is a real illustrated scene of "{topic}" — not shapes with labels
  □ Every SVG <rect>, <circle>, <ellipse>, <path> fill references a gradient ID
  □ Both sliders call renderCanvasChanges() on oninput (while dragging, not just release)
  □ renderCanvasChanges() mutates ≥5 distinct SVG attributes per slider
  □ Particle system runs continuously with topic-appropriate symbols
  □ runSimulation() uses the real domain formula and all 4 output parts are present
  □ All text content is grounded in the Grounded Content provided
  □ No [INJECT ...] bracket placeholders remain in the final output
  □ No function body is empty or contains only a comment
  □ Output is one complete HTML file — no external CDN links, no markdown fences

=== OUTPUT EXECUTION ===
Populate all [INJECT ...] slots in the Application Shell above using the
Educational Inputs and Grounded Content. Do not modify the Shell's CSS or
structural HTML outside the designated slots.

CRITICAL OUTPUT FORMAT RULES:
  • Return ONLY the raw HTML — start your response with <!DOCTYPE html>
  • Do NOT wrap in ```html or any markdown code fences
  • Do NOT add any explanation, commentary, or text before or after the HTML
  • Do NOT truncate or abbreviate any section — output the full file completely
  • Do NOT stop early — the file is only complete when </html> is the last line
"""

    return grounded_section + instructions + _SIMULATION_TEMPLATE_V3 + output_command

@router.get("/simulation")
async def get_simulation_cache(daily_id: str):
    """Return the most recent cached simulation for a class, or 404 if none exists."""
    if not ObjectId.is_valid(daily_id):
        raise HTTPException(status_code=400, detail="Invalid daily_id format")
    db = await get_db()
    existing = await db.simulations.find_one({"daily_id": daily_id}, sort=[("created_at", -1)])
    if not existing:
        raise HTTPException(status_code=404, detail="No simulation found")
    return {"html": existing["html"]}


@router.post("/simulation")
async def simulation_for_student(daily_id: str, student_id: str, force: bool = False, tenant: str = Depends(get_tenant)):
    logger = logging.getLogger(__name__)
    logger.info(f"[SIMULATION] daily_id={daily_id} student_id={student_id} force={force}")

    if not ObjectId.is_valid(daily_id):
        raise HTTPException(status_code=400, detail="Invalid daily_id format")

    db = await get_db()

    d = await db.classes_daily.find_one({"_id": ObjectId(daily_id), "tenant": tenant})
    if not d:
        raise HTTPException(status_code=404, detail="Daily class not found")

    # Return cached simulation unless force-regeneration is requested.
    # We never delete old records — sort by created_at desc always picks the newest.
    if not force:
        existing = await db.simulations.find_one({"daily_id": daily_id}, sort=[("created_at", -1)])
        if existing:
            logger.info("[SIMULATION] Returning cached simulation")
            return {"html": existing["html"]}

    s = await db.students.find_one({"student_id": student_id, "tenant": tenant})
    persona = s.get("story_persona") if s else None

    topic = ", ".join(d.get("topics", [])) or d.get("topic", "the topic")
    subject = d.get("subject", "")
    class_no = d.get("class_no")
    summary_text = _extract_summary_text(d.get("summary_blocks"), d.get("summary"))

    # ── Build a compact user message with the educational context ──────────────
    # System prompt = _SIMULATION_TEMPLATE_V2 verbatim (the prompt the user verified
    # produces high-quality SVG simulations when sent to Claude Sonnet 4.6).
    grade_label = f"Class {class_no}" if class_no else "Middle School"
    persona_desc = ""
    if persona:
        if isinstance(persona, dict):
            themes = persona.get("themes", [])
            persona_desc = (
                f"Character role: {persona.get('character_role', 'Explorer')}, "
                f"Tone: {persona.get('story_tone', 'Curious')}, "
                f"Themes: {', '.join(themes)}"
            )
        else:
            persona_desc = f"Student interest: {persona}"

    user_parts = [
        f"Topic: {topic}",
        f"Subject: {subject}",
        f"Target Grade Level: {grade_label}",
    ]
    if persona_desc:
        user_parts.append(f"Student Learning Persona: {persona_desc}")
    if summary_text:
        user_parts.append(
            "\nGrounded Content (authoritative source — use ONLY this for explanations, do not invent facts):\n"
            + summary_text
        )
    user_parts.append("\nGenerate the complete interactive simulation HTML now. Output ONLY raw HTML starting with <!DOCTYPE html>. No markdown fences, no commentary.")
    user_message = "\n".join(user_parts)

    html = None

    # ── Google Gemini (primary): high-quality HTML/SVG simulation generation ───
    gemini = get_gemini_client()
    if gemini is not None:
        try:
            from google.genai import types as genai_types
            g_resp = gemini.models.generate_content(
                model=settings.GEMINI_SIMULATION_MODEL,
                contents=user_message,
                config=genai_types.GenerateContentConfig(
                    temperature=0.65,
                    max_output_tokens=12000,
                    system_instruction=_SIMULATION_TEMPLATE_V2,
                ),
            )
            html = (g_resp.text or "").strip() or None
        except Exception as e:
            logger.warning(f"[SIMULATION] Gemini call failed, falling back to Anthropic/Azure: {e}")

    # ── Anthropic Claude (fallback): richer SVG generation than gpt-4o-mini ────
    if html is None and settings.ANTHROPIC_API_KEY:
        try:
            anth_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            anth_resp = anth_client.messages.create(
                model=settings.ANTHROPIC_SIMULATION_MODEL,
                max_tokens=12000,
                temperature=0.65,
                system=_SIMULATION_TEMPLATE_V2,
                messages=[{"role": "user", "content": user_message}],
            )
            html = anth_resp.content[0].text.strip()
        except Exception as e:
            logger.warning(f"[SIMULATION] Anthropic call failed, falling back to Azure: {e}")

    # ── Azure OpenAI (fallback): kept intact so existing setup keeps working ───
    if html is None:
        prompt = _build_simulation_prompt(topic, subject, class_no, persona, summary_text)
        client = get_client()
        try:
            resp = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a specialized Educational Content Pipeline Engine. "
                            "Return ONLY raw HTML starting with <!DOCTYPE html>. "
                            "No markdown, no code fences, no commentary."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.65,
                max_tokens=12000,
            )
        except Exception as e:
            logger.exception(f"[SIMULATION] LLM call failed: {e}")
            raise HTTPException(status_code=502, detail=f"Simulation generation failed: {str(e)}")

        html = resp.choices[0].message.content.strip()

    # Strip markdown code fences if LLM wraps despite instructions
    if html.startswith("```"):
        lines = html.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        html = "\n".join(lines)

    from datetime import datetime
    await db.simulations.insert_one({
        "daily_id": daily_id,
        "student_id": student_id,
        "html": html,
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
    logger.info("[SIMULATION] Stored and returning new simulation")
    return {"html": html}
