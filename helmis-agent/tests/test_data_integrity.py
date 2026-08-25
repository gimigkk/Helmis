"""
test_data_integrity.py — Rigorous Byte-for-Byte Binary Integrity and Anti-Corruption Test Suite.
Verifies that PDFs, JPEGs, PNGs, ZIPs, and documents maintain 100.000% SHA-256 fidelity
across Ingestion, Storage, Cataloging, ReAct Tool Execution, HTTP Streaming, and WAHA Dispatch.
"""

import base64
import hashlib
import secrets
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.client import WahaClient
from src.tools.registry import execute_tool_call
from src.vault import (
    get_vault_file_by_id,
    get_vault_file_by_name,
    init_vault_structure,
    save_file_to_vault,
)
from src.webhook import create_webhook_app


@pytest.fixture(autouse=True)
def clean_vault_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate vault directory and catalog for each test."""
    vault_data_dir = tmp_path / "data"
    vault_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("src.vault.DATA_DIR", str(vault_data_dir))
    monkeypatch.setattr("src.vault.VAULT_DIR", str(vault_data_dir / "vault"))
    monkeypatch.setattr("src.vault.CATALOG_FILE", str(vault_data_dir / "file_catalog.json"))
    init_vault_structure()


def generate_realistic_pdf(size_kb: int = 270) -> bytes:
    """Generate a valid binary PDF byte stream with exact target size."""
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    footer = b"\nxref\n0 3\n0000000000 65535 f \ntrailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n%%EOF\n"
    payload_size = (size_kb * 1024) - len(header) - len(footer)
    assert payload_size > 0
    # Include null bytes and arbitrary binary sequence
    random_payload = b"stream\n" + secrets.token_bytes(payload_size - 17) + b"\nendstream"
    return header + random_payload + footer


def generate_jpeg_bytes() -> bytes:
    """Generate a realistic JPEG image binary with valid SOI, APP0, and EOI markers."""
    soi = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
    body = secrets.token_bytes(1024 * 50)  # 50 KB
    eoi = b"\xff\xd9"
    return soi + body + eoi


def generate_zip_bytes() -> bytes:
    """Generate a realistic ZIP archive binary with valid PK header."""
    header = b"PK\x03\x04\x14\x00\x00\x00\x08\x00"
    body = secrets.token_bytes(1024 * 30)  # 30 KB
    return header + body


def test_pdf_binary_byte_for_byte_preservation() -> None:
    """Verify that a 270 KB binary PDF is saved with 100% SHA-256 byte-for-byte fidelity."""
    original_pdf = generate_realistic_pdf(size_kb=270)
    expected_hash = hashlib.sha256(original_pdf).hexdigest()
    expected_len = len(original_pdf)

    record = save_file_to_vault(
        data=original_pdf,
        filename="Pilihan_Program_Bimbel_ELERA_EDUCATION.pdf",
        owner="Gilang",
        category="projects",
        subfolder="projects/freelance_webdev",
        description="Brosur bimbel Elera Education",
    )

    assert record["size_bytes"] == expected_len
    assert record["content_hash"] == expected_hash
    assert record["mime_type"] == "application/pdf"

    # Read back from vault storage
    res = get_vault_file_by_id(record["id"])
    assert res is not None
    rec, stored_bytes = res

    assert len(stored_bytes) == expected_len
    assert hashlib.sha256(stored_bytes).hexdigest() == expected_hash
    assert stored_bytes == original_pdf  # Direct byte equality check
    assert stored_bytes.startswith(b"%PDF-1.7")
    assert stored_bytes.endswith(b"%%EOF\n")


def test_jpeg_and_zip_binary_fidelity() -> None:
    """Verify images and archives retain exact binary markers without string conversion."""
    jpeg_bytes = generate_jpeg_bytes()
    jpeg_hash = hashlib.sha256(jpeg_bytes).hexdigest()

    rec_img = save_file_to_vault(
        data=jpeg_bytes,
        filename="scan_ktp_gilang.jpg",
        owner="Gilang",
        category="id_cards",
    )
    assert rec_img["mime_type"] == "image/jpeg"
    _, stored_jpeg = get_vault_file_by_id(rec_img["id"])  # type: ignore
    assert stored_jpeg == jpeg_bytes
    assert hashlib.sha256(stored_jpeg).hexdigest() == jpeg_hash

    zip_bytes = generate_zip_bytes()
    zip_hash = hashlib.sha256(zip_bytes).hexdigest()
    rec_zip = save_file_to_vault(
        data=zip_bytes,
        filename="backup_project.zip",
        owner="Gilang",
        category="documents",
    )
    _, stored_zip = get_vault_file_by_id(rec_zip["id"])  # type: ignore
    assert stored_zip == zip_bytes
    assert hashlib.sha256(stored_zip).hexdigest() == zip_hash


@pytest.mark.asyncio
async def test_react_tool_ignores_ocr_text_when_media_data_present() -> None:
    """
    ANTI-CORRUPTION TEST: Even if Gemini provides an OCR transcript in `content_text`,
    `save_vault_file` MUST use the real binary bytes from `media_data`.
    """
    original_pdf = generate_realistic_pdf(size_kb=150)
    b64_pdf = base64.b64encode(original_pdf).decode("ascii")
    expected_hash = hashlib.sha256(original_pdf).hexdigest()

    ocr_fake_text = "BIMBINGAN BELAJAR ELERA EDUCATION\nBiaya les 50rb"

    # Execute tool as Gemini would when receiving a document with OCR text
    tool_res = await execute_tool_call(
        func_name="save_vault_file",
        args={
            "filename": "brosur_elera.pdf",
            "category": "projects",
            "subfolder": "projects/freelance_webdev",
            "content_text": ocr_fake_text,  # Model mistakenly provides plain text
            "ocr_summary": "Summary of prices",
        },
        default_sender="Gilang",
        media_data={"mimeType": "application/pdf", "data": b64_pdf},
    )

    assert tool_res["status"] == "success"
    file_record = tool_res["file"]

    # Verify saved file is the 150KB PDF, NOT the 50-byte text
    assert file_record["size_bytes"] == len(original_pdf)
    assert file_record["content_hash"] == expected_hash

    res = get_vault_file_by_name("brosur_elera.pdf")
    assert res is not None
    _, stored_bytes = res
    assert stored_bytes == original_pdf
    assert hashlib.sha256(stored_bytes).hexdigest() == expected_hash


@pytest.mark.asyncio
async def test_waha_send_media_receives_unaltered_data_uri_and_filename() -> None:
    """Verify that dispatching via send_vault_file provides uncorrupted Data URI and correct filename."""
    original_pdf = generate_realistic_pdf(size_kb=80)
    rec = save_file_to_vault(
        data=original_pdf,
        filename="brosur_elera_education.pdf",
        owner="Gilang",
        category="projects",
    )

    mock_client = AsyncMock(spec=WahaClient)

    send_res = await execute_tool_call(
        func_name="send_vault_file",
        args={"file_id_or_name": rec["id"], "recipient": "Gilang"},
        default_sender="Gilang",
        client=mock_client,
    )

    assert send_res["status"] == "success"
    assert mock_client.send_media.called

    call_kwargs = mock_client.send_media.call_args.kwargs
    assert call_kwargs["filename"] == "brosur_elera_education.pdf"
    assert call_kwargs["mimetype"] == "application/pdf"

    # Decode Data URI sent to WAHA and verify byte-for-byte equality
    media_url = call_kwargs["media_url"]
    assert media_url.startswith("data:application/pdf;base64,")
    encoded_b64 = media_url.split(",", 1)[1]
    decoded_bytes = base64.b64decode(encoded_b64)

    assert decoded_bytes == original_pdf
    assert hashlib.sha256(decoded_bytes).hexdigest() == hashlib.sha256(original_pdf).hexdigest()


@pytest.mark.asyncio
async def test_http_streaming_endpoint_integrity() -> None:
    """Verify HTTP streaming endpoint does not mutate binary bytes (CRLF, null bytes, headers)."""
    original_pdf = generate_realistic_pdf(size_kb=200)
    rec = save_file_to_vault(
        data=original_pdf,
        filename="tax_report_2026.pdf",
        owner="Gilang",
        category="documents",
    )

    mock_client = AsyncMock(spec=WahaClient)
    app = create_webhook_app(mock_client)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/vault/file/{rec['id']}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert int(resp.headers["content-length"]) == len(original_pdf)
        assert resp.content == original_pdf
        assert hashlib.sha256(resp.content).hexdigest() == hashlib.sha256(original_pdf).hexdigest()
