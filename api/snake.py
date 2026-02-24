"""Snake API client — push synonyms to snake.aws.monce.ai."""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SNAKE_BASE = "https://snake.aws.monce.ai"


def add_article_synonym(
    text: str,
    num_article: str,
    factory_id: str,
    trigger_rebuild: bool = False,
) -> dict:
    """Add an article synonym to Snake.

    Args:
        text: The synonym text (e.g. "PLANILUX 4MM" for article 12345)
        num_article: The article number to map to
        factory_id: Factory tenant ID (e.g. "GLASSYA", "SGD")
        trigger_rebuild: Whether to rebuild the factory after adding
    """
    resp = requests.post(
        f"{SNAKE_BASE}/synonyms",
        json={
            "text": text,
            "num_article": num_article,
            "factory_id": factory_id,
            "trigger_rebuild": trigger_rebuild,
        },
        timeout=30,
    )

    if resp.status_code != 200:
        logger.error(f"Snake /synonyms error: {resp.status_code} — {resp.text}")
        raise RuntimeError(f"Snake API error {resp.status_code}: {resp.text}")

    return resp.json()


def add_client_synonym(
    text: str,
    numero_client: str,
    factory_id: str,
    trigger_rebuild: bool = False,
) -> dict:
    """Add a client synonym to Snake.

    Args:
        text: The synonym text (e.g. "SAINT GOBAIN PARIS" for client 7890)
        numero_client: The client number to map to
        factory_id: Factory tenant ID
        trigger_rebuild: Whether to rebuild the factory after adding
    """
    resp = requests.post(
        f"{SNAKE_BASE}/synonym_client",
        json={
            "text": text,
            "numero_client": numero_client,
            "factory_id": factory_id,
            "trigger_rebuild": trigger_rebuild,
        },
        timeout=30,
    )

    if resp.status_code != 200:
        logger.error(f"Snake /synonym_client error: {resp.status_code} — {resp.text}")
        raise RuntimeError(f"Snake API error {resp.status_code}: {resp.text}")

    return resp.json()


def rebuild_all() -> dict:
    """Trigger a full rebuild of all factory tenants on Snake."""
    resp = requests.post(
        f"{SNAKE_BASE}/rebuild_all",
        timeout=600,  # rebuilds can take a while
    )

    if resp.status_code != 200:
        logger.error(f"Snake /rebuild_all error: {resp.status_code} — {resp.text}")
        raise RuntimeError(f"Snake API error {resp.status_code}: {resp.text}")

    return resp.json()


def add_synonyms_batch(
    synonyms: list,
    synonym_type: str = "article",
) -> dict:
    """Add multiple synonyms in batch, then rebuild affected factories.

    Args:
        synonyms: List of dicts with keys:
            - article: {text, num_article, factory_id}
            - client: {text, numero_client, factory_id}
        synonym_type: "article" or "client"

    Returns summary of results.
    """
    results = {"added": 0, "errors": [], "factories_affected": set()}

    for syn in synonyms:
        try:
            if synonym_type == "article":
                add_article_synonym(
                    text=syn["text"],
                    num_article=syn["num_article"],
                    factory_id=syn["factory_id"],
                    trigger_rebuild=False,
                )
            else:
                add_client_synonym(
                    text=syn["text"],
                    numero_client=syn["numero_client"],
                    factory_id=syn["factory_id"],
                    trigger_rebuild=False,
                )
            results["added"] += 1
            results["factories_affected"].add(syn["factory_id"])
        except RuntimeError as e:
            results["errors"].append({"synonym": syn, "error": str(e)})

    # Rebuild all affected factories
    if results["added"] > 0:
        try:
            rebuild_result = rebuild_all()
            results["rebuild"] = rebuild_result
        except RuntimeError as e:
            results["rebuild_error"] = str(e)

    results["factories_affected"] = list(results["factories_affected"])
    return results
