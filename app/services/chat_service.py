"""
AI-tutor chat business logic (no data layer — a grounded LLM proxy).
router → ChatService → LLM client.
"""
from __future__ import annotations

from typing import AsyncGenerator, List, Literal, Optional

from fastapi import Depends
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.exceptions import AppError
from ..services.ai import get_client
from ..prompts.chat import TUTOR_SYSTEM_PROMPT

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: Role
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_items=1)
    summary: Optional[str] = None
    persona: Optional[str] = None
    subject: Optional[str] = None
    topic: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 1000


class ChatResponse(BaseModel):
    reply: str



def _build_messages(req: ChatRequest) -> List[dict]:
    msgs: List[dict] = [{"role": "system", "content": TUTOR_SYSTEM_PROMPT}]
    if req.subject and req.topic:
        msgs.append({"role": "system", "content": (
            f"The student is currently studying {req.subject} — topic: {req.topic}. "
            f"If they ask about this topic, answer using the lecture summary below. "
            f"If they ask about a DIFFERENT subject or topic, answer their question helpfully, "
            f"then gently remind them: 'By the way, you were studying {req.topic} in {req.subject} — "
            f"want to continue with that?' Do NOT block or refuse off-topic academic questions.")})
    if req.summary:
        msgs.append({"role": "system", "content": f"Lecture summary/context:\n{req.summary}"})
    if req.persona:
        msgs.append({"role": "system",
                     "content": f"Student persona/hobbies: {req.persona}. Adapt tone and examples accordingly."})
    msgs.extend({"role": m.role, "content": m.content} for m in req.messages)
    return msgs


class ChatService:
    async def complete(self, req: ChatRequest) -> str:
        try:
            client = get_client()
            resp = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=_build_messages(req),
                temperature=req.temperature, max_tokens=req.max_tokens)
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            raise AppError(f"Chat error: {e}")

    async def stream_deltas(self, req: ChatRequest) -> AsyncGenerator[str, None]:
        """Yield raw text deltas; the router formats them as SSE."""
        client = get_client()
        stream = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=_build_messages(req),
            temperature=req.temperature, max_tokens=req.max_tokens, stream=True)
        for chunk in stream:
            delta = getattr(chunk.choices[0].delta, "content", None)
            if delta:
                yield delta


def get_chat_service() -> ChatService:
    return ChatService()
