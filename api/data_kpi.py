"""Pull KPIs and metrics from data.aws.monce.ai."""

import logging
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

DATA_BASE = "https://data.aws.monce.ai"
DATA_AUTH = HTTPBasicAuth("monce", "Data@Monce")


def _get(endpoint: str, params: dict = None, timeout: int = 120) -> dict:
    """GET from data.aws.monce.ai with auth."""
    resp = requests.get(
        f"{DATA_BASE}{endpoint}",
        params=params,
        auth=DATA_AUTH,
        timeout=timeout,
    )
    if resp.status_code != 200:
        logger.error(f"data.aws.monce.ai {endpoint} error: {resp.status_code} — {resp.text}")
        raise RuntimeError(f"data.aws.monce.ai error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def fetch_accuracy(days: int = 7, factory_id: Optional[int] = None) -> dict:
    """Fetch extraction accuracy KPI.

    Returns overall accuracy, per-field breakdown, per-factory breakdown,
    perfect extraction rate, and Snake expression method distribution.
    """
    params = {"days": days}
    if factory_id is not None:
        params["factory_id"] = factory_id
    return _get("/api/kpi/accuracy", params)


def fetch_volume(days: int = 7, factory_id: Optional[int] = None) -> dict:
    """Fetch extraction volume KPI.

    Returns total extractions, verified count, verification rate,
    daily breakdown, and per-factory totals.
    """
    params = {"days": days}
    if factory_id is not None:
        params["factory_id"] = factory_id
    return _get("/api/kpi/volume", params)


def fetch_suggestions(days: int = 7, factory_id: Optional[int] = None, min_confidence: float = 0.5) -> dict:
    """Fetch synonym suggestions from extraction data.

    Returns Snake SAT matches that should be added as synonyms,
    no-match queries that need investigation, and stats.
    """
    params = {"days": days, "min_confidence": min_confidence}
    if factory_id is not None:
        params["factory_id"] = factory_id
    return _get("/api/kpi/suggestions", params)


def fetch_comments_stats(days: int = 7) -> dict:
    """Fetch user feedback/comment statistics."""
    return _get("/api/comments/stats", {"days": days})


def fetch_standup(hours: int = 48) -> dict:
    """Fetch daily standup report."""
    return _get("/api/comments/standup", {"hours": hours})


def fetch_pending_synonyms(factory_id: Optional[int] = None) -> dict:
    """Fetch count of pending synonym reviews."""
    params = {}
    if factory_id is not None:
        params["factory_id"] = factory_id
    return _get("/api/synonyms/pending/count", params)


def fetch_all_kpis(days: int = 7, factory_id: Optional[int] = None) -> dict:
    """Fetch all KPIs in one call — accuracy + volume + suggestions + pending synonyms.

    This is the main entry point for Concierge to get a full picture.
    """
    result = {}

    try:
        result["accuracy"] = fetch_accuracy(days=days, factory_id=factory_id)
    except Exception as e:
        result["accuracy_error"] = str(e)

    try:
        result["volume"] = fetch_volume(days=days, factory_id=factory_id)
    except Exception as e:
        result["volume_error"] = str(e)

    try:
        result["suggestions"] = fetch_suggestions(days=days, factory_id=factory_id)
    except Exception as e:
        result["suggestions_error"] = str(e)

    try:
        result["pending_synonyms"] = fetch_pending_synonyms(factory_id=factory_id)
    except Exception as e:
        result["pending_synonyms_error"] = str(e)

    return result


def summarize_kpis_for_memory(kpis: dict) -> str:
    """Turn KPI response into a concise memory string for Concierge."""
    parts = []

    acc = kpis.get("accuracy", {})
    if acc:
        overall = acc.get("overall_accuracy", "?")
        perfect = acc.get("perfect_extraction_rate", "?")
        wo_ref = acc.get("overall_accuracy_wo_ref", "?")
        parts.append(f"Accuracy: {overall}% overall, {wo_ref}% excl. ref, {perfect}% perfect extractions")

        # Snake expression breakdown
        snake = acc.get("snake_expression", {})
        if snake:
            exact = snake.get("exact", {}).get("pct", "?")
            sat = snake.get("sat", {}).get("pct", "?")
            low = snake.get("low_conf", {}).get("pct", "?")
            parts.append(f"Snake: {exact}% exact, {sat}% SAT, {low}% low-conf")

    vol = kpis.get("volume", {})
    if vol:
        total = vol.get("total_extractions", "?")
        verified = vol.get("total_verified", "?")
        rate = vol.get("verification_rate", "?")
        parts.append(f"Volume: {total} extractions, {verified} verified ({rate}%)")

    sug = kpis.get("suggestions", {})
    if sug:
        stats = sug.get("stats", {})
        total_q = stats.get("total_queries", 0)
        sat_matches = stats.get("snake_sat", 0)
        no_match = stats.get("no_match", 0)
        parts.append(f"Synonym gaps: {sat_matches} SAT-only (need synonyms), {no_match} no-match out of {total_q} queries")

    pending = kpis.get("pending_synonyms", {})
    if pending:
        count = pending.get("count", 0)
        if count:
            parts.append(f"Pending synonym reviews: {count}")

    return " | ".join(parts) if parts else "No KPI data available"
