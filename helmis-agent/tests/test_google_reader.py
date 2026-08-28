"""
test_google_reader.py — Comprehensive Unit Tests for Google Workspace & URL Reader Engine.
"""

import io
import os
import time
from unittest.mock import patch

import pytest
import pytest_httpx
import pypdf

from src.memory.sandbox import (
    cleanup_sandbox,
    get_from_sandbox,
    get_sandbox_dir,
    is_safe_sandbox_path,
    save_to_sandbox,
)
from src.tools.google_reader import (
    format_csv_to_markdown_table,
    is_ssrf_safe_url,
    normalize_url,
    parse_google_url_type,
    read_url_content,
)
from src.tools.registry import execute_tool_call


def create_test_pdf_bytes(text_per_page: list[str]) -> bytes:
    """Helper to generate a minimal valid in-memory PDF with given text per page."""
    writer = pypdf.PdfWriter()
    for text in text_per_page:
        # Create a blank page and attach text if possible, or add blank page
        writer.add_blank_page(width=200, height=200)
    
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


# ---------------------------------------------------------------------------
# 1. URL Normalization & Type Parsing
# ---------------------------------------------------------------------------

def test_normalize_url():
    assert normalize_url("docs.google.com/document/d/123/edit") == "https://docs.google.com/document/d/123/edit"
    assert normalize_url("https://example.com/page") == "https://example.com/page"
    assert normalize_url("drive.google.com/file/d/abc/view") == "https://drive.google.com/file/d/abc/view"


def test_parse_google_sheets_url_types():
    # Standard sheet URL
    t1, doc_id1, p1 = parse_google_url_type("https://docs.google.com/spreadsheets/d/1I1vGay0Comufvsa4ClB7KHgfZjBGd4Xt/edit")
    assert t1 == "sheets"
    assert doc_id1 == "1I1vGay0Comufvsa4ClB7KHgfZjBGd4Xt"
    assert p1.get("gid") is None

    # Sheet with query param gid
    t2, doc_id2, p2 = parse_google_url_type("https://docs.google.com/spreadsheets/d/18TyocDN1TeVmb_32MSnqqcTT4EgV9YVH-kFoTZSUgYE/edit?gid=142240181")
    assert t2 == "sheets"
    assert doc_id2 == "18TyocDN1TeVmb_32MSnqqcTT4EgV9YVH-kFoTZSUgYE"
    assert p2.get("gid") == "142240181"

    # Sheet with hash fragment #gid=
    t3, doc_id3, p3 = parse_google_url_type("https://docs.google.com/spreadsheets/d/18TyocDN1TeVmb_32MSnqqcTT4EgV9YVH-kFoTZSUgYE/edit#gid=998877")
    assert t3 == "sheets"
    assert doc_id3 == "18TyocDN1TeVmb_32MSnqqcTT4EgV9YVH-kFoTZSUgYE"
    assert p3.get("gid") == "998877"


def test_parse_google_docs_and_slides():
    # Google Doc
    t_doc, doc_id_doc, _ = parse_google_url_type("https://docs.google.com/document/d/1v7MBHFsJ_7mfHfGEAbkiOwFIzUgV2Bw6TW6tjHTJgOI/edit")
    assert t_doc == "docs"
    assert doc_id_doc == "1v7MBHFsJ_7mfHfGEAbkiOwFIzUgV2Bw6TW6tjHTJgOI"

    # Google Slides
    t_slide, doc_id_slide, _ = parse_google_url_type("https://docs.google.com/presentation/d/1XYZ987654321/edit")
    assert t_slide == "slides"
    assert doc_id_slide == "1XYZ987654321"

    # Google Drive File
    t_drive, doc_id_drive, _ = parse_google_url_type("https://drive.google.com/file/d/1AbC_file_id/view?usp=sharing")
    assert t_drive == "drive_file"
    assert doc_id_drive == "1AbC_file_id"


# ---------------------------------------------------------------------------
# 2. SSRF Protection
# ---------------------------------------------------------------------------

def test_ssrf_protection():
    assert is_ssrf_safe_url("http://127.0.0.1:8765/sse") is False
    assert is_ssrf_safe_url("http://localhost:3000") is False
    assert is_ssrf_safe_url("http://169.254.169.254/latest/meta-data") is False
    assert is_ssrf_safe_url("http://10.0.0.5/api") is False
    assert is_ssrf_safe_url("http://192.168.1.1/admin") is False
    assert is_ssrf_safe_url("https://docs.google.com/spreadsheets/d/123/edit") is True
    assert is_ssrf_safe_url("https://en.wikipedia.org/wiki/Economics") is True


# ---------------------------------------------------------------------------
# 3. CSV to Markdown Table Formatter
# ---------------------------------------------------------------------------

def test_format_csv_to_markdown_table():
    csv_sample = (
        "No,NIM,Nama,Kelompok,Topik\n"
        "1,142240181,BUNGA SALSABILA AGUSTINA,Kelompok 4,Building Relationships\n"
        "2,142240195,SAFIRA ADINATA KUSUMADEWI,Kelompok 4,Building Relationships\n"
        "3,142240203,GINANDA KARISMA IMANI PUTRI,Kelompok 4,Building Relationships\n"
        "4,142240220,JUBEL ALESSANDRO DAMANIK,Kelompok 5,Conflict Resolution\n"
    )
    # General table formatting
    table = format_csv_to_markdown_table(csv_sample)
    assert "| No | NIM | Nama | Kelompok | Topik |" in table
    assert "BUNGA SALSABILA AGUSTINA" in table

    # Filtered by query
    filtered = format_csv_to_markdown_table(csv_sample, query="JUBEL")
    assert "JUBEL ALESSANDRO DAMANIK" in filtered
    assert "BUNGA SALSABILA" not in filtered


