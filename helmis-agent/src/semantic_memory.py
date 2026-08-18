"""
semantic_memory.py — Vector-backed episodic & preference memory for Helmis.

Provides Mem0-grade automatic memory extraction, vector embeddings,
and semantic retrieval rotated across all Gemini API keys.
"""

import json
import logging
import math
import os
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx

from .agent import GEMINI_KEYS, GEMINI_MODELS, get_next_gemini_key

log = logging.getLogger("helmis-semantic-memory")

DATA_DIR = os.environ.get("DATA_DIR", "/app/data" if os.path.exists("/app") else "./data")
SEMANTIC_MEMORY_FILE = os.path.join(DATA_DIR, "semantic_memories.json")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Jakarta"))


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(SEMANTIC_MEMORY_FILE), exist_ok=True)


def load_semantic_memories() -> list[dict[str, Any]]:
    """Load persistent memories from disk."""
    _ensure_dir()
    if not os.path.exists(SEMANTIC_MEMORY_FILE):
        return []
    try:
        with open(SEMANTIC_MEMORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return cast(list[dict[str, Any]], data)
    except Exception as e:
        log.error("Failed to load semantic memory file: %s", e)
    return []


def save_semantic_memories(memories: list[dict[str, Any]]) -> None:
    """Save persistent memories to disk."""
    _ensure_dir()
    try:
        with open(SEMANTIC_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memories, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error("Failed to save semantic memory file: %s", e)


async def get_embedding(text: str) -> list[float] | None:
    """Compute 3072-dimensional embedding using Google Gemini API with key rotation."""
    if not text.strip():
        return None

    for _ in range(len(GEMINI_KEYS) or 1):
        key = get_next_gemini_key()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={key}"
        payload = {"content": {"parts": [{"text": text.strip()}]}}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    values = resp.json().get("embedding", {}).get("values", [])
                    if isinstance(values, list) and len(values) > 0:
                        return cast(list[float], values)
                elif resp.status_code == 429:
                    log.warning("Embedding key rate-limited (429), rotating...")
                    continue
                else:
                    log.warning("Embedding key error %d, rotating...", resp.status_code)
                    continue
        except Exception as e:
            log.warning("Embedding exception: %s, rotating...", e)
            continue
    return None


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    if len(v1) != len(v2) or not v1 or not v2:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2, strict=True))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


async def add_memory(fact: str, user_id: str, category: str = "general") -> dict[str, Any] | None:
    """
    Store a new episodic fact or preference in semantic memory with vector embedding.
    """
    clean_fact = fact.strip()
    if not clean_fact:
        return None

    # Check for exact duplicate text
    memories = load_semantic_memories()
    for m in memories:
        if m.get("fact", "").lower() == clean_fact.lower() and m.get("user_id") == user_id:
            log.debug("Memory already exists: %s", clean_fact)
            return m

    embedding = await get_embedding(clean_fact)
    now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M WIB")

    entry: dict[str, Any] = {
        "id": f"mem_{int(datetime.now().timestamp() * 1000)}",
        "fact": clean_fact,
        "user_id": user_id,
        "category": category,
        "created_at": now_str,
        "embedding": embedding,
    }

    memories.append(entry)
    save_semantic_memories(memories)
    log.info("Saved new semantic memory for [%s]: %s", user_id, clean_fact)
    return entry


async def search_memories(
    query: str,
    user_id: str | None = None,
    top_k: int = 5,
    min_score: float = 0.65,
) -> list[dict[str, Any]]:
    """
    Semantically search memories relevant to the query and user.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    memories = load_semantic_memories()
    if not memories:
        return []

    q_vector = await get_embedding(clean_query)
    results: list[tuple[float, dict[str, Any]]] = []

    for m in memories:
        # Filter by user if specified
        if user_id and m.get("user_id") not in (user_id, "Both", "all"):
            continue

        vec = m.get("embedding")
        if vec and q_vector:
            score = cosine_similarity(q_vector, vec)
        else:
            # Fallback to keyword match if embedding is missing
            score = (
                0.8
                if any(word in m.get("fact", "").lower() for word in clean_query.lower().split())
                else 0.0
            )

        if score >= min_score:
            res_item = {
                "fact": m.get("fact"),
                "user_id": m.get("user_id"),
                "category": m.get("category"),
                "score": round(score, 3),
            }
            results.append((score, res_item))

    # Sort descending by similarity score
    results.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in results[:top_k]]


def delete_memory(query: str, user_id: str | None = None) -> dict[str, Any]:
    """Delete facts/preferences matching query keyword from semantic vector storage."""
    memories = load_semantic_memories()
    clean_q = query.strip().lower()
    initial_count = len(memories)

    kept: list[dict[str, Any]] = []
    deleted: list[str] = []
    for m in memories:
        if (not user_id or m.get("user_id") in (user_id, "Both", "all")) and clean_q in m.get("fact", "").lower():
            deleted.append(str(m.get("fact", "")))
        else:
            kept.append(m)

    if len(kept) < initial_count:
        save_semantic_memories(kept)
        log.info("Deleted %d semantic memories matching '%s'", len(deleted), query)
        return {
            "status": "success",
            "deleted_count": len(deleted),
            "deleted_facts": deleted,
            "message": f"Berhasil menghapus {len(deleted)} memori.",
        }
    return {"status": "not_found", "message": f"Tidak ditemukan memori yang cocok dengan '{query}'."}


async def extract_facts_from_turn_background(
    user_message: str,
    assistant_reply: str,
    sender_name: str,
) -> None:
    """
    Passive background worker: Extracts durable facts, personal preferences,
    routines, and key context from a conversation turn and stores them in vector memory.
    """
    if len(user_message.strip()) < 8:
        return

    prompt = f"""
Analyze the following conversation turn between {sender_name} and Helmis (personal assistant).
Identify if {sender_name} shared any durable personal facts, preferences, habits, health/dietary info, relationships, or ongoing projects that an executive secretary should remember forever.

User ({sender_name}): "{user_message}"
Helmis: "{assistant_reply}"

Rules:
- Only extract persistent personal facts or preferences (e.g. "Gilang prefers black coffee", "Bunga has a cat named Mimi", "Gilang is studying for Syariah Economics exam").
- Do NOT extract transient questions, one-off greetings, or temporary task requests (tasks are already handled separately).
- If no durable facts or preferences were mentioned, return an empty array [].
- Output ONLY a JSON array of concise fact strings in Indonesian or English.

Example output:
["Gilang tidak suka kopi manis", "Gilang alergi kacang"]
"""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }

    extracted_facts: list[str] = []
    for model in GEMINI_MODELS:
        for _ in range(len(GEMINI_KEYS) or 1):
            key = get_next_gemini_key()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        text = (
                            data.get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [{}])[0]
                            .get("text", "")
                        )
                        parsed = json.loads(text)
                        if isinstance(parsed, list):
                            extracted_facts = [str(x).strip() for x in parsed if str(x).strip()]
                        break
                    elif resp.status_code == 429:
                        continue
                    elif resp.status_code == 404:
                        break
            except Exception:
                pass
        if extracted_facts:
            break

    for fact in extracted_facts:
        await add_memory(fact=fact, user_id=sender_name)
