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
from . import snake
from . import data_kpi

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

class ArticleSynonymRequest(BaseModel):
    text: str
    num_article: str
    factory_id: str
    trigger_rebuild: bool = False

class ClientSynonymRequest(BaseModel):
    text: str
    numero_client: str
    factory_id: str
    trigger_rebuild: bool = False

class BatchSynonymRequest(BaseModel):
    synonyms: list
    synonym_type: str = "article"


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


# --- Snake synonym endpoints ---

@router.post("/snake/synonym")
async def add_article_synonym(req: ArticleSynonymRequest):
    """Push an article synonym to snake.aws.monce.ai."""
    try:
        result = snake.add_article_synonym(
            text=req.text,
            num_article=req.num_article,
            factory_id=req.factory_id,
            trigger_rebuild=req.trigger_rebuild,
        )
        memory.add_memory(
            f"Added article synonym: '{req.text}' → article {req.num_article} [{req.factory_id}]",
            source="snake",
            tags=["synonym", "article", req.factory_id],
        )
        return {"status": "ok", "result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/snake/synonym_client")
async def add_client_synonym(req: ClientSynonymRequest):
    """Push a client synonym to snake.aws.monce.ai."""
    try:
        result = snake.add_client_synonym(
            text=req.text,
            numero_client=req.numero_client,
            factory_id=req.factory_id,
            trigger_rebuild=req.trigger_rebuild,
        )
        memory.add_memory(
            f"Added client synonym: '{req.text}' → client {req.numero_client} [{req.factory_id}]",
            source="snake",
            tags=["synonym", "client", req.factory_id],
        )
        return {"status": "ok", "result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/snake/synonyms_batch")
async def add_synonyms_batch(req: BatchSynonymRequest):
    """Push multiple synonyms to snake.aws.monce.ai in batch, then rebuild."""
    try:
        result = snake.add_synonyms_batch(
            synonyms=req.synonyms,
            synonym_type=req.synonym_type,
        )
        if result["added"] > 0:
            memory.add_memory(
                f"Batch added {result['added']} {req.synonym_type} synonyms "
                f"to factories: {', '.join(result['factories_affected'])}",
                source="snake",
                tags=["synonym", "batch", req.synonym_type],
            )
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/snake/rebuild")
async def rebuild_snake():
    """Trigger a full rebuild of all Snake factory tenants."""
    try:
        result = snake.rebuild_all()
        return {"status": "ok", "result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Intelligence endpoints ---

@router.get("/intelligence")
async def intelligence():
    """Return business intelligence signals from current digests.

    Filters digests to only [INTELLIGENCE] entries — the actionable signals:
    new clients, volume anomalies, product shifts, low-confidence hotspots.
    """
    digests = memory.load_digests()
    signals = [d for d in digests if d.get("type", "").startswith(("new_", "volume_", "product_", "low_", "factory_"))]
    return {
        "signals": len(signals),
        "entries": signals,
        "tip": "Run POST /ingest then POST /digest to refresh intelligence from latest data",
    }


@router.get("/intelligence/clients")
async def intelligence_clients():
    """Client-focused intelligence: new clients, volume anomalies, diversification."""
    digests = memory.load_digests()
    client_signals = [
        d for d in digests
        if d.get("type") in ("new_clients", "volume_spikes", "volume_drops", "product_diversification")
    ]
    return {"signals": len(client_signals), "entries": client_signals}


@router.get("/intelligence/quality")
async def intelligence_quality():
    """Matching quality intelligence: low-confidence hotspots needing synonym work."""
    digests = memory.load_digests()
    quality_signals = [
        d for d in digests
        if d.get("type") in ("low_confidence_hotspots", "matching_quality")
    ]
    return {"signals": len(quality_signals), "entries": quality_signals}


@router.get("/intelligence/market")
async def intelligence_market():
    """Market intelligence: new glass types, factory shifts, product trends."""
    digests = memory.load_digests()
    market_signals = [
        d for d in digests
        if d.get("type") in ("new_glass_types", "factory_shifts", "glass_types")
    ]
    return {"signals": len(market_signals), "entries": market_signals}


# --- Data KPI endpoints (data.aws.monce.ai) ---

@router.get("/kpi")
async def kpi_all(days: int = 1, factory_id: Optional[int] = None):
    """Pull all KPIs from data.aws.monce.ai and store as memory.

    Returns accuracy, volume, synonym suggestions, and pending reviews.
    Default 1 day to keep queries fast. Use days=7 for weekly view.
    """
    try:
        kpis = data_kpi.fetch_all_kpis(days=days, factory_id=factory_id)
        summary = data_kpi.summarize_kpis_for_memory(kpis)
        memory.add_memory(
            f"[KPI snapshot {days}d] {summary}",
            source="data.aws.monce.ai",
            tags=["kpi", "snapshot"],
        )
        return kpis
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/kpi/accuracy")
async def kpi_accuracy(days: int = 1, factory_id: Optional[int] = None):
    """Extraction accuracy KPI from data.aws.monce.ai."""
    try:
        return data_kpi.fetch_accuracy(days=days, factory_id=factory_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/kpi/volume")
async def kpi_volume(days: int = 1, factory_id: Optional[int] = None):
    """Extraction volume KPI from data.aws.monce.ai."""
    try:
        return data_kpi.fetch_volume(days=days, factory_id=factory_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/kpi/suggestions")
async def kpi_suggestions(days: int = 1, factory_id: Optional[int] = None, min_confidence: float = 0.5):
    """Synonym suggestions — Snake SAT matches that need synonym entries."""
    try:
        return data_kpi.fetch_suggestions(days=days, factory_id=factory_id, min_confidence=min_confidence)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/kpi/comments")
async def kpi_comments(days: int = 1):
    """User feedback/comment statistics from data.aws.monce.ai."""
    try:
        return data_kpi.fetch_comments_stats(days=days)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/kpi/standup")
async def kpi_standup(hours: int = 24):
    """Daily standup report from data.aws.monce.ai."""
    try:
        return data_kpi.fetch_standup(hours=hours)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
