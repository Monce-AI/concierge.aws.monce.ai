"""Memory management for Concierge."""

import json
import os
from datetime import datetime
from typing import Optional

from .config import config


def _memories_path() -> str:
    return os.path.join(config.data_dir, "memories.json")


def _conversations_path() -> str:
    return os.path.join(config.data_dir, "conversations.json")


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
    # Keep last 200 conversations
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


def get_recent_memories(n: int = 30) -> list:
    return load_memories()[-n:]


def get_recent_conversations(n: int = 10) -> list:
    return load_conversations()[-n:]


def memory_count() -> int:
    return len(load_memories())


def conversation_count() -> int:
    return len(load_conversations())
