"""API routes for Concierge."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel

from . import memory
from .sonnet import chat

logger = logging.getLogger(__name__)

router = APIRouter()

STATIC_DIR = Path(__file__).parent / "static"


# --- Request/Response models ---

class ChatRequest(BaseModel):
    message: str

class RememberRequest(BaseModel):
    text: str
    source: Optional[str] = None
    tags: Optional[list] = None

class ForgetRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    reply: str
    latency_ms: int = 0

class RememberResponse(BaseModel):
    remembered: bool
    entry: dict

class ForgetResponse(BaseModel):
    forgotten: int
    query: str


# --- Endpoints ---

@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "concierge",
        "memories": memory.memory_count(),
        "conversations": memory.conversation_count(),
    }


@router.get("/ui", include_in_schema=False)
async def chat_ui():
    """Serve the chat interface."""
    ui_path = STATIC_DIR / "ui.html"
    if ui_path.exists():
        return FileResponse(str(ui_path))
    return {"error": "UI not found"}


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Chat with Concierge."""
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message")

    result = chat(message)

    # Store conversation
    memory.save_conversation(message, result["reply"])

    return ChatResponse(reply=result["reply"], latency_ms=result["latency_ms"])


@router.post("/remember", response_model=RememberResponse)
async def remember(req: RememberRequest):
    """Store a memory."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    entry = memory.add_memory(text, source=req.source, tags=req.tags)
    return RememberResponse(remembered=True, entry=entry)


@router.post("/forget", response_model=ForgetResponse)
async def forget_memories(req: ForgetRequest):
    """Forget memories matching query."""
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    forgotten = memory.forget(query)
    return ForgetResponse(forgotten=forgotten, query=query)


@router.get("/memories")
async def get_memories(limit: int = 50, offset: int = 0):
    """Return memories, most recent first."""
    all_memories = memory.load_memories()
    total = len(all_memories)
    reversed_memories = list(reversed(all_memories))
    page = reversed_memories[offset:offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "memories": page,
    }
