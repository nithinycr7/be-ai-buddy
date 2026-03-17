from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ..core.security import api_key_guard
from ..db.mongo import get_db
from ..models.schemas import Story, ContentPrefs
from ..services.ai import get_client
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
    client = get_client()

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

    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": "You are an educational story designer for children aged 7-14. Always return valid JSON only, no extra text."},
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
async def story_for_student(daily_id: str, student_id: str):
    logger = logging.getLogger(__name__)
    logger.info(f"[STORY] Starting story generation for daily_id={daily_id}, student_id={student_id}")
    
    try:
        db = await get_db()
        logger.info("[STORY] Database connection established")
        
        if not ObjectId.is_valid(daily_id):
            logger.error(f"[STORY] Invalid daily_id format: {daily_id}")
            raise HTTPException(status_code=400, detail="Invalid daily_id format")
        
        d = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
        logger.info(f"[STORY] Daily class lookup result: {d is not None}")
        if not d:
            logger.error(f"[STORY] Daily class not found for daily_id={daily_id}")
            raise HTTPException(status_code=404, detail="Daily class not found")
        
        s = await db.students.find_one({"student_id": student_id})
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
            "daily_id": daily_id
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
            {"student_id": student_id, "daily_id": daily_id},
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


