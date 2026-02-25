"""Bedrock Sonnet caller for Concierge chat and analysis."""

import json
import logging
import time

import requests

from .config import config
from .memory import (
    get_recent_memories, get_recent_conversations, load_manifest,
    load_digests, search_memories,
)

logger = logging.getLogger(__name__)

BEDROCK_URL = (
    f"https://bedrock-runtime.{config.aws_region}.amazonaws.com"
    f"/model/{config.bedrock_model}/invoke"
)

SYSTEM_PROMPT = """You are Moncey Concierge — the internal memory and intelligence layer for Monce AI.

Your role:
- You are the living memory of what passes through the Monce AI extraction pipeline (Claude VLM pipeline for glass manufacturing orders).
- You track order patterns, customer behavior, extraction volumes, and emerging trends.
- You serve as context provider for the future sales agent — everything you learn feeds into smarter agentic ordering.
- You report on extraction data: what's being processed, what's succeeding, what's failing, what patterns emerge.
- You know the Monce AI stack: Claude multistage extraction, Snake SAT matching, fuzzy article matching, customer prompt profiles.
- You proactively surface business intelligence signals when they appear in the data.

Context structure:
- [DIGEST] entries are pre-computed aggregates from ALL extraction data — use these for volume, ranking, and trend questions.
- [INTELLIGENCE] entries are business intelligence signals detected from extraction patterns — proactively surface these.
- [SEARCH] entries are memories matched to the user's query by keyword — use these for specific lookups.
- Recent memories are the latest raw ingestions — use these for "what just happened" questions.

Intelligence signals you track:
- New clients appearing for the first time — potential new business or competitors entering the market.
- Volume spikes/drops per client — expansion, contraction, or shifting suppliers.
- New glass types being ordered — new product lines, collections, or industry trend shifts.
- Client product diversification — customers ordering glass types they haven't ordered before (new projects, geographic expansion).
- Low-confidence matching hotspots — clients/factories where Snake synonym coverage is weak (action: add synonyms).
- Factory volume share shifts — changing distribution of work across factories (regulatory changes, capacity shifts).

Personality:
- Sharp, concise, data-driven. Use numbers.
- You speak like an experienced ops analyst who's seen every order come through.
- When asked about patterns, synthesize from digests first, then intelligence signals, then raw memories.
- French context welcome (Monce is a French glass industry company), but default to English unless spoken to in French.
- When you cite data, be specific: give counts, percentages, client names, dates.
- When intelligence signals are present, highlight them proactively — don't wait to be asked.

When you have memories/context, use them to give informed answers. When you don't have enough data, say so clearly and suggest running /ingest."""


def _call_sonnet(messages: list, system: str = None, max_tokens: int = 2048) -> str:
    if not config.aws_bearer_token:
        raise RuntimeError("AWS_BEARER_TOKEN_BEDROCK not set")

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        body["system"] = system

    response = requests.post(
        BEDROCK_URL,
        headers={
            "Authorization": f"Bearer {config.aws_bearer_token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60,
    )

    if response.status_code != 200:
        logger.error(f"Bedrock error: {response.status_code} — {response.text}")
        raise RuntimeError(f"Bedrock API error: {response.status_code}")

    result = response.json()
    return result.get("content", [{}])[0].get("text", "")


def chat(message: str) -> dict:
    """Chat with Concierge using digests + smart search + recent context.

    Returns: {"reply": str, "latency_ms": int}
    """
    manifest = load_manifest()
    digests = load_digests()
    search_results = search_memories(message, limit=20)
    recent_memories = get_recent_memories(10)
    recent_convos = get_recent_conversations(10)

    # Build context — prioritize digests, then search, then recent
    context_parts = []

    if manifest and manifest != "No manifest defined yet.":
        context_parts.append(f"## Manifest\n{manifest}")

    # Digests — pre-computed aggregates (always include, they're compact)
    if digests:
        digest_text = "## Digests (pre-computed from ALL extraction data)\n"
        for d in digests:
            digest_text += f"- {d['text']}\n"
        context_parts.append(digest_text)

    # Search results — memories relevant to this query
    if search_results:
        search_text = "## Search results (memories matching your query)\n"
        for m in search_results:
            tags = f" [{', '.join(m['tags'])}]" if m.get("tags") else ""
            search_text += f"- {m['text']}{tags}\n"
        context_parts.append(search_text)

    # Recent raw memories
    if recent_memories:
        mem_text = "## Recent memories (latest 10)\n"
        for m in recent_memories:
            tags = f" [{', '.join(m['tags'])}]" if m.get("tags") else ""
            mem_text += f"- {m['text']}{tags} — {m['timestamp']}\n"
        context_parts.append(mem_text)

    # Recent conversations
    if recent_convos:
        convo_text = "## Recent conversations\n"
        for c in recent_convos:
            convo_text += f"- User: {c['user'][:100]}\n  Concierge: {c['assistant'][:100]}\n"
        context_parts.append(convo_text)

    system = SYSTEM_PROMPT
    if context_parts:
        system += "\n\n---\n\n" + "\n\n".join(context_parts)

    messages = [{"role": "user", "content": message}]

    start = time.time()
    reply = _call_sonnet(messages, system=system)
    latency_ms = int((time.time() - start) * 1000)

    logger.info(f"Sonnet chat took {latency_ms}ms")
    return {"reply": reply, "latency_ms": latency_ms}
