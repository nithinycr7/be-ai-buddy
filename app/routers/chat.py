from __future__ import annotations
from typing import List, Literal, Optional, AsyncGenerator
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from ..core.config import settings
from ..core.security import require_role
from ..services.ai import get_client  # you already have this in ai.py

router = APIRouter(prefix=f"/ai", tags=["ai.chat"], dependencies=[Depends(require_role("student", "teacher", "admin", "parent"))])

# ----- Schemas -----
Role = Literal["system", "user", "assistant"]

class ChatMessage(BaseModel):
    role: Role
    content: str = Field(..., min_length=1)

class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_items=1)
    # Optional lecture context to ground the answer
    summary: Optional[str] = None
    persona: Optional[str] = None
    subject: Optional[str] = None
    topic: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 1000

class ChatResponse(BaseModel):
    reply: str

SYSTEM_PROMPT_BASE = (
    "You are AI Buddy, a warm and knowledgeable tutor for students in grades 3-9. "
    "Your goal is to explain concepts clearly and thoroughly so the student truly understands.\n\n"
    "RESPONSE STYLE:\n"
    "- Give clear, well-structured explanations using simple language\n"
    "- Use bullet points, numbered steps, or short paragraphs for clarity\n"
    "- Include a real-life example or analogy when helpful\n"
    "- Use bold for key terms\n"
    "- After explaining, ask ONE follow-up question to check understanding\n"
    "- Aim for 4-8 sentences — not too short, not a wall of text\n\n"
    "RULES:\n"
    "- If a lecture summary is provided, base your answer on it (this is what the teacher taught)\n"
    "- Use age-appropriate language (simpler for younger students)\n"
    "- Be encouraging and supportive\n"
    "- If the student asks a non-academic question, gently steer them back to learning"
)

def _build_messages(req: ChatRequest) -> List[dict]:
    msgs: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT_BASE}]

    # Topic context — tells the LLM what the student is currently studying
    if req.subject and req.topic:
        msgs.append({
            "role": "system",
            "content": (
                f"The student is currently studying {req.subject} — topic: {req.topic}. "
                f"If they ask about this topic, answer using the lecture summary below. "
                f"If they ask about a DIFFERENT subject or topic, answer their question helpfully, "
                f"then gently remind them: 'By the way, you were studying {req.topic} in {req.subject} — "
                f"want to continue with that?' Do NOT block or refuse off-topic academic questions."
            )
        })

    if req.summary:
        msgs.append({
            "role": "system",
            "content": f"Lecture summary/context:\n{req.summary}"
        })
    if req.persona:
        msgs.append({
            "role": "system",
            "content": f"Student persona/hobbies: {req.persona}. Adapt tone and examples accordingly."
        })
    # user/assistant history from the UI
    msgs.extend({"role": m.role, "content": m.content} for m in req.messages)
    return msgs

# ----- One-shot completion (fits current UI) -----
@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=_build_messages(req),
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        reply = resp.choices[0].message.content or ""
        return ChatResponse(reply=reply.strip())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {e}")

# ----- Streaming (SSE) – optional upgrade -----
@router.post("/chat/ ")
async def chat_stream(req: ChatRequest):
    client = get_client()

    def sse_format(data: str) -> str:
        return f"data: {data}\n\n"

    async def gen() -> AsyncGenerator[bytes, None]:
        try:
            stream = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=_build_messages(req),
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = getattr(chunk.choices[0].delta, "content", None)
                if delta:
                    yield sse_format(delta).encode("utf-8")
            # end of stream marker (optional)
            yield sse_format("[DONE]").encode("utf-8")
        except Exception as e:
            yield sse_format(f"[ERROR] {e}").encode("utf-8")

    return StreamingResponse(gen(), media_type="text/event-stream")
