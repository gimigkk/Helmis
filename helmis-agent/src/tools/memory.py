"""
memory.py — Tool Handlers for Episodic Semantic Vector Memory & Global Search.
"""

from typing import Any

from ..memory import semantic as semantic_memory
from ..memory.store import search_memory
from .registry import register_tool


@register_tool("remember_fact")
async def handle_remember_fact(args: dict[str, Any], default_sender: str) -> dict[str, Any]:
    fact = str(args.get("fact", "")).strip()
    user_id = str(args.get("user_id") or default_sender).strip()
    if not fact:
        return {"status": "error", "error": "Fakta/preferensi tidak boleh kosong."}

    saved = await semantic_memory.add_memory(
        fact=fact,
        user_id=user_id,
        provenance="explicit_remember_fact_tool",
        source_turn_id=str(args.get("source_turn_id") or "") or None,
        scope=str(args.get("scope") or "private"),
    )
    return {
        "status": "success",
        "saved_fact": saved,
        "message": f"Fakta/preferensi '{fact}' untuk {user_id} berhasil diingat ke memori jangka panjang.",
    }


@register_tool("correct_fact")
async def handle_correct_fact(args: dict[str, Any], default_sender: str) -> dict[str, Any]:
    old_claim = str(args.get("query") or args.get("old_fact") or "").strip()
    new_fact = str(args.get("corrected_fact") or args.get("fact") or "").strip()
    user_id = str(args.get("user_id") or default_sender).strip()
    if not old_claim:
        return {"status": "error", "error": "Klaim lama yang dikoreksi tidak boleh kosong."}
    if not new_fact:
        return {"status": "error", "error": "Fakta koreksi tidak boleh kosong."}

    return await semantic_memory.correct_memory(
        query=old_claim,
        corrected_fact=new_fact,
        user_id=user_id,
        source_turn_id=str(args.get("source_turn_id") or "") or None,
    )


@register_tool("delete_memory")
async def handle_delete_memory(args: dict[str, Any], default_sender: str) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    user_id = str(args.get("user_id") or default_sender).strip()
    if not query:
        return {"status": "error", "error": "Query penghapusan memori tidak boleh kosong."}

    return await semantic_memory.delete_memory(query=query, user_id=user_id)


@register_tool("recall_memory")
async def handle_recall_memory(args: dict[str, Any], default_sender: str) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"status": "error", "error": "Query pencarian memori tidak boleh kosong."}

    results = await semantic_memory.search_memories(
        query=query, user_id=default_sender, top_k=5
    )
    return {"status": "success", "count": len(results), "results": results}


@register_tool("search_memory")
def handle_search_memory(args: dict[str, Any]) -> dict[str, Any]:
    keyword = str(args.get("keyword") or args.get("query") or "").strip()
    mem_results = search_memory(keyword)
    return {"status": "success", "results": mem_results}


@register_tool("list_memory_candidates")
def handle_list_memory_candidates(args: dict[str, Any], default_sender: str) -> dict[str, Any]:
    candidates = semantic_memory.list_memory_candidates(user_id=default_sender)
    return {"status": "success", "count": len(candidates), "candidates": candidates}


@register_tool("confirm_memory_candidate")
def handle_confirm_memory_candidate(args: dict[str, Any], default_sender: str) -> dict[str, Any]:
    memory_id = str(args.get("memory_id") or args.get("id") or "").strip()
    if not memory_id:
        return {"status": "error", "error": "ID kandidat memori tidak boleh kosong."}
    return semantic_memory.resolve_memory_candidate(memory_id, accept=True, user_id=default_sender)


@register_tool("reject_memory_candidate")
def handle_reject_memory_candidate(args: dict[str, Any], default_sender: str) -> dict[str, Any]:
    memory_id = str(args.get("memory_id") or args.get("id") or "").strip()
    if not memory_id:
        return {"status": "error", "error": "ID kandidat memori tidak boleh kosong."}
    return semantic_memory.resolve_memory_candidate(memory_id, accept=False, user_id=default_sender)
