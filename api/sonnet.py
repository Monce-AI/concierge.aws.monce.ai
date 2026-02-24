"""Bedrock Sonnet caller for Concierge chat and analysis."""

import json
import logging
import time

import requests

from .config import config
from .memory import get_recent_memories, get_recent_conversations, load_manifest

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

Personality:
- Sharp, concise, data-driven.
- You speak like an experienced ops analyst who's seen every order come through.
- When asked about patterns, you synthesize from your memories — don't just list, interpret.
- French context welcome (Monce is a French glass industry company), but default to English unless spoken to in French.

When you have memories/context, use them to give informed answers. When you don't have enough data, say so clearly."""


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
    """Chat with Concierge using full memory context.

    Returns: {"reply": str, "latency_ms": int}
    """
    manifest = load_manifest()
    recent_memories = get_recent_memories(30)
    recent_convos = get_recent_conversations(10)

    # Build context
    context_parts = []

    if manifest and manifest != "No manifest defined yet.":
        context_parts.append(f"## Manifest\n{manifest}")

    if recent_memories:
        mem_text = "## Recent memories\n"
        for m in recent_memories:
            tags = f" [{', '.join(m['tags'])}]" if m.get("tags") else ""
            source = f" (from {m['source']})" if m.get("source") else ""
            mem_text += f"- {m['text']}{tags}{source} — {m['timestamp']}\n"
        context_parts.append(mem_text)

    if recent_convos:
        convo_text = "## Recent conversations\n"
        for c in recent_convos:
            convo_text.append  # Skip if empty
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
