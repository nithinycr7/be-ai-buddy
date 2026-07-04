from __future__ import annotations
from typing import AsyncGenerator
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..core.security import require_role
from ..services.chat_service import ChatService, ChatRequest, ChatResponse, get_chat_service

router = APIRouter(prefix="/ai", tags=["ai.chat"], dependencies=[Depends(require_role("student", "teacher", "admin", "parent"))])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, service: ChatService = Depends(get_chat_service)):
    """One-shot grounded AI-tutor completion."""
    return ChatResponse(reply=await service.complete(req))


@router.post("/chat/ ")
async def chat_stream(req: ChatRequest, service: ChatService = Depends(get_chat_service)):
    """Streaming (SSE) AI-tutor completion."""
    def _sse(data: str) -> bytes:
        return f"data: {data}\n\n".encode("utf-8")

    async def gen() -> AsyncGenerator[bytes, None]:
        try:
            async for delta in service.stream_deltas(req):
                yield _sse(delta)
            yield _sse("[DONE]")
        except Exception as e:
            yield _sse(f"[ERROR] {e}")

    return StreamingResponse(gen(), media_type="text/event-stream")
