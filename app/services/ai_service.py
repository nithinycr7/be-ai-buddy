"""
AI business logic: text-to-speech + interactive simulation generation/caching.
router → AiService → repositories (+ LLM clients + pure prompt module).

The service returns plain data (TTS audio bytes, simulation dicts) and raises
domain exceptions; the router wraps TTS bytes in a StreamingResponse.
"""
from __future__ import annotations

import logging
from datetime import datetime

import anthropic
from bson import ObjectId
from fastapi import Depends
from pydantic import BaseModel

from ..core.config import settings
from ..core.exceptions import AppError, BadRequestError, NotFoundError
from ..db.repositories import (
    DailyClassRepository, get_daily_repo,
    SimulationRepository, get_simulation_repo,
    StudentRepository, get_student_repo,
)
from ..services.ai import get_client, get_gemini_client
from ..prompts.simulation import (
    _SIMULATION_TEMPLATE_V2, _build_simulation_prompt, _extract_summary_text,
)
from ..prompts.tts import SSML_TEMPLATE

logger = logging.getLogger(__name__)


class TTSRequest(BaseModel):
    text: str
    voice: str = "en-IN-NeerjaNeural"
    # Azure Neural voice options (Indian English, kid-friendly):
    #   en-IN-NeerjaNeural / en-IN-PrabhatNeural / en-US-JennyNeural / en-US-GuyNeural


def _valid_daily_or_400(daily_id: str) -> None:
    if not ObjectId.is_valid(daily_id):
        raise BadRequestError("Invalid daily_id format")


