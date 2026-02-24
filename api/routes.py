"""API routes for Concierge."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel

from . import memory
from .sonnet import chat
from .ingest import ingest_extractions, ingest_stats

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

class IngestRequest(BaseModel):
    days: int = 14
    factory: Optional[str] = None
    status: Optional[str] = None


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
async def get_memories(limit: int = 50, offset: int = 0, tag: Optional[str] = None):
    """Return memories, most recent first. Optionally filter by tag."""
    all_memories = memory.load_memories()
    if tag:
        all_memories = [m for m in all_memories if tag in m.get("tags", [])]
    total = len(all_memories)
    reversed_memories = list(reversed(all_memories))
    page = reversed_memories[offset:offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "tag": tag,
        "memories": page,
    }


@router.post("/ingest")
async def ingest_endpoint(req: IngestRequest):
    """Ingest extraction data from monce_db into Concierge memory.

    Pulls extractions from the last N days and stores them as tagged memories.
    Deduplicates by extraction ID — safe to call repeatedly.
    Auto-computes digests after ingestion.
    """
    try:
        result = ingest_extractions(
            days=req.days,
            factory=req.factory,
            status=req.status,
        )
        # Auto-compute digests after ingestion
        digests = memory.compute_digests()
        result["digests_computed"] = len(digests)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/stats")
async def ingest_stats_endpoint(factory: Optional[str] = None):
    """Pull aggregate stats from monce_db and store as memory."""
    try:
        stats = ingest_stats(factory=factory)
        return stats
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/digest")
async def compute_digest():
    """Recompute aggregate digests from all extraction memories."""
    digests = memory.compute_digests()
    return {"digests": len(digests), "entries": digests}


@router.get("/digest")
async def get_digests():
    """Return current digests."""
    digests = memory.load_digests()
    return {"digests": len(digests), "entries": digests}


@router.get("/search")
async def search_endpoint(q: str, limit: int = 30):
    """Search memories by keyword."""
    results = memory.search_memories(q, limit=limit)
    return {"query": q, "results": len(results), "memories": results}
