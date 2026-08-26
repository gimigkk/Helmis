"""
test_vault.py — Unit and integration tests for Document Vault, File Catalog, Directory Operations, and ReAct Tooling.
"""

import os
import shutil
import tempfile
from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.memory.vault import (
    create_vault_directory,
    delete_vault_directory,
    delete_vault_files,
    get_vault_file_by_id,
    get_vault_file_by_name,
    init_vault_structure,
    is_safe_vault_path,
    list_vault_directories,
    list_vault_files,
    move_vault_files,
    read_vault_file,
    sanitize_filename,
    save_file_to_vault,
    search_vault,
)
from src.tools import execute_tool_call
from src.whatsapp.client import WahaClient
from src.whatsapp.webhook import create_webhook_app


@pytest.fixture(autouse=True)
def isolated_vault_environment(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Provide an isolated temporary directory for vault files and catalog during tests."""
    temp_dir = tempfile.mkdtemp(prefix="helmis_vault_test_")
    vault_dir = os.path.join(temp_dir, "vault")
    catalog_file = os.path.join(temp_dir, "file_catalog.json")

    monkeypatch.setattr("src.memory.vault.DATA_DIR", temp_dir)
    monkeypatch.setattr("src.memory.vault.VAULT_DIR", vault_dir)
    monkeypatch.setattr("src.memory.vault.CATALOG_FILE", catalog_file)

    init_vault_structure()

    yield temp_dir

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_sanitize_filename_and_path_safety() -> None:
    """Verify filename sanitization and strict path traversal protection."""
    assert sanitize_filename("scan:bpjs#1.pdf") == "scan_bpjs_1.pdf"
    assert sanitize_filename("my cv (final) 2026.pdf") == "my_cv_final_2026.pdf"
    assert sanitize_filename("../../../etc/passwd") == "passwd"

    # Path safety
    from src.memory.vault import _get_vault_dir
    safe_path = os.path.join(_get_vault_dir(), "health", "gilang", "bpjs.pdf")
    unsafe_path = os.path.join(_get_vault_dir(), "..", "passwords.txt")
    assert is_safe_vault_path(safe_path) is True
    assert is_safe_vault_path(unsafe_path) is False


def test_save_file_to_vault_and_deduplication() -> None:
    """Verify saving file, catalog indexing, SHA-256 deduplication, and auto-versioning."""
    sample_bytes = b"%PDF-1.4 sample bpjs document bytes"
    rec1 = save_file_to_vault(
        data=sample_bytes,
        filename="scan_bpjs_gilang.pdf",
        owner="Gilang",
        category="health",
        description="Kartu BPJS Kesehatan Gilang",
        tags=["bpjs", "kesehatan"],
        ocr_summary="NO BPJS: 000123456789",
    )

    assert rec1["filename"] == "scan_bpjs_gilang.pdf"
    assert rec1["category"] == "health"
    assert rec1["owner"] == "Gilang"
    assert rec1["size_bytes"] == len(sample_bytes)
    assert "health/gilang/scan_bpjs_gilang.pdf" in rec1["relative_path"]

    # Identical content returns existing record (deduplication)
    rec2 = save_file_to_vault(
        data=sample_bytes,
        filename="scan_bpjs_copy.pdf",
        owner="Gilang",
        category="health",
    )
    assert rec2["id"] == rec1["id"]

    # Different content with same filename triggers versioning
    different_bytes = b"%PDF-1.4 updated new bpjs scan bytes"
    rec3 = save_file_to_vault(
        data=different_bytes,
        filename="scan_bpjs_gilang.pdf",
        owner="Gilang",
        category="health",
    )
    assert rec3["filename"] == "scan_bpjs_gilang_v2.pdf"
    assert rec3["id"] != rec1["id"]


def test_search_and_list_vault_files() -> None:
    """Verify keyword, tag, owner, and category searches."""
    save_file_to_vault(
        data=b"ktp gilang data",
        filename="ktp_gilang.jpg",
        owner="Gilang",
        category="id_cards",
        tags=["ktp", "identitas"],
    )
    save_file_to_vault(
        data=b"ktp bunga data",
        filename="ktp_bunga.jpg",
        owner="Bunga",
        category="id_cards",
        tags=["ktp", "identitas"],
    )
    save_file_to_vault(
        data=b"garuda ticket bali",
        filename="tiket_garuda_bali.pdf",
        owner="Both",
        category="travel",
        tags=["flight", "tiket", "bali"],
    )

    # Search by keyword
    results = search_vault("tiket")
    assert len(results) == 1
    assert results[0]["filename"] == "tiket_garuda_bali.pdf"

    # Search with owner filter
    bunga_results = search_vault("ktp", owner="Bunga")
    assert len(bunga_results) == 1
    assert bunga_results[0]["filename"] == "ktp_bunga.jpg"

    # List by category
    id_cards = list_vault_files(category="id_cards")
    assert len(id_cards) == 2


def test_get_and_delete_vault_file() -> None:
    """Verify file retrieval by id/name and clean single & bulk deletion."""
    rec = save_file_to_vault(
        data=b"cv document bytes",
        filename="cv_gilang_2026.pdf",
        owner="Gilang",
        category="documents",
    )
    save_file_to_vault(
        data=b"draft 1 bytes",
        filename="temp_draft_1.pdf",
        owner="Gilang",
        category="documents",
    )
    save_file_to_vault(
        data=b"draft 2 bytes",
        filename="temp_draft_2.pdf",
        owner="Gilang",
        category="documents",
    )

    res_by_id = get_vault_file_by_id(rec["id"])
    assert res_by_id is not None
    assert res_by_id[1] == b"cv document bytes"

    res_by_name = get_vault_file_by_name("cv_gilang_2026.pdf")
    assert res_by_name is not None
    assert res_by_name[0]["id"] == rec["id"]

    # Single delete
    deleted = delete_vault_files(rec["id"])
    assert len(deleted) == 1
    assert get_vault_file_by_id(rec["id"]) is None

    # Bulk delete by query
    bulk_deleted = delete_vault_files("temp_draft")
    assert len(bulk_deleted) == 2
    assert get_vault_file_by_name("temp_draft_1.pdf") is None


def test_move_vault_file_and_bulk_move() -> None:
    """Verify moving single files and bulk matching moves."""
    save_file_to_vault(data=b"kriyamic nda", filename="kriyamic_nda.pdf", category="documents")
    save_file_to_vault(data=b"kriyamic invoice", filename="kriyamic_invoice.pdf", category="documents")
    save_file_to_vault(data=b"personal note", filename="note.txt", category="documents")

    # Bulk move files containing 'kriyamic' to projects/kriyamic
    create_vault_directory("projects/kriyamic")
    moved = move_vault_files(
        target="kriyamic",
        destination_dir="projects/kriyamic",
        new_category="projects",
    )

    assert len(moved) == 2
    assert all("projects/kriyamic" in m["relative_path"] for m in moved)

    # Note remains in documents
    note_rec = get_vault_file_by_name("note.txt")
    assert note_rec is not None
    assert "documents" in note_rec[0]["relative_path"]


def test_directory_operations_and_safety() -> None:
    """Verify directory creation, listing, and non-empty deletion safety."""
    created = create_vault_directory("projects/secret_lab")
    assert created == "projects/secret_lab"

    dirs = list_vault_directories()
    assert "projects/secret_lab" in dirs

    # Non-empty deletion check
    save_file_to_vault(
        data=b"lab data",
        filename="experiment.pdf",
        subfolder="projects/secret_lab",
    )

    # Non-recursive should fail
    success, msg = delete_vault_directory("projects/secret_lab", recursive=False)
    assert success is False
    assert "tidak kosong" in msg

    # Recursive succeeds and unregisters file
    success_rec, msg_rec = delete_vault_directory("projects/secret_lab", recursive=True)
    assert success_rec is True
    assert "berhasil dihapus" in msg_rec
    assert get_vault_file_by_name("experiment.pdf") is None


@pytest.mark.asyncio
async def test_react_tool_execution_for_vault() -> None:
    """Verify ReAct tool handlers through execute_tool_call."""
    mock_client = AsyncMock(spec=WahaClient)

    # 1. save_vault_file tool
    save_res = await execute_tool_call(
        func_name="save_vault_file",
        args={
            "filename": "scan_bpjs_gilang.pdf",
            "category": "health",
            "owner": "Gilang",
            "description": "Kartu BPJS Kesehatan",
            "tags": ["bpjs", "kesehatan"],
            "ocr_summary": "NO: 123456",
        },
        default_sender="Gilang",
        client=mock_client,
    )
    assert save_res["status"] == "success"
    file_id = save_res["file"]["id"]

    # 2. search_vault_files tool
    search_res = await execute_tool_call(
        func_name="search_vault_files",
        args={"query": "bpjs"},
        default_sender="Gilang",
        client=mock_client,
    )
    assert search_res["status"] == "success"
    assert search_res["count"] == 1

    # 3. send_vault_file tool
    send_res = await execute_tool_call(
        func_name="send_vault_file",
        args={
            "file_id_or_name": file_id,
            "recipient": "Gilang",
            "caption": "Ini file BPJS kamu.",
        },
        default_sender="Gilang",
        client=mock_client,
    )
    assert send_res["status"] == "success"
    assert mock_client.send_media.called

    # 4. move_vault_files tool (polymorphic)
    move_res = await execute_tool_call(
        func_name="move_vault_files",
        args={
            "target": file_id,
            "destination_directory": "health/shared",
        },
        default_sender="Gilang",
        client=mock_client,
    )
    assert move_res["status"] == "success"

    # 5. delete_vault_files tool (polymorphic)
    del_res = await execute_tool_call(
        func_name="delete_vault_files",
        args={"target": file_id},
        default_sender="Gilang",
        client=mock_client,
    )
    assert del_res["status"] == "success"


@pytest.mark.asyncio
async def test_vault_http_streaming_endpoint() -> None:
    """Verify the Starlette GET /vault/file/{file_id} streaming endpoint."""
    rec = save_file_to_vault(
        data=b"%PDF-1.5 test document stream",
        filename="stream_doc.pdf",
        category="documents",
        owner="Gilang",
    )

    mock_client = AsyncMock(spec=WahaClient)
    app = create_webhook_app(mock_client)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/vault/file/{rec['id']}")
        assert resp.status_code == 200
        assert resp.content == b"%PDF-1.5 test document stream"
        assert resp.headers["content-type"] == "application/pdf"

        # Resolve by filename
        resp_by_name = await ac.get("/vault/file/stream_doc.pdf")
        assert resp_by_name.status_code == 200
        assert resp_by_name.content == b"%PDF-1.5 test document stream"

        resp_404 = await ac.get("/vault/file/non_existent_id")
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_save_vault_file_with_media_data_binary() -> None:
    """Verify tool saves real binary bytes when media_data is present."""
    import base64

    pdf_bytes = b"%PDF-1.4 real binary pdf content"
    b64_str = base64.b64encode(pdf_bytes).decode("ascii")

    res = await execute_tool_call(
        func_name="save_vault_file",
        args={"filename": "incoming_scan", "category": "health", "owner": "Gilang"},
        default_sender="Gilang",
        media_data={"mimeType": "application/pdf", "data": b64_str},
    )
    assert res["status"] == "success"
    file_record = res["file"]
    assert file_record["filename"] == "incoming_scan.pdf"
    assert file_record["size_bytes"] == len(pdf_bytes)

    # Read back from vault
    _, retrieved_bytes = get_vault_file_by_id(file_record["id"])  # type: ignore
    assert retrieved_bytes == pdf_bytes


def test_root_category_protection_and_move_collision() -> None:
    """Verify default categories are protected and move collisions auto-version."""
    # 1. Protected root category deletion
    success, msg = delete_vault_directory("health", recursive=True)
    assert success is False
    assert "dilindungi" in msg

    # 2. Move collision versioning
    save_file_to_vault(data=b"first copy", filename="ticket.pdf", category="travel", subfolder="travel/gilang")
    r2 = save_file_to_vault(data=b"second copy", filename="ticket.pdf", category="travel", subfolder="travel/bunga")
    moved = move_vault_files(target=r2["id"], destination_dir="travel/gilang")
    assert len(moved) == 1
    assert moved[0]["filename"] == "ticket_v2.pdf"
    assert "travel/gilang/ticket_v2.pdf" in moved[0]["relative_path"]


def test_read_vault_file_plain_text_and_image() -> None:
    """Verify read_vault_file extracts text from plain text files and metadata from images."""
    # 1. Text file
    memo_text = "# Project Roadmap\n\n1. Setup server\n2. Deploy WhatsApp bot"
    rec_text = save_file_to_vault(
        data=memo_text.encode("utf-8"),
        filename="roadmap.md",
        category="projects",
    )

    read_res = read_vault_file(rec_text["id"])
    assert read_res["status"] == "success"
    assert read_res["content_type"] == "text"
    assert "Setup server" in read_res["content"]

    # 2. Image file
    save_file_to_vault(
        data=b"\xff\xd8\xff\xe0 fake jpeg bytes",
        filename="struk_makan.jpg",
        category="receipts",
        description="Struk makan malam di Restoran Padang",
        ocr_summary="Total: Rp 125.000, 2 Ayam Pop, 1 Es Teh",
    )

    read_img = read_vault_file("struk_makan.jpg")
    assert read_img["status"] == "success"
    assert read_img["content_type"] == "image"
    assert "Total: Rp 125.000" in read_img["content"]


@pytest.mark.asyncio
async def test_react_read_vault_file_tool() -> None:
    """Verify ReAct tool execution for read_vault_file."""
    rec = save_file_to_vault(
        data=b"Client requirements: Freelance web development project details",
        filename="brief.txt",
        category="projects",
    )

    res = await execute_tool_call(
        func_name="read_vault_file",
        args={"file_id_or_name": rec["id"]},
        default_sender="Gilang",
    )
    assert res["status"] == "success"
    assert "Freelance web development" in res["content"]


def test_vault_catalog_corruption_auto_repair() -> None:
    """Verify corrupted JSON catalog automatically self-heals."""
    import src.memory.vault as vault
    # Overwrite catalog file with invalid truncated JSON
    with open(vault._get_catalog_file(), "w") as f:
        f.write("{ invalid json corrupted ")

    # Load should catch error and return fresh structure
    cat = vault._load_catalog()
    assert "files" in cat
    assert isinstance(cat["files"], list)


def test_vault_directory_guard_edge_cases() -> None:
    """Verify edge cases for directory deletion: non-existent, root, outside vault."""
    # 1. Non-existent directory
    success, msg = delete_vault_directory("non_existent_dir")
    assert success is False
    assert "tidak ditemukan" in msg

    # 2. Root directory
    success, msg = delete_vault_directory("")
    assert success is False

    # 3. Read non-existent file
    res = read_vault_file("definitely_not_a_real_file.pdf")
    assert res["status"] == "error"
    assert "tidak ditemukan" in res["error"]


def test_vault_search_and_list_filter_matrix() -> None:
    """Verify search and list filters across tags, directory prefixes, and owner combinations."""
    save_file_to_vault(
        data=b"tag test data",
        filename="tax_2025.pdf",
        category="receipts",
        tags=["pajak", "spt", "tahunan"],
        owner="Gilang",
    )

    # Search by tag
    res_tag = search_vault(query="pajak", category="receipts", owner="Gilang")
    assert len(res_tag) >= 1

    # Search with non-matching filter
    res_none = search_vault(query="pajak", category="health")
    assert len(res_none) == 0

    # List with directory filter
    res_dir = list_vault_files(directory="receipts/gilang")
    assert len(res_dir) >= 1


def test_vault_preserves_original_filename_and_searches_by_original_name() -> None:
    """Verify that original filenames with spaces and special characters are preserved and searchable."""
    orig_name = "P2_Gilang Muhamad Widiagung_M0403241117_02.pdf"
    rec = save_file_to_vault(
        data=b"%PDF-1.4 analgor assignment content",
        filename="P2_Gilang Muhamad Widiagung_M0403241117_02.pdf",
        category="documents",
        owner="Gilang",
        original_filename=orig_name,
    )

    assert rec["original_filename"] == orig_name
    assert rec["filename"] == "P2_Gilang_Muhamad_Widiagung_M0403241117_02.pdf"

    # Search by student ID / NIM
    res_nim = search_vault("M0403241117")
    assert len(res_nim) >= 1
    assert res_nim[0]["original_filename"] == orig_name

    # Search by student full name with space
    res_name = search_vault("Gilang Muhamad Widiagung")
    assert len(res_name) >= 1
    assert res_name[0]["original_filename"] == orig_name

    # Search by assignment prefix
    res_p2 = search_vault("P2 Gilang")
    assert len(res_p2) >= 1


@pytest.mark.asyncio
async def test_save_and_send_vault_file_tools_use_original_filename() -> None:
    """Verify handle_save_vault_file tool and handle_send_vault_file tool use original_filename."""
    import base64
    from unittest.mock import AsyncMock

    pdf_bytes = b"%PDF-1.5 test raw bytes"
    b64_pdf = base64.b64encode(pdf_bytes).decode("ascii")
    orig_doc_name = "Tugas 1 (Analisis Algoritma) [FINAL].pdf"

    save_res = await execute_tool_call(
        func_name="save_vault_file",
        args={
            "category": "documents",
            "owner": "Gilang",
            "description": "Tugas kuliah analgor",
        },
        default_sender="Gilang",
        media_data={
            "mimeType": "application/pdf",
            "data": b64_pdf,
            "filename": orig_doc_name,
        },
    )

    assert save_res["status"] == "success"
    file_rec = save_res["file"]
    assert file_rec["original_filename"] == orig_doc_name
    assert orig_doc_name in save_res["message"]

    # Test send_vault_file preserves original_filename when sending to WhatsApp client
    mock_client = AsyncMock()
    send_res = await execute_tool_call(
        func_name="send_vault_file",
        args={"file_id_or_name": file_rec["id"], "recipient": "current"},
        default_sender="Gilang",
        client=mock_client,
    )

    assert send_res["status"] == "success"
    assert send_res["filename"] == orig_doc_name
    mock_client.send_media.assert_called_once()
    _, kwargs = mock_client.send_media.call_args
    assert kwargs["filename"] == orig_doc_name

