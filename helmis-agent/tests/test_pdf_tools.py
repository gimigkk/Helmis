"""
test_pdf_tools.py — Unit and Integration Tests for PDF Engine, ReAct Tooling, and Document Conversions.
"""

import io
import os
import shutil
import tempfile
from collections.abc import Generator

import pymupdf as fitz
import pytest
from PIL import Image

from src.memory.pdf_engine import (
    A4_HEIGHT,
    A4_WIDTH,
    compress_pdf_bytes,
    images_to_pdf_bytes,
    merge_pdf_bytes,
    pdf_to_docx_bytes,
    render_pdf_page_bytes,
    split_pdf_bytes,
)
from src.memory.vault import (
    get_vault_file_by_name,
    init_vault_structure,
    save_file_to_vault,
)
from src.tools import execute_tool_call


@pytest.fixture(autouse=True)
def isolated_vault_environment(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Provide an isolated temporary directory for vault storage during tests."""
    temp_dir = tempfile.mkdtemp(prefix="helmis_pdf_test_")
    vault_dir = os.path.join(temp_dir, "vault")
    catalog_file = os.path.join(temp_dir, "file_catalog.json")

    monkeypatch.setattr("src.memory.vault.DATA_DIR", temp_dir)
    monkeypatch.setattr("src.memory.vault.VAULT_DIR", vault_dir)
    monkeypatch.setattr("src.memory.vault.CATALOG_FILE", catalog_file)

    init_vault_structure()

    yield temp_dir

    shutil.rmtree(temp_dir, ignore_errors=True)


def _create_sample_pdf(pages_text: list[str], width: float = 595.32, height: float = 841.92) -> bytes:
    """Helper to create a valid multi-page PDF with given text and dimensions."""
    doc = fitz.open()
    for txt in pages_text:
        page = doc.new_page(width=width, height=height)
        page.insert_text((50, 100), txt, fontsize=14)
    b = doc.tobytes()
    doc.close()
    return b


def _create_sample_image(width: int = 400, height: int = 300, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """Helper to create a sample JPEG image."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ============================================================
# Core Engine Tests
# ============================================================


def test_merge_pdfs_native_sizing() -> None:
    """Verify merge preserves native aspect ratio & dimensions with 0 added margins."""
    pdf1 = _create_sample_pdf(["Doc 1 Page 1", "Doc 1 Page 2"], width=400, height=600)
    pdf2 = _create_sample_pdf(["Doc 2 Page 1"], width=800, height=1200)

    merged = merge_pdf_bytes([pdf1, pdf2], page_sizing="original")
    doc = fitz.open(stream=merged, filetype="pdf")

    assert len(doc) == 3
    # Page 1 and 2 keep exact 400x600 dimensions
    assert round(doc[0].rect.width) == 400
    assert round(doc[0].rect.height) == 600
    # Page 3 keeps exact 800x1200 dimensions
    assert round(doc[2].rect.width) == 800
    assert round(doc[2].rect.height) == 1200
    doc.close()


def test_merge_pdfs_uniform_a4() -> None:
    """Verify merge standardizes disparate pages onto uniform A4 format."""
    pdf1 = _create_sample_pdf(["Page 1"], width=400, height=300)  # Landscape
    pdf2 = _create_sample_pdf(["Page 2"], width=300, height=500)  # Portrait

    merged = merge_pdf_bytes([pdf1, pdf2], page_sizing="a4")
    doc = fitz.open(stream=merged, filetype="pdf")

    assert len(doc) == 2
    # Page 1 was landscape -> A4 landscape (841.92 x 595.32)
    assert round(doc[0].rect.width) == round(A4_HEIGHT)
    assert round(doc[0].rect.height) == round(A4_WIDTH)
    # Page 2 was portrait -> A4 portrait (595.32 x 841.92)
    assert round(doc[1].rect.width) == round(A4_WIDTH)
    assert round(doc[1].rect.height) == round(A4_HEIGHT)
    doc.close()


def test_split_pdf_ranges_and_rotation() -> None:
    """Verify page range parsing, slicing, and rotation."""
    pdf = _create_sample_pdf(["Hal 1", "Hal 2", "Hal 3", "Hal 4", "Hal 5"])

    # 1. Complex range: "1-2, 4"
    split1 = split_pdf_bytes(pdf, pages="1-2, 4", rotate_deg=0)
    doc1 = fitz.open(stream=split1, filetype="pdf")
    assert len(doc1) == 3
    assert "Hal 1" in doc1[0].get_text()
    assert "Hal 2" in doc1[1].get_text()
    assert "Hal 4" in doc1[2].get_text()
    doc1.close()

    # 2. Keywords "last" with 90 deg rotation
    split2 = split_pdf_bytes(pdf, pages="last", rotate_deg=90)
    doc2 = fitz.open(stream=split2, filetype="pdf")
    assert len(doc2) == 1
    assert "Hal 5" in doc2[0].get_text()
    assert doc2[0].rotation == 90
    doc2.close()

    # 3. Keyword "odd"
    split3 = split_pdf_bytes(pdf, pages="odd")
    doc3 = fitz.open(stream=split3, filetype="pdf")
    assert len(doc3) == 3  # Pages 1, 3, 5
    assert "Hal 1" in doc3[0].get_text()
    assert "Hal 3" in doc3[1].get_text()
    assert "Hal 5" in doc3[2].get_text()
    doc3.close()


def test_render_pdf_page_image() -> None:
    """Verify rendering a PDF page to a sharp PNG image."""
    pdf = _create_sample_pdf(["Important Invoice Details: Total Rp 500.000"])
    png_bytes = render_pdf_page_bytes(pdf, page_number=1, dpi=150, fmt="png")

    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    img = Image.open(io.BytesIO(png_bytes))
    assert img.size[0] > 0
    assert img.size[1] > 0


def test_images_to_pdf_fit_image_and_a4() -> None:
    """Verify compiling photos into a multi-page PDF with 0 margins."""
    img1 = _create_sample_image(width=640, height=480)
    img2 = _create_sample_image(width=1080, height=1920)

    # 1. fit_image mode (zero outer white margin, exact dimensions)
    pdf_fit = images_to_pdf_bytes([img1, img2], page_sizing="fit_image")
    doc_fit = fitz.open(stream=pdf_fit, filetype="pdf")
    assert len(doc_fit) == 2
    assert round(doc_fit[0].rect.width) == 640
    assert round(doc_fit[0].rect.height) == 480
    assert round(doc_fit[1].rect.width) == 1080
    assert round(doc_fit[1].rect.height) == 1920
    doc_fit.close()

    # 2. A4 mode (uniform standard sizing)
    pdf_a4 = images_to_pdf_bytes([img1, img2], page_sizing="a4")
    doc_a4 = fitz.open(stream=pdf_a4, filetype="pdf")
    assert len(doc_a4) == 2
    assert round(doc_a4[0].rect.width) == round(A4_HEIGHT)  # Landscape image -> landscape A4
    assert round(doc_a4[1].rect.width) == round(A4_WIDTH)   # Portrait image -> portrait A4
    doc_a4.close()


def test_pdf_to_docx_conversion() -> None:
    """Verify converting a sample PDF to Word .docx format with preserved spaces."""
    import docx

    pdf = _create_sample_pdf(["Helmis Project Roadmap", "Item 1: Deploy Bot", "Item 2: Run Tests"])
    docx_bytes = pdf_to_docx_bytes(pdf)

    # Word .docx files are PK zip archives
    assert docx_bytes.startswith(b"PK\x03\x04")

    # Verify extracted paragraphs preserve distinct words and spaces
    doc = docx.Document(io.BytesIO(docx_bytes))
    full_text = " ".join(p.text for p in doc.paragraphs)
    assert "Helmis Project Roadmap" in full_text
    assert "Deploy Bot" in full_text


def test_pdf_to_docx_ilovepdf_api_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify iLovePDF Cloud API integration when credentials are set."""
    from unittest.mock import MagicMock

    import httpx

    monkeypatch.setenv("ILOVEPDF_PUBLIC_KEY", "project_public_test_key")
    monkeypatch.setenv("ILOVEPDF_SECRET_KEY", "secret_test_key")

    mock_docx_bytes = b"PK\x03\x04\x14\x00\x00\x00\x08\x00mocked_ilovepdf_word_docx"

    # Mock httpx.Client calls

    class MockHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "auth" in str(url):
                resp.json.return_value = {"token": "fake_jwt_token"}
            elif "upload" in str(url):
                resp.json.return_value = {"server_filename": "uploaded_server_file.pdf"}
            elif "process" in str(url):
                resp.json.return_value = {"status": "TaskSuccess"}
            return resp

        def get(self, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "start" in str(url):
                resp.json.return_value = {"server": "api2.ilovepdf.com", "task": "task_abc123"}
            elif "download" in str(url):
                resp.content = mock_docx_bytes
            return resp

    monkeypatch.setattr(httpx, "Client", MockHttpxClient)

    pdf = _create_sample_pdf(["Test iLovePDF API"])
    res = pdf_to_docx_bytes(pdf, filename="test.pdf")
    assert res == mock_docx_bytes


def test_compress_pdf() -> None:
    """Verify stream deflation and optimization of PDF."""
    pdf = _create_sample_pdf(["Uncompressed document text stream repeated " * 50])
    compressed = compress_pdf_bytes(pdf)
    assert len(compressed) > 0
    # Verify resulting document is valid and readable
    doc = fitz.open(stream=compressed, filetype="pdf")
    assert len(doc) == 1
    assert "Uncompressed document" in doc[0].get_text()
    doc.close()


# ============================================================
# ReAct Tool Execution Tests
# ============================================================


@pytest.mark.asyncio
async def test_react_process_pdf_merge() -> None:
    """Verify ReAct tool execution for action='merge'."""
    pdf1 = _create_sample_pdf(["Bab 1: Pendahuluan"])
    pdf2 = _create_sample_pdf(["Bab 2: Pembahasan"])

    save_file_to_vault(data=pdf1, filename="bab1.pdf", category="documents", owner="Gilang")
    save_file_to_vault(data=pdf2, filename="bab2.pdf", category="documents", owner="Gilang")

    res = await execute_tool_call(
        func_name="process_pdf",
        args={
            "action": "merge",
            "target_files": ["bab1.pdf", "bab2.pdf"],
            "page_sizing": "original",
            "output_filename": "tugas_lengkap.pdf",
        },
        default_sender="Gilang",
    )

    assert res["status"] == "success"
    assert res["file"]["filename"] == "tugas_lengkap.pdf"
    assert res["input_count"] == 2

    # Verify merged file exists in vault
    vault_rec = get_vault_file_by_name("tugas_lengkap.pdf")
    assert vault_rec is not None
    _, saved_bytes = vault_rec
    doc = fitz.open(stream=saved_bytes, filetype="pdf")
    assert len(doc) == 2
    doc.close()


@pytest.mark.asyncio
async def test_react_process_pdf_split() -> None:
    """Verify ReAct tool execution for action='split'."""
    pdf = _create_sample_pdf(["Hal 1", "Hal 2", "Hal 3", "Hal 4", "Hal 5"])
    save_file_to_vault(data=pdf, filename="modul.pdf", category="documents", owner="Gilang")

    res = await execute_tool_call(
        func_name="process_pdf",
        args={
            "action": "split",
            "target_files": ["modul.pdf"],
            "pages": "2-3",
            "output_filename": "modul_bab2.pdf",
        },
        default_sender="Gilang",
    )

    assert res["status"] == "success"
    assert res["file"]["filename"] == "modul_bab2.pdf"

    vault_rec = get_vault_file_by_name("modul_bab2.pdf")
    assert vault_rec is not None
    _, saved_bytes = vault_rec
    doc = fitz.open(stream=saved_bytes, filetype="pdf")
    assert len(doc) == 2
    assert "Hal 2" in doc[0].get_text()
    assert "Hal 3" in doc[1].get_text()
    doc.close()


@pytest.mark.asyncio
async def test_react_process_pdf_render_image() -> None:
    """Verify ReAct tool execution for action='render_image'."""
    pdf = _create_sample_pdf(["Page 1", "Page 2: Confidential Financial Data"])
    save_file_to_vault(data=pdf, filename="keuangan.pdf", category="documents", owner="Gilang")

    res = await execute_tool_call(
        func_name="process_pdf",
        args={
            "action": "render_image",
            "target_files": ["keuangan.pdf"],
            "page_number": 2,
            "format": "png",
            "output_filename": "keuangan_hal2.png",
        },
        default_sender="Gilang",
    )

    assert res["status"] == "success"
    assert res["file"]["filename"] == "keuangan_hal2.png"
    assert res["page_number"] == 2

    vault_rec = get_vault_file_by_name("keuangan_hal2.png")
    assert vault_rec is not None
    _, saved_bytes = vault_rec
    assert saved_bytes.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_react_process_pdf_images_to_pdf() -> None:
    """Verify ReAct tool execution for action='images_to_pdf'."""
    img1 = _create_sample_image(300, 200)
    img2 = _create_sample_image(300, 200)

    save_file_to_vault(data=img1, filename="nota1.jpg", category="receipts", owner="Gilang")
    save_file_to_vault(data=img2, filename="nota2.jpg", category="receipts", owner="Gilang")

    res = await execute_tool_call(
        func_name="process_pdf",
        args={
            "action": "images_to_pdf",
            "target_files": ["nota1.jpg", "nota2.jpg"],
            "output_filename": "rekap_nota.pdf",
        },
        default_sender="Gilang",
    )

    assert res["status"] == "success"
    assert res["file"]["filename"] == "rekap_nota.pdf"

    vault_rec = get_vault_file_by_name("rekap_nota.pdf")
    assert vault_rec is not None
    _, saved_bytes = vault_rec
    doc = fitz.open(stream=saved_bytes, filetype="pdf")
    assert len(doc) == 2
    doc.close()


@pytest.mark.asyncio
async def test_react_process_pdf_to_docx() -> None:
    """Verify ReAct tool execution for action='to_docx'."""
    pdf = _create_sample_pdf(["Perjanjian Kerjasama 2026"])
    save_file_to_vault(data=pdf, filename="kontrak.pdf", category="documents", owner="Gilang")

    res = await execute_tool_call(
        func_name="process_pdf",
        args={
            "action": "to_docx",
            "target_files": ["kontrak.pdf"],
            "output_filename": "kontrak.docx",
        },
        default_sender="Gilang",
    )

    assert res["status"] == "success"
    assert res["file"]["filename"] == "kontrak.docx"

    vault_rec = get_vault_file_by_name("kontrak.docx")
    assert vault_rec is not None
    _, saved_bytes = vault_rec
    assert saved_bytes.startswith(b"PK\x03\x04")


@pytest.mark.asyncio
async def test_react_process_pdf_compress() -> None:
    """Verify ReAct tool execution for action='compress'."""
    pdf = _create_sample_pdf(["Portfolio Gilang - Software Engineer"])
    save_file_to_vault(data=pdf, filename="portfolio.pdf", category="documents", owner="Gilang")

    res = await execute_tool_call(
        func_name="process_pdf",
        args={
            "action": "compress",
            "target_files": ["portfolio.pdf"],
            "output_filename": "portfolio_opt.pdf",
        },
        default_sender="Gilang",
    )

    assert res["status"] == "success"
    assert res["file"]["filename"] == "portfolio_opt.pdf"
    assert "saved_percent" in res


@pytest.mark.asyncio
async def test_react_process_pdf_error_handling() -> None:
    """Verify handling of missing files, invalid actions, and empty parameters."""
    # 1. Missing action
    res1 = await execute_tool_call(
        func_name="process_pdf",
        args={"target_files": ["any.pdf"]},
        default_sender="Gilang",
    )
    assert res1["status"] == "error"
    assert "action" in res1["error"]

    # 2. Missing target file
    res2 = await execute_tool_call(
        func_name="process_pdf",
        args={"action": "merge", "target_files": ["non_existent_1.pdf", "non_existent_2.pdf"]},
        default_sender="Gilang",
    )
    assert res2["status"] == "error"
    assert "tidak ditemukan" in res2["error"]

    # 3. Invalid action
    res3 = await execute_tool_call(
        func_name="process_pdf",
        args={"action": "unknown_op", "target_files": ["any.pdf"]},
        default_sender="Gilang",
    )
    assert res3["status"] == "error"
    assert "tidak dikenal" in res3["error"]
