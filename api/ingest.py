"""Ingest extraction data from monce_db into Concierge memory."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import memory

logger = logging.getLogger(__name__)


def _get_monce_client():
    """Create a MonceClient from environment variables."""
    # Import monce_db — must be installed: pip install -e /path/to/data.aws.monce.ai
    try:
        from monce_db import MonceClient
    except ImportError:
        raise RuntimeError(
            "monce_db not installed. Install with: "
            "pip install -e /path/to/data.aws.monce.ai"
        )

    return MonceClient(
        access_key=os.environ.get("MONCE_S3_ACCESS_KEY"),
        secret_key=os.environ.get("MONCE_S3_SECRET_KEY"),
        bucket=os.environ.get("MONCE_S3_BUCKET", "monceai-prod-extraction-charles"),
        region=os.environ.get("MONCE_S3_REGION", "eu-west-3"),
    )


def _summarize_extraction(ext: dict) -> str:
    """Turn a raw extraction dict into a concise memory string."""
    parts = []

    # Factory/tenant
    factory = ext.get("_factory_name") or f"factory_{ext.get('factory_id', '?')}"
    tenant = ext.get("_tenant_name", "")
    parts.append(f"[{factory}]" + (f" ({tenant})" if tenant else ""))

    # Status
    status = ext.get("status", "unknown")
    parts.append(f"status={status}")

    # Client
    cm = ext.get("client_matching")
    if isinstance(cm, dict) and cm.get("nom"):
        client_str = cm["nom"]
        if cm.get("numero_client"):
            client_str += f" #{cm['numero_client']}"
        method = cm.get("method", "")
        tier = cm.get("tier", "")
        parts.append(f"client={client_str} (tier {tier}, {method})")

    # Measurements
    value = ext.get("value")
    if isinstance(value, dict):
        measurements = value.get("measurements", [])
        n_rows = len(measurements)
        parts.append(f"{n_rows} line(s)")

        # Glass types seen
        glasses = set()
        for m in measurements:
            for field in ("verre1", "verre2", "verre3"):
                v = m.get(field)
                if v:
                    glasses.add(v)
        if glasses:
            parts.append(f"glass: {', '.join(list(glasses)[:3])}")

        # Project title
        title = value.get("project_title")
        if title:
            parts.append(f'project="{title[:60]}"')

    # Matching quality
    matching = ext.get("matching")
    if isinstance(matching, dict) and matching:
        n_matched = len(matching)
        parts.append(f"{n_matched} row(s) matched")

    # Confidence
    conf = ext.get("confidence")
    if conf is not None:
        parts.append(f"conf={conf:.0%}")

    # Dates
    created = ext.get("created_at", "")
    if created:
        parts.append(f"created={created[:10]}")

    return " | ".join(parts)


def ingest_extractions(
    days: int = 14,
    factory: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """Pull extractions from monce_db and store as memories.

    Args:
        days: Number of days to look back (default: 14)
        factory: Factory name or ID to filter (default: all)
        status: Filter by status (default: all)

    Returns:
        {"ingested": int, "skipped": int, "total_fetched": int}
    """
    client = _get_monce_client()

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    where = f"created_at >= '{since}'"
    if status:
        where += f" AND status='{status}'"

    logger.info(f"Ingesting extractions: days={days}, factory={factory}, status={status}")

    kwargs = {"table": "extracted_data", "where": where}
    if factory:
        kwargs["factory"] = factory

    data = client.fetch(**kwargs)
    logger.info(f"Fetched {len(data)} extractions from monce_db")

    # Check existing memories to avoid duplicates
    existing = memory.load_memories()
    existing_ids = set()
    for m in existing:
        if m.get("tags") and "extraction" in m.get("tags", []):
            text = m.get("text", "")
            if "ext_id=" in text:
                eid = text.split("ext_id=")[1].split(" ")[0].split("|")[0].strip()
                existing_ids.add(eid)

    # Batch build new memories (avoid O(n^2) JSON I/O)
    new_entries = []
    skipped = 0

    for ext in data:
        ext_id = ext.get("id", "")
        if ext_id in existing_ids:
            skipped += 1
            continue

        summary = _summarize_extraction(ext)
        text = f"ext_id={ext_id} | {summary}"

        tags = ["extraction", ext.get("status", "unknown")]
        factory_name = ext.get("_factory_name")
        if factory_name:
            tags.append(factory_name)

        new_entries.append({
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "monce_db",
            "tags": tags,
        })

    # Single write
    if new_entries:
        existing.extend(new_entries)
        memory.save_memories(existing)

    ingested = len(new_entries)
    logger.info(f"Ingested {ingested} extractions, skipped {skipped} duplicates")

    return {
        "ingested": ingested,
        "skipped": skipped,
        "total_fetched": len(data),
        "days": days,
        "factory": factory,
        "status": status,
    }


def ingest_stats(factory: Optional[str] = None) -> dict:
    """Pull aggregate stats from monce_db and store as a single memory.

    Returns stats dict.
    """
    client = _get_monce_client()

    stats = client.get_stats(factory=factory)
    factory_label = factory or "all"

    text = (
        f"[monce_db stats {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC] "
        f"factory={factory_label} | "
        f"total={stats['total']} verified={stats['verified']} "
        f"extracted={stats['extracted']} rejected={stats['rejected']} "
        f"matching={stats['with_matching']} "
        f"verified%={stats['verified_pct']}% matching%={stats['matching_pct']}%"
    )

    memory.add_memory(text, source="monce_db", tags=["stats", factory_label])

    return stats
