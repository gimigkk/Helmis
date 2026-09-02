"""
test_guardrails_fidelity.py — Unit Tests for Two-Step Anti-Hallucination & State Mutation Guardrails.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.guardrails import (
    detect_unexecuted_mutation_claims,
    format_tool_chips,
    strip_hallucinated_tool_chips,
    verify_action_fidelity,
)
from src.agent.loop import run_agentic_react_loop

# ---------------------------------------------------------------------------
# 1. Detection of Unexecuted Mutation Claims
# ---------------------------------------------------------------------------

def test_detect_unexecuted_complete_task():
    text = "Sip, tugas Nge-chat anak murid buat les sudah Helmis tandai selesai ya."
    # Without tool execution -> Violation
    assert detect_unexecuted_mutation_claims(text, []) == "complete_task"
    # With failed tool execution -> Violation
    assert detect_unexecuted_mutation_claims(text, [{"name": "complete_task", "result": {"status": "error"}}]) == "complete_task"
    # With successful tool execution -> Valid
    assert detect_unexecuted_mutation_claims(text, [{"name": "complete_task", "result": {"status": "success"}}]) is None


def test_detect_unexecuted_delete_action():
    t_note = "Catatan resep masakan sudah berhasil dihapus dari sistem."
    assert detect_unexecuted_mutation_claims(t_note, []) == "delete_action"
    assert detect_unexecuted_mutation_claims(t_note, [{"name": "delete_note", "result": {"status": "success"}}]) is None

    t_task = "Tugas belanja bulanan sudah Helmis hapus ya."
    assert detect_unexecuted_mutation_claims(t_task, []) == "delete_action"
    assert detect_unexecuted_mutation_claims(t_task, [{"name": "delete_task", "result": {"status": "success"}}]) is None


def test_detect_unexecuted_add_task():
    text = "Pengingat bayar kosan sudah Helmis catat untuk tanggal 1 September ya."
    assert detect_unexecuted_mutation_claims(text, []) == "add_task"
    assert detect_unexecuted_mutation_claims(text, [{"name": "add_task", "result": {"status": "success"}}]) is None


def test_detect_unexecuted_save_vault():
    text = "Link presentasinya sudah Helmis simpan ke Brankas Dokumen ya."
    assert detect_unexecuted_mutation_claims(text, []) == "save_vault_file"
    assert detect_unexecuted_mutation_claims(text, [{"name": "save_vault_file", "result": {"status": "success"}}]) is None


def test_detect_unexecuted_send_action():
    text = "Dokumen kurikulum sudah berhasil dikirimkan ke chat Bunga ya."
    assert detect_unexecuted_mutation_claims(text, []) == "send_action"
    assert detect_unexecuted_mutation_claims(text, [{"name": "send_whatsapp_message", "result": {"status": "success"}}]) is None


def test_detect_allowed_general_queries():
    # Regular conversation
    assert detect_unexecuted_mutation_claims("Halo Gilang, ada yang bisa Helmis bantu hari ini?", []) is None
    # Task listing query response
    assert detect_unexecuted_mutation_claims(
        "Berikut adalah daftar tugas yang sudah selesai:\n1. Tugas A\n2. Tugas B",
        [{"name": "list_tasks", "result": {"status": "success"}}],
    ) is None


# ---------------------------------------------------------------------------
# 2. verify_action_fidelity Guardrail Overrides
# ---------------------------------------------------------------------------

def test_verify_action_fidelity_blocks_unexecuted_mutation():
    text = "Sip, tugas Nge-chat anak murid buat les sudah Helmis tandai selesai ya."
    # If passed to verify_action_fidelity with empty tools, text is blocked and replaced
    res = verify_action_fidelity(text, [])
    assert "belum berhasil diproses" in res
    assert "Nge-chat anak murid" not in res


def test_verify_action_fidelity_passes_verified_mutation():
    text = "Sip, tugas Nge-chat anak murid buat les sudah Helmis tandai selesai ya."
    tools = [{"name": "complete_task", "result": {"status": "success"}}]
    res = verify_action_fidelity(text, tools)
    assert "Sip, tugas Nge-chat anak murid" in res
    assert "↳" not in res  # chips are opt-in (default off)


def test_strip_hallucinated_tool_chips():
    hallucinated = "Tugas sudah selesai.\n\n↳ `complete_task`, `delete_task`"
    cleaned = strip_hallucinated_tool_chips(hallucinated)
    assert cleaned == "Tugas sudah selesai."


# ---------------------------------------------------------------------------
# 3. Agent Loop Turn Interception Simulation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_intercepts_unexecuted_mutation_claim():
    """
    Simulate LLM generating hallucinated completion on Step 1, being intercepted,
    and then emitting functionCall on Step 2.
    """
    mock_client = AsyncMock()
    mock_client.get_messages = AsyncMock(return_value=[])

    # Step 1: LLM hallucinates text without functionCall
    resp_step1 = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Sip, tugas nge-chat murid sudah Helmis tandai selesai ya."}
                    ]
                }
            }
        ]
    }

    # Step 2: After being intercepted, LLM emits functionCall
    resp_step2 = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "complete_task",
                                "args": {"title": "nge-chat murid"},
                            }
                        }
                    ]
                }
            }
        ]
    }

    # Step 3: LLM finalizes response with verified outcome
    resp_step3 = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Beres, tugas nge-chat murid sudah berhasil ditandai selesai."}
                    ]
                }
            }
        ]
    }

    call_count = 0

    async def mock_post(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        if call_count == 1:
            mock_resp.json = lambda: resp_step1
        elif call_count == 2:
            mock_resp.json = lambda: resp_step2
        else:
            mock_resp.json = lambda: resp_step3
        return mock_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post), \
         patch("src.agent.loop.get_next_gemini_key", return_value="dummy_key_123"), \
         patch("src.tools.tasks.complete_task", return_value={"status": "success", "task_id": "1", "title": "nge-chat murid"}):

        final_reply = await run_agentic_react_loop(
            client=mock_client,
            chat_id="120363411261097957@g.us",
            sender_name="Bunga",
            message_text="tugas nge-chat murid udah selesai",
            max_steps=5,
        )

        # Ensure loop intercepted step 1 and completed across multiple steps
        assert call_count >= 2
        assert final_reply is not None
        assert "berhasil ditandai selesai" in final_reply
        assert "complete_task" not in final_reply  # chips are opt-in (default off)


def test_sanitize_latex_for_whatsapp():
    from src.agent.guardrails import sanitize_latex_for_whatsapp

    raw = "Penentuan dominant term seperti $O(n^3)$, $O(n^{1.5})$, $O(n^2)$, $O(n \\log_2 n)$, $F(n)$, dan $O(n)$."
    cleaned = sanitize_latex_for_whatsapp(raw)
    assert "$" not in cleaned
    assert "O(n³)" in cleaned
    assert "O(n¹.⁵)" in cleaned
    assert "O(n²)" in cleaned
    assert "O(n log₂ n)" in cleaned
    assert "F(n)" in cleaned
    assert "O(n)" in cleaned


def test_format_tool_chips_with_extraction_mode_badges():
    tools = [
        {
            "name": "read_url",
            "result": {
                "status": "success",
                "source_type": "google_sheets",
                "extraction_mode": "pubhtml_parser",
            },
        },
        {
            "name": "read_vault_file",
            "result": {
                "status": "success",
                "content_type": "image",
                "extraction_mode": "vision_ocr",
            },
        },
        {
            "name": "read_vault_file",
            "result": {
                "status": "success",
                "content_type": "pdf",
                "extraction_mode": "digital_text",
            },
        },
    ]
    chips = format_tool_chips(tools)
    assert chips == "↳ `read_google_sheet:pubhtml_parser`, `read_vault_file:vision_ocr`, `read_vault_file:digital_text`"
