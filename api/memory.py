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

    # --- 7. New/emerging clients (first seen in last 7 days) ---
    week_ago_str = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    two_weeks_ago_str = (now - timedelta(days=14)).strftime("%Y-%m-%d")

    old_clients = set()
    new_clients_this_week = Counter()
    for r in records:
        date = r.get("created_date", "")[:10]
        client = r.get("client")
        if not client:
            continue
        if date < week_ago_str:
            old_clients.add(client)
        elif date >= week_ago_str:
            new_clients_this_week[client] += 1

    emerging = {c: n for c, n in new_clients_this_week.items() if c not in old_clients}
    if emerging:
        sorted_emerging = sorted(emerging.items(), key=lambda x: x[1], reverse=True)[:15]
        emerging_lines = ", ".join(f"{name} ({count} orders)" for name, count in sorted_emerging)
        digests.append({
            "text": (
                f"[INTELLIGENCE] New clients this week (not seen before {week_ago_str}): "
                f"{emerging_lines} | {len(emerging)} new clients total"
            ),
            "type": "new_clients",
            "timestamp": now.isoformat(),
        })

    # --- 8. Client volume anomalies (week-over-week spikes/drops) ---
    prev_week_clients = Counter()
    curr_week_clients = Counter()
    for r in records:
        date = r.get("created_date", "")[:10]
        client = r.get("client")
        if not client or not date:
            continue
        if two_weeks_ago_str <= date < week_ago_str:
            prev_week_clients[client] += 1
        elif date >= week_ago_str:
            curr_week_clients[client] += 1

    spikes = []
    drops = []
    all_clients_both_weeks = set(prev_week_clients) | set(curr_week_clients)
    for client in all_clients_both_weeks:
        prev = prev_week_clients.get(client, 0)
        curr = curr_week_clients.get(client, 0)
        if prev >= 3 and curr >= prev * 2:
            spikes.append((client, prev, curr))
        elif prev >= 3 and curr <= prev * 0.3:
            drops.append((client, prev, curr))

    if spikes:
        spikes.sort(key=lambda x: x[2], reverse=True)
        spike_lines = ", ".join(f"{c} ({p}→{cu}, +{(cu/p-1)*100:.0f}%)" for c, p, cu in spikes[:10])
        digests.append({
            "text": f"[INTELLIGENCE] Volume spikes (2x+ week-over-week): {spike_lines}",
            "type": "volume_spikes",
            "timestamp": now.isoformat(),
        })

    if drops:
        drops.sort(key=lambda x: x[1], reverse=True)
        drop_lines = ", ".join(f"{c} ({p}→{cu}, -{(1-cu/p)*100:.0f}%)" for c, p, cu in drops[:10])
        digests.append({
            "text": f"[INTELLIGENCE] Volume drops (70%+ decline week-over-week): {drop_lines}",
            "type": "volume_drops",
            "timestamp": now.isoformat(),
        })

    # --- 9. Glass type shifts (new types appearing this week) ---
    old_glasses = set()
    new_glasses_this_week = Counter()
    for r in records:
        date = r.get("created_date", "")[:10]
        for g in r.get("glasses", []):
            if date < week_ago_str:
                old_glasses.add(g)
            elif date >= week_ago_str:
                new_glasses_this_week[g] += 1

    emerging_glass = {g: n for g, n in new_glasses_this_week.items() if g not in old_glasses}
    if emerging_glass:
        sorted_eg = sorted(emerging_glass.items(), key=lambda x: x[1], reverse=True)[:10]
        eg_lines = ", ".join(f"{g} ({n}x)" for g, n in sorted_eg)
        digests.append({
            "text": f"[INTELLIGENCE] New glass types this week (not seen before): {eg_lines}",
            "type": "new_glass_types",
            "timestamp": now.isoformat(),
        })

    # --- 10. Client product diversification (clients ordering new glass types) ---
    client_glasses_old = {}
    client_glasses_new = {}
    for r in records:
        date = r.get("created_date", "")[:10]
        client = r.get("client")
        if not client:
            continue
        glasses = set(r.get("glasses", []))
        if date < week_ago_str:
            client_glasses_old.setdefault(client, set()).update(glasses)
        elif date >= week_ago_str:
            client_glasses_new.setdefault(client, set()).update(glasses)

    diversifying = []
    for client in client_glasses_new:
        if client in client_glasses_old:
            new_types = client_glasses_new[client] - client_glasses_old[client]
            if new_types:
                diversifying.append((client, new_types))

    if diversifying:
        diversifying.sort(key=lambda x: len(x[1]), reverse=True)
        div_lines = ", ".join(
            f"{c} (+{', '.join(list(g)[:3])})"
            for c, g in diversifying[:10]
        )
        digests.append({
            "text": (
                f"[INTELLIGENCE] Clients ordering new product types this week: {div_lines} | "
                f"{len(diversifying)} clients diversifying"
            ),
            "type": "product_diversification",
            "timestamp": now.isoformat(),
        })

    # --- 11. Low-confidence hotspots (clients/factories needing synonym work) ---
    low_conf_clients = Counter()
    low_conf_factories = Counter()
    for r in records:
        conf = r.get("confidence")
        if conf is not None and conf < 0.7:
            client = r.get("client")
            factory = r.get("factory")
            if client:
                low_conf_clients[client] += 1
            if factory:
                low_conf_factories[factory] += 1

    if low_conf_clients:
        top_low = low_conf_clients.most_common(10)
        low_lines = ", ".join(f"{c} ({n} low-conf)" for c, n in top_low)
        digests.append({
            "text": (
                f"[INTELLIGENCE] Clients with most low-confidence matches (<70%): {low_lines} | "
                f"These may need synonym additions on Snake"
            ),
            "type": "low_confidence_hotspots",
            "timestamp": now.isoformat(),
        })

    # --- 12. Factory activity distribution shift ---
    prev_factory = Counter()
    curr_factory = Counter()
    for r in records:
        date = r.get("created_date", "")[:10]
        factory = r.get("factory", "unknown")
        if two_weeks_ago_str <= date < week_ago_str:
            prev_factory[factory] += 1
        elif date >= week_ago_str:
            curr_factory[factory] += 1

    prev_total = sum(prev_factory.values()) or 1
    curr_total = sum(curr_factory.values()) or 1
    all_factories = set(prev_factory) | set(curr_factory)
    shifts = []
    for f in all_factories:
        prev_pct = prev_factory.get(f, 0) / prev_total * 100
        curr_pct = curr_factory.get(f, 0) / curr_total * 100
        if abs(curr_pct - prev_pct) > 5:
            shifts.append((f, prev_pct, curr_pct))

    if shifts:
        shift_lines = ", ".join(
            f"{f} ({p:.0f}%→{c:.0f}%)" for f, p, c in sorted(shifts, key=lambda x: abs(x[2]-x[1]), reverse=True)
        )
        digests.append({
            "text": f"[INTELLIGENCE] Factory volume share shifts (>5pt change): {shift_lines}",
            "type": "factory_shifts",
            "timestamp": now.isoformat(),
        })

    # Save digests
    save_digests(digests)
    return digests