# ---------------------------------------------------------------------------
# 4. Sandbox Lifecycle & Operations
# ---------------------------------------------------------------------------

def test_sandbox_storage_and_cleanup(tmp_path):
    with patch("src.memory.sandbox.DATA_DIR", str(tmp_path)):
        rec = save_to_sandbox(
            data=b"hello temporary sandbox",
            filename="test_snapshot.csv",
            metadata={"source_url": "https://example.com/test"},
            ttl_seconds=10,
        )
        assert rec["filename"].startswith("test_snapshot_sbx_")
        assert os.path.exists(rec["filepath"])

        # Retrieve file
        res = get_from_sandbox(rec["file_id"])
        assert res is not None
        meta, data = res
        assert data == b"hello temporary sandbox"
        assert meta["metadata"]["source_url"] == "https://example.com/test"

        # Path traversal guard
        assert is_safe_sandbox_path(rec["filepath"]) is True
        assert is_safe_sandbox_path(os.path.join(str(tmp_path), "../evil.txt")) is False

        # Cleanup expired
        time.sleep(0.01)
        cleaned = cleanup_sandbox(max_age_seconds=0)
        assert cleaned >= 1


# ---------------------------------------------------------------------------
# 5. Full Engine read_url_content (Google Sheets, Docs, Private Docs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_google_sheets_public(httpx_mock: pytest_httpx.HTTPXMock, tmp_path):
    with patch("src.memory.sandbox.DATA_DIR", str(tmp_path)):
        url = "https://docs.google.com/spreadsheets/d/18TyocDN1TeVmb_32MSnqqcTT4EgV9YVH-kFoTZSUgYE/edit?gid=142240181"
        expected_export_url = "https://docs.google.com/spreadsheets/d/18TyocDN1TeVmb_32MSnqqcTT4EgV9YVH-kFoTZSUgYE/export?format=csv&gid=142240181"

        mock_csv = (
            "NIM,Nama,Kelompok\n"
            "142240181,Bunga Salsabila,Kelompok 4\n"
            "142240195,Safira Adinata,Kelompok 4\n"
        )
        httpx_mock.add_response(url=expected_export_url, text=mock_csv, status_code=200)

        res = await read_url_content(url=url)
        assert res["status"] == "success"
        assert res["source_type"] == "google_sheets"
        assert res["is_snapshot"] is True
        assert "Bunga Salsabila" in res["content"]
        assert "Kelompok 4" in res["content"]
        assert "WIB" in res["snapshot_at"]


@pytest.mark.asyncio
async def test_read_google_docs_public(httpx_mock: pytest_httpx.HTTPXMock, tmp_path):
    with patch("src.memory.sandbox.DATA_DIR", str(tmp_path)):
        url = "https://docs.google.com/document/d/1v7MBHFsJ_7mfHfGEAbkiOwFIzUgV2Bw6TW6tjHTJgOI/edit"
        expected_export_url = "https://docs.google.com/document/d/1v7MBHFsJ_7mfHfGEAbkiOwFIzUgV2Bw6TW6tjHTJgOI/export?format=txt"

        mock_txt = "Silabus Pengantar Ekonomi Syariah 2026.\nTopik 1: Konsep Dasar.\nTopik 2: Riba dan Gharar."
        httpx_mock.add_response(url=expected_export_url, text=mock_txt, status_code=200)

        res = await read_url_content(url=url)
        assert res["status"] == "success"
        assert res["source_type"] == "google_docs"
        assert "Silabus Pengantar Ekonomi Syariah" in res["content"]


@pytest.mark.asyncio
async def test_read_google_doc_private_redirect(httpx_mock: pytest_httpx.HTTPXMock, tmp_path):
    with patch("src.memory.sandbox.DATA_DIR", str(tmp_path)):
        url = "https://docs.google.com/document/d/private_doc_123/edit"
        expected_export_url = "https://docs.google.com/document/d/private_doc_123/export?format=txt"

        login_html = "<html><head><title>Sign in - Google Accounts</title></head><body>ServiceLogin</body></html>"
        httpx_mock.add_response(
            url=expected_export_url,
            text=login_html,
            status_code=200,
        )

        res = await read_url_content(url=url)
        assert res["status"] == "permission_denied"
        assert "privat" in res["message"].lower()
        assert "Anyone with the link" in res["message"]


@pytest.mark.asyncio
async def test_execute_tool_call_read_url(httpx_mock: pytest_httpx.HTTPXMock, tmp_path):
    with patch("src.memory.sandbox.DATA_DIR", str(tmp_path)):
        url = "https://docs.google.com/document/d/test_doc_abc/edit"
        expected_export_url = "https://docs.google.com/document/d/test_doc_abc/export?format=txt"

        httpx_mock.add_response(url=expected_export_url, text="Tugas kelompok Soft Skill 1.", status_code=200)

        res = await execute_tool_call("read_url", {"url": url}, default_sender="Gilang")
        assert res["status"] == "success"
        assert "Tugas kelompok Soft Skill 1" in res["content"]
        assert "_model_directive" in res


def test_format_tool_chips_google_types():
    from src.agent.guardrails import format_tool_chips

    chips = format_tool_chips([
        {"name": "read_url", "result": {"status": "success", "source_type": "google_sheets"}},
        {"name": "read_url", "result": {"status": "success", "source_type": "google_docs"}},
        {"name": "read_url", "result": {"status": "success", "source_type": "google_slides"}},
        {"name": "read_url", "result": {"status": "success", "source_type": "generic_web"}},
    ])
    assert chips == "↳ `read_google_sheet`, `read_google_doc`, `read_google_slides`, `read_web_page`"
