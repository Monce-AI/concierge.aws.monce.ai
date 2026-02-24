"""Memory management for Concierge."""

import json
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from .config import config


def _memories_path() -> str:
    return os.path.join(config.data_dir, "memories.json")


def _conversations_path() -> str:
    return os.path.join(config.data_dir, "conversations.json")


def _digests_path() -> str:
    return os.path.join(config.data_dir, "digests.json")


def _manifest_path() -> str:
    return os.path.join(config.data_dir, "MANIFEST.md")


def _ensure_dirs():
    os.makedirs(config.data_dir, exist_ok=True)


def load_memories() -> list:
    path = _memories_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_memories(memories: list):
    _ensure_dirs()
    with open(_memories_path(), "w") as f:
        json.dump(memories, f, indent=2)


def add_memory(text: str, source: Optional[str] = None, tags: Optional[list] = None) -> dict:
    memories = load_memories()
    entry = {"text": text, "timestamp": datetime.now().isoformat()}
    if source:
        entry["source"] = source
    if tags:
        entry["tags"] = tags
    memories.append(entry)
    save_memories(memories)
    return entry


def forget(query: str) -> int:
    memories = load_memories()
    remaining = [m for m in memories if query.lower() not in m["text"].lower()]
    forgotten = len(memories) - len(remaining)
    if forgotten > 0:
        save_memories(remaining)
    return forgotten


def load_conversations() -> list:
    path = _conversations_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_conversation(user_msg: str, assistant_msg: str):
    _ensure_dirs()
    convos = load_conversations()
    convos.append({
        "user": user_msg,
        "assistant": assistant_msg,
        "timestamp": datetime.now().isoformat(),
    })
    if len(convos) > 200:
        convos = convos[-200:]
    with open(_conversations_path(), "w") as f:
        json.dump(convos, f, indent=2)


def load_manifest() -> str:
    path = _manifest_path()
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return "No manifest defined yet."


def load_digests() -> list:
    path = _digests_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_digests(digests: list):
    _ensure_dirs()
    with open(_digests_path(), "w") as f:
        json.dump(digests, f, indent=2)


# -------------------------------------------------------------------------
# Smart retrieval
# -------------------------------------------------------------------------

def search_memories(query: str, limit: int = 50) -> list:
    """Search memories by keyword matching on text and tags."""
    memories = load_memories()
    query_lower = query.lower()
    tokens = query_lower.split()

    scored = []
    for m in memories:
        text = m.get("text", "").lower()
        tags = [t.lower() for t in m.get("tags", [])]
        score = 0
        for token in tokens:
            if token in text:
                score += 1
            if token in tags:
                score += 2  # tag match weights more
        if score > 0:
            scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit]]


def get_memories_by_tag(tag: str, limit: int = 100) -> list:
    """Get memories filtered by tag."""
    memories = load_memories()
    return [m for m in memories if tag in m.get("tags", [])][-limit:]


def get_recent_memories(n: int = 30) -> list:
    return load_memories()[-n:]


def get_recent_conversations(n: int = 10) -> list:
    return load_conversations()[-n:]


def memory_count() -> int:
    return len(load_memories())


def conversation_count() -> int:
    return len(load_conversations())


# -------------------------------------------------------------------------
# Digest computation — pre-aggregated summaries from raw memories
# -------------------------------------------------------------------------