class AiService:
    def __init__(self, sims: SimulationRepository, daily: DailyClassRepository,
                 students: StudentRepository):
        self.sims = sims
        self.daily = daily
        self.students = students

    # ── TTS ────────────────────────────────────────────────────────────────────
    async def synthesize_speech(self, req: TTSRequest) -> bytes:
        """Return MP3 audio bytes from Azure AI Speech. Router streams them."""
        import html as html_mod
        import httpx

        if not req.text or not req.text.strip():
            raise BadRequestError("text is required")

        if settings.AZURE_SPEECH_TTS_KEY and settings.AZURE_SPEECH_TTS_REGION:
            tts_url = (f"https://{settings.AZURE_SPEECH_TTS_REGION}.tts.speech.microsoft.com"
                       "/cognitiveservices/v1")
            ssml = SSML_TEMPLATE.format(voice=req.voice, text=html_mod.escape(req.text[:5000]))
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        tts_url, content=ssml.encode("utf-8"),
                        headers={
                            "Ocp-Apim-Subscription-Key": settings.AZURE_SPEECH_TTS_KEY,
                            "Content-Type": "application/ssml+xml",
                            "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
                            "User-Agent": "mymedha-lxp",
                        })
                if resp.status_code != 200:
                    logger.error(f"[TTS] Azure Speech error {resp.status_code}: {resp.text[:200]}")
                    raise AppError(f"Azure Speech TTS failed: {resp.status_code}", status_code=502)
                return resp.content
            except AppError:
                raise
            except Exception as e:
                logger.error(f"[TTS] Azure Speech exception: {e}")
                raise AppError(f"TTS failed: {e}", status_code=500)

        raise AppError("TTS not configured: set AZURE_SPEECH_TTS_KEY and AZURE_SPEECH_TTS_REGION",
                       status_code=503)

    # ── simulation ───────────────────────────────────────────────────────────────
    async def get_cached_simulation(self, daily_id: str) -> dict:
        _valid_daily_or_400(daily_id)
        existing = await self.sims.latest_for_daily(daily_id)
        if not existing:
            raise NotFoundError("No simulation found")
        return {"html": existing["html"]}

    async def generate_simulation(self, *, daily_id: str, student_id: str, force: bool) -> dict:
        logger.info(f"[SIMULATION] daily_id={daily_id} student_id={student_id} force={force}")
        _valid_daily_or_400(daily_id)

        d = await self.daily.get(daily_id)  # tenant-scoped
        if not d:
            raise NotFoundError("Daily class not found")

        if not force:
            existing = await self.sims.latest_for_daily(daily_id)
            if existing:
                logger.info("[SIMULATION] Returning cached simulation")
                return {"html": existing["html"]}

        s = await self.students.get(student_id)
        persona = s.get("story_persona") if s else None

        topic = ", ".join(d.get("topics", [])) or d.get("topic", "the topic")
        subject = d.get("subject", "")
        class_no = d.get("class_no")
        summary_text = _extract_summary_text(d.get("summary_blocks"), d.get("summary"))

        grade_label = f"Class {class_no}" if class_no else "Middle School"
        persona_desc = ""
        if persona:
            if isinstance(persona, dict):
                themes = persona.get("themes", [])
                persona_desc = (f"Character role: {persona.get('character_role', 'Explorer')}, "
                                f"Tone: {persona.get('story_tone', 'Curious')}, "
                                f"Themes: {', '.join(themes)}")
            else:
                persona_desc = f"Student interest: {persona}"

        user_parts = [f"Topic: {topic}", f"Subject: {subject}", f"Target Grade Level: {grade_label}"]
        if persona_desc:
            user_parts.append(f"Student Learning Persona: {persona_desc}")
        if summary_text:
            user_parts.append(
                "\nGrounded Content (authoritative source — use ONLY this for explanations, do not invent facts):\n"
                + summary_text)
        user_parts.append("\nGenerate the complete interactive simulation HTML now. Output ONLY raw HTML starting with <!DOCTYPE html>. No markdown fences, no commentary.")
        user_message = "\n".join(user_parts)

        html = None

        # Gemini (primary)
        gemini = get_gemini_client()
        if gemini is not None:
            try:
                from google.genai import types as genai_types
                g_resp = gemini.models.generate_content(
                    model=settings.GEMINI_SIMULATION_MODEL, contents=user_message,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.65, max_output_tokens=12000,
                        system_instruction=_SIMULATION_TEMPLATE_V2))
                html = (g_resp.text or "").strip() or None
            except Exception as e:
                logger.warning(f"[SIMULATION] Gemini call failed, falling back to Anthropic/Azure: {e}")

        # Anthropic (fallback)
        if html is None and settings.ANTHROPIC_API_KEY:
            try:
                anth_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
                anth_resp = anth_client.messages.create(
                    model=settings.ANTHROPIC_SIMULATION_MODEL, max_tokens=12000, temperature=0.65,
                    system=_SIMULATION_TEMPLATE_V2, messages=[{"role": "user", "content": user_message}])
                html = anth_resp.content[0].text.strip()
            except Exception as e:
                logger.warning(f"[SIMULATION] Anthropic call failed, falling back to Azure: {e}")

        # Azure OpenAI (fallback)
        if html is None:
            prompt = _build_simulation_prompt(topic, subject, class_no, persona, summary_text)
            client = get_client()
            try:
                resp = client.chat.completions.create(
                    model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                    messages=[
                        {"role": "system", "content": (
                            "You are a specialized Educational Content Pipeline Engine. "
                            "Return ONLY raw HTML starting with <!DOCTYPE html>. "
                            "No markdown, no code fences, no commentary.")},
                        {"role": "user", "content": prompt}],
                    temperature=0.65, max_tokens=12000)
            except Exception as e:
                logger.exception(f"[SIMULATION] LLM call failed: {e}")
                raise AppError(f"Simulation generation failed: {e}", status_code=502)
            html = resp.choices[0].message.content.strip()

        # Strip markdown fences if the LLM wraps despite instructions
        if html.startswith("```"):
            lines = html.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            html = "\n".join(lines)

        await self.sims.create({
            "daily_id": daily_id, "student_id": student_id, "html": html,
            "created_at": datetime.utcnow().isoformat() + "Z"})
        logger.info("[SIMULATION] Stored and returning new simulation")
        return {"html": html}


def get_ai_service(
    sims: SimulationRepository = Depends(get_simulation_repo),
    daily: DailyClassRepository = Depends(get_daily_repo),
    students: StudentRepository = Depends(get_student_repo),
) -> AiService:
    return AiService(sims, daily, students)
