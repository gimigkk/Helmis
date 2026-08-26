"""
semantic_memory.py — Vector-backed episodic & preference memory for Helmis.

Provides Mem0-grade automatic memory extraction, vector embeddings,
and semantic retrieval rotated across all Gemini API keys.
"""

import json
import logging
import math
import os
import threading
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx

from .cascade import GEMINI_KEYS, GEMINI_MODELS, get_next_gemini_key

log = logging.getLogger("helmis-semantic-memory")

DATA_DIR = os.environ.get("DATA_DIR", "/app/data" if os.path.exists("/app") else "./data")
SEMANTIC_MEMORY_FILE = os.path.join(DATA_DIR, "semantic_memories.json")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Jakarta"))

_semantic_lock = threading.RLock()


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(SEMANTIC_MEMORY_FILE), exist_ok=True)


def load_semantic_memories() -> list[dict[str, Any]]:
    """Load persistent memories from disk with thread-safety."""
    _ensure_dir()
    with _semantic_lock:
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
    """Save persistent memories atomically to disk."""
    _ensure_dir()
    with _semantic_lock:
        tmp_file = f"{SEMANTIC_MEMORY_FILE}.tmp.{os.getpid()}"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(memories, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, SEMANTIC_MEMORY_FILE)
        except Exception as e:
            log.error("Failed to save semantic memory file: %s", e)
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass


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
    Automatically supersedes/updates existing memories if the fact updates a previously recorded topic
    (similarity >= 0.88), preventing memory rot across semesters or changing routines.
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

    # Semantic supersession check: If a memory on the same topic exists with high similarity >= 0.88
    if embedding:
        for m in memories:
            if m.get("user_id") == user_id and m.get("embedding"):
                sim = cosine_similarity(embedding, m["embedding"])
                if sim >= 0.88:
                    old_fact = m.get("fact")
                    m["fact"] = clean_fact
                    m["category"] = category
                    m["created_at"] = now_str
                    m["embedding"] = embedding
                    save_semantic_memories(memories)
                    log.info(
                        "Superseded existing memory for [%s] (sim=%.2f): '%s' -> '%s'",
                        user_id,
                        sim,
                        old_fact,
                        clean_fact,
                    )
                    return m

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
                "created_at": m.get("created_at"),
                "score": round(score, 3),
            }
            results.append((score, res_item))

    # Sort descending by similarity score
    results.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in results[:top_k]]


async def delete_memory(query: str, user_id: str | None = None) -> dict[str, Any]:
    """Delete facts/preferences matching query keyword or semantic meaning from vector storage."""
    memories = load_semantic_memories()
    clean_q = query.strip().lower()
    if not clean_q:
        return {"status": "error", "error": "Query tidak boleh kosong."}

    initial_count = len(memories)
    q_tokens = [w for w in clean_q.split() if len(w) > 2]

    kept: list[dict[str, Any]] = []
    deleted: list[str] = []

    # First pass: substring or token matching
    for m in memories:
        f_text = str(m.get("fact", "")).lower()
        u_match = not user_id or m.get("user_id") in (user_id, "Both", "all")
        matched = u_match and (clean_q in f_text or (q_tokens and all(tok in f_text for tok in q_tokens)))
        if matched:
            deleted.append(str(m.get("fact", "")))
        else:
            kept.append(m)

    # Second pass: if nothing matched with tokens, try embedding similarity > 0.78
    if not deleted:
        try:
            q_vec = await get_embedding(clean_q)
            kept_vec: list[dict[str, Any]] = []
            for m in kept:
                u_match = not user_id or m.get("user_id") in (user_id, "Both", "all")
                vec = m.get("embedding")
                if u_match and vec and q_vec:
                    sim = cosine_similarity(q_vec, vec)
                    if sim >= 0.78:
                        deleted.append(str(m.get("fact", "")))
                        continue
                kept_vec.append(m)
            kept = kept_vec
        except Exception:
            pass

    if len(kept) < initial_count:
        save_semantic_memories(kept)
        log.info("Deleted %d semantic memories matching '%s'", len(deleted), query)
        return {
            "status": "success",
            "deleted_count": len(deleted),
            "deleted_facts": deleted,
            "message": f"Berhasil menghapus {len(deleted)} memori dari database.",
        }
    return {
        "status": "not_found",
        "deleted_count": 0,
        "message": f"Tidak ditemukan memori yang cocok dengan '{query}'. Memori tersebut memang belum pernah tersimpan di database.",
    }


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