def compute_digests() -> list:
    """Compute aggregate digests from all extraction memories.

    Produces summaries that Sonnet can reason from:
    - Top clients by extraction count (per factory)
    - Factory volume breakdown
    - Status distribution
    - Daily volume trends
    - Glass type frequency
    - Matching quality overview
    """
    memories = load_memories()
    extractions = [m for m in memories if "extraction" in m.get("tags", [])]

    if not extractions:
        return []

    now = datetime.utcnow()
    digests = []

    # Parse extraction data from memory text
    records = []
    for m in extractions:
        text = m.get("text", "")
        tags = m.get("tags", [])
        record = {"text": text, "tags": tags, "timestamp": m.get("timestamp", "")}

        # Parse fields from pipe-delimited text
        for part in text.split("|"):
            part = part.strip()
            if part.startswith("client="):
                record["client"] = part.split("client=")[1].split("(")[0].strip()
            elif part.startswith("[") and part.endswith("]"):
                record["factory"] = part.strip("[]")
            elif "(" in part and part.startswith("["):
                pieces = part.split("]")
                if pieces:
                    record["factory"] = pieces[0].strip("[ ")
            elif part.startswith("status="):
                record["status"] = part.split("=")[1].strip()
            elif "line(s)" in part:
                try:
                    record["lines"] = int(part.split()[0])
                except (ValueError, IndexError):
                    pass
            elif part.startswith("glass:"):
                record["glasses"] = [g.strip() for g in part.replace("glass:", "").split(",")]
            elif part.startswith("conf="):
                try:
                    record["confidence"] = float(part.replace("conf=", "").replace("%", "")) / 100
                except ValueError:
                    pass
            elif part.startswith("created="):
                record["created_date"] = part.split("=")[1].strip()
            elif "row(s) matched" in part:
                try:
                    record["matched_rows"] = int(part.split()[0])
                except (ValueError, IndexError):
                    pass

        # Factory from tags
        if "factory" not in record:
            for t in tags:
                if t not in ("extraction", "verified", "extracted", "rejected", "unknown"):
                    record["factory"] = t
                    break

        records.append(record)

    total = len(records)

    # --- 1. Overall summary ---
    status_counts = Counter(r.get("status", "unknown") for r in records)
    factory_counts = Counter(r.get("factory", "unknown") for r in records)
    total_lines = sum(r.get("lines", 0) for r in records)

    summary = (
        f"[DIGEST] Overall: {total} extractions ingested | "
        f"Status: {dict(status_counts)} | "
        f"Factories: {dict(factory_counts)} | "
        f"Total measurement lines: {total_lines}"
    )
    digests.append({
        "text": summary,
        "type": "overall",
        "timestamp": now.isoformat(),
    })

    # --- 2. Top clients per factory ---
    factory_clients = {}
    for r in records:
        factory = r.get("factory", "unknown")
        client = r.get("client")
        if client:
            if factory not in factory_clients:
                factory_clients[factory] = Counter()
            factory_clients[factory][client] += 1

    for factory, clients in factory_clients.items():
        top = clients.most_common(15)
        client_lines = ", ".join(f"{name} ({count})" for name, count in top)
        digest = (
            f"[DIGEST] Top clients [{factory}]: {client_lines} | "
            f"Total unique clients: {len(clients)}"
        )
        digests.append({
            "text": digest,
            "type": "top_clients",
            "factory": factory,
            "timestamp": now.isoformat(),
        })

    # --- 3. Daily volume trends ---
    daily = Counter()
    for r in records:
        date = r.get("created_date", "")[:10]
        if date:
            daily[date] += 1

    if daily:
        sorted_days = sorted(daily.items())
        trend_lines = ", ".join(f"{d}: {c}" for d, c in sorted_days[-14:])
        digests.append({
            "text": f"[DIGEST] Daily extraction volume (last 14d): {trend_lines}",
            "type": "daily_volume",
            "timestamp": now.isoformat(),
        })

    # --- 4. Glass type frequency ---
    glass_counter = Counter()
    for r in records:
        for g in r.get("glasses", []):
            glass_counter[g] += 1

    if glass_counter:
        top_glass = glass_counter.most_common(20)
        glass_lines = ", ".join(f"{g} ({c})" for g, c in top_glass)
        digests.append({
            "text": f"[DIGEST] Top glass types: {glass_lines}",
            "type": "glass_types",
            "timestamp": now.isoformat(),
        })

    # --- 5. Matching quality ---
    with_match = sum(1 for r in records if r.get("matched_rows", 0) > 0)
    confs = [r["confidence"] for r in records if "confidence" in r]
    avg_conf = sum(confs) / len(confs) if confs else 0

    digests.append({
        "text": (
            f"[DIGEST] Matching quality: {with_match}/{total} extractions matched "
            f"({with_match/total*100:.1f}%) | "
            f"Avg confidence: {avg_conf:.1%} (across {len(confs)} scored extractions)"
        ),
        "type": "matching_quality",
        "timestamp": now.isoformat(),
    })

    # --- 6. Weekly client rankings (last 7 days) ---
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    weekly_clients = Counter()
    weekly_count = 0
    for r in records:
        date = r.get("created_date", "")[:10]
        if date >= week_ago:
            weekly_count += 1
            client = r.get("client")
            if client:
                weekly_clients[client] += 1

    if weekly_clients:
        top_weekly = weekly_clients.most_common(15)
        weekly_lines = ", ".join(f"{name} ({count})" for name, count in top_weekly)
        digests.append({
            "text": (
                f"[DIGEST] This week's top clients (since {week_ago}): {weekly_lines} | "
                f"Total extractions this week: {weekly_count}"
            ),
            "type": "weekly_clients",
            "timestamp": now.isoformat(),
        })

    # Save digests
    save_digests(digests)
    return digests
