from typing import List, Literal, Optional, AsyncGenerator
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from ..core.config import settings
from ..services.ai import get_client  # you already have this in ai.py

router = APIRouter(prefix=f"/ai", tags=["ai.chat"])

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
    temperature: float = 0.2
    max_tokens: int = 600

class ChatResponse(BaseModel):
    reply: str

SYSTEM_PROMPT_BASE = (
    "You are AI Buddy, a kind, concise tutor for school students. "
    "Answer clearly in short paragraphs or bullets. "
    "Prefer concrete steps and examples. If the user asks about today's lecture,"
    "Answer based on the persona and restrict to 2-3 lines"
    "use the provided lecture summary if available."
    "Do not respond to any questions other than academic queries related to school subjects."
    "If the question is not related to school subjects, politely inform the user that you can only assist with academic queries."
)

def _build_messages(req: ChatRequest) -> List[dict]:
    msgs: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT_BASE}]
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
