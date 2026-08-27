"""
pdf_engine.py — High-Performance PDF & Document Manipulation Engine.

Features:
  - Merge PDFs (native zero-margin or uniform A4 standard format)
  - Split / Slice / Reorder / Rotate PDF pages
  - Render PDF page to high-DPI PNG/JPG (instant WhatsApp photo preview)
  - Convert Images (JPG, PNG, WEBP) to PDF (fit_image zero-margin or A4)
  - Convert PDF to editable Word DOCX (via pdf2docx)
  - Convert Word DOCX to PDF (via LibreOffice headless)
  - Compress PDF (stream deflation, garbage collection, optimization)
"""

import io
import logging
import os
import shutil
import subprocess
import tempfile

import fitz  # PyMuPDF
from PIL import Image, ImageOps

log = logging.getLogger("helmis-pdf-engine")

# Standard Dimensions in Points (72 points = 1 inch)
A4_WIDTH = 595.32
A4_HEIGHT = 841.92
LETTER_WIDTH = 612.0
LETTER_HEIGHT = 792.0


def _parse_page_ranges(pages_str: str, total_pages: int) -> list[int]:
    """
    Parse a user page range string (1-indexed) into a list of 0-indexed page numbers.
    Supports: "1-3, 5, 8-10", "last", "odd", "even", "all".
    """
    cleaned = pages_str.strip().lower()
    if not cleaned or cleaned in ("all", "*"):
        return list(range(total_pages))

    if cleaned == "last":
        return [total_pages - 1] if total_pages > 0 else []

    if cleaned == "odd":
        return [i for i in range(total_pages) if (i + 1) % 2 != 0]

    if cleaned == "even":
        return [i for i in range(total_pages) if (i + 1) % 2 == 0]

    selected_pages: list[int] = []
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]

    for part in parts:
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start = int(bounds[0].strip())
                end = int(bounds[1].strip())
                step = 1 if start <= end else -1
                for p_num in range(start, end + step, step):
                    idx = p_num - 1 if p_num > 0 else total_pages + p_num
                    if 0 <= idx < total_pages:
                        selected_pages.append(idx)
            except ValueError:
                log.warning("Invalid range fragment: %s", part)
                continue
        else:
            try:
                p_num = int(part)
                idx = p_num - 1 if p_num > 0 else total_pages + p_num
                if 0 <= idx < total_pages:
                    selected_pages.append(idx)
            except ValueError:
                log.warning("Invalid page fragment: %s", part)
                continue

    return selected_pages


# ============================================================
# 1. Merge PDFs
# ============================================================


def merge_pdf_bytes(
    pdf_bytes_list: list[bytes],
    page_sizing: str = "original",
) -> bytes:
    """
    Merge multiple PDF files.
    - page_sizing="original": Preserves native aspect ratio and dimensions per page (zero outer white pixels).
    - page_sizing="a4": Normalizes all pages onto standard A4 canvas with proportional centering.
    """
    if not pdf_bytes_list:
        raise ValueError("Daftar PDF untuk digabungkan tidak boleh kosong.")

    dest_doc = fitz.open()

    for i, p_bytes in enumerate(pdf_bytes_list):
        if not p_bytes:
            continue
        try:
            src_doc = fitz.open(stream=p_bytes, filetype="pdf")
        except Exception as err:
            raise ValueError(f"Gagal membaca PDF urutan ke-{i+1}: {err}") from err

        if src_doc.is_encrypted:
            if not src_doc.authenticate(""):
                src_doc.close()
                dest_doc.close()
                raise ValueError(f"PDF urutan ke-{i+1} terenkripsi/ber-password.")

        if page_sizing.lower() in ("a4", "uniform_a4"):
            for page_idx in range(len(src_doc)):
                src_page = src_doc[page_idx]
                src_rect = src_page.rect
                target_w = A4_WIDTH
                target_h = A4_HEIGHT

                # Detect landscape
                if src_rect.width > src_rect.height:
                    target_w, target_h = A4_HEIGHT, A4_WIDTH

                dest_page = dest_doc.new_page(width=target_w, height=target_h)

                scale = min(target_w / src_rect.width, target_h / src_rect.height)
                fit_w = src_rect.width * scale
                fit_h = src_rect.height * scale
                offset_x = (target_w - fit_w) / 2.0
                offset_y = (target_h - fit_h) / 2.0

                dest_rect = fitz.Rect(offset_x, offset_y, offset_x + fit_w, offset_y + fit_h)
                dest_page.show_pdf_page(dest_rect, src_doc, page_idx)
        else:
            # Native / original sizing: insert directly without added borders
            dest_doc.insert_pdf(src_doc)

        src_doc.close()

    if len(dest_doc) == 0:
        dest_doc.close()
        raise ValueError("Hasil penggabungan PDF kosong (tidak ada halaman valid).")

    out_bytes = dest_doc.tobytes(garbage=4, deflate=True)
    dest_doc.close()
    return out_bytes


# ============================================================
# 2. Split / Slice / Rotate PDF
# ============================================================


def split_pdf_bytes(
    pdf_bytes: bytes,
    pages: str,
    rotate_deg: int = 0,
) -> bytes:
    """
    Extract specific pages or page ranges from a PDF, with optional rotation (90, 180, 270).
    """
    if not pdf_bytes:
        raise ValueError("File PDF kosong.")

    src_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if src_doc.is_encrypted and not src_doc.authenticate(""):
        src_doc.close()
        raise ValueError("File PDF terenkripsi/ber-password.")

    total_pages = len(src_doc)
    if total_pages == 0:
        src_doc.close()
        raise ValueError("File PDF tidak memiliki halaman.")

    selected_indices = _parse_page_ranges(pages, total_pages)
    if not selected_indices:
        src_doc.close()
        raise ValueError(f"Tidak ada halaman yang cocok dengan spesifikasi '{pages}' (Total: {total_pages} hal).")

    dest_doc = fitz.open()
    for idx in selected_indices:
        dest_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)

    # Apply rotation if specified
    if rotate_deg in (90, 180, 270):
        for p in dest_doc:
            p.set_rotation((p.rotation + rotate_deg) % 360)

    out_bytes = dest_doc.tobytes(garbage=4, deflate=True)
    src_doc.close()
    dest_doc.close()
    return out_bytes


# ============================================================
# 3. Render PDF Page to Image (PNG / JPEG)
# ============================================================


def render_pdf_page_bytes(
    pdf_bytes: bytes,
    page_number: int = 1,
    dpi: int = 150,
    fmt: str = "png",
) -> bytes:
    """
    Render a specific page of a PDF to an image byte stream (PNG or JPEG) for WhatsApp preview.
    """
    if not pdf_bytes:
        raise ValueError("File PDF kosong.")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.is_encrypted and not doc.authenticate(""):
        doc.close()
        raise ValueError("File PDF terenkripsi/ber-password.")

    total = len(doc)
    if total == 0:
        doc.close()
        raise ValueError("File PDF tidak memiliki halaman.")

    idx = page_number - 1 if page_number > 0 else total + page_number
    if not (0 <= idx < total):
        doc.close()
        raise ValueError(f"Halaman {page_number} tidak ditemukan (Total: {total} halaman).")

    page = doc[idx]
    # alpha=False ensures solid white background instead of transparent checkerboard
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    img_fmt = "jpeg" if fmt.lower() in ("jpg", "jpeg") else "png"
    out_bytes = pix.tobytes(img_fmt)
    doc.close()
    return out_bytes


# ============================================================
# 4. Images to Multi-Page PDF
# ============================================================


def images_to_pdf_bytes(
    image_bytes_list: list[bytes],
    page_sizing: str = "fit_image",
) -> bytes:
    """
    Convert a list of image byte streams (JPG, PNG, WEBP, BMP) into a multi-page PDF.
    - page_sizing="fit_image": Canvas matches exact pixel dimensions (0 outer margin pixels).
    - page_sizing="a4": Scales and centers images onto uniform A4 pages.
    """
    if not image_bytes_list:
        raise ValueError("Daftar gambar tidak boleh kosong.")

    dest_doc = fitz.open()

    for idx, img_b in enumerate(image_bytes_list):
        if not img_b:
            continue
        try:
            pil_img = Image.open(io.BytesIO(img_b))
            # Auto-handle EXIF camera rotation
            pil_img = ImageOps.exif_transpose(pil_img) or pil_img

            # Convert RGBA / Palette / Grayscale to RGB for clean rendering
            if pil_img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", pil_img.size, (255, 255, 255))
                if pil_img.mode == "RGBA":
                    bg.paste(pil_img, mask=pil_img.split()[3])
                else:
                    bg.paste(pil_img.convert("RGB"))
                pil_img = bg
            elif pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")

            # Save normalized image to clean JPEG buffer
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=95)
            clean_jpg_bytes = buf.getvalue()

            img_w, img_h = pil_img.size

            if page_sizing.lower() in ("a4", "uniform_a4"):
                target_w = A4_WIDTH
                target_h = A4_HEIGHT
                if img_w > img_h:
                    target_w, target_h = A4_HEIGHT, A4_WIDTH

                page = dest_doc.new_page(width=target_w, height=target_h)
                scale = min(target_w / img_w, target_h / img_h)
                fit_w = img_w * scale
                fit_h = img_h * scale
                offset_x = (target_w - fit_w) / 2.0
                offset_y = (target_h - fit_h) / 2.0
                dest_rect = fitz.Rect(offset_x, offset_y, offset_x + fit_w, offset_y + fit_h)
                page.insert_image(dest_rect, stream=clean_jpg_bytes)
            else:
                # 1:1 fit_image: page size = exact image pixel dimensions with ZERO margins
                page = dest_doc.new_page(width=img_w, height=img_h)
                page.insert_image(page.rect, stream=clean_jpg_bytes)

        except Exception as err:
            raise ValueError(f"Gagal memproses gambar urutan ke-{idx+1}: {err}") from err

    if len(dest_doc) == 0:
        dest_doc.close()
        raise ValueError("Gagal membuat PDF: tidak ada gambar valid.")

    out_bytes = dest_doc.tobytes(garbage=4, deflate=True)
    dest_doc.close()
    return out_bytes


# ============================================================
# 5. PDF to Editable Word DOCX
# ============================================================


def pdf_to_docx_bytes(pdf_bytes: bytes) -> bytes:
    """
    Convert PDF bytes to editable Microsoft Word .docx bytes using pdf2docx.
    """
    if not pdf_bytes:
        raise ValueError("File PDF kosong.")

    from pdf2docx import Converter

    with tempfile.TemporaryDirectory(prefix="helmis_pdf2docx_") as tmp_dir:
        pdf_path = os.path.join(tmp_dir, "input.pdf")
        docx_path = os.path.join(tmp_dir, "output.docx")

        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        try:
            cv = Converter(pdf_path)
            cv.convert(docx_path)
            cv.close()
        except Exception as err:
            raise ValueError(f"Gagal mengonversi PDF ke DOCX: {err}") from err

        if not os.path.exists(docx_path):
            raise ValueError("Konversi gagal menghasilkan file DOCX.")

        with open(docx_path, "rb") as f:
            docx_bytes = f.read()

        return docx_bytes


# ============================================================
# 6. Word DOCX to PDF (via LibreOffice Headless)
# ============================================================


def docx_to_pdf_bytes(docx_bytes: bytes) -> bytes:
    """
    Convert Word .docx bytes to PDF using LibreOffice headless.
    """
    if not docx_bytes:
        raise ValueError("File DOCX kosong.")

    libreoffice_bin = shutil.which("libreoffice") or shutil.which("soffice")
    if not libreoffice_bin:
        raise RuntimeError("LibreOffice tidak terpasang di sistem untuk konversi DOCX ke PDF.")

    with tempfile.TemporaryDirectory(prefix="helmis_docx2pdf_") as tmp_dir:
        docx_path = os.path.join(tmp_dir, "input.docx")
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)

        cmd = [
            libreoffice_bin,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            tmp_dir,
            docx_path,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, timeout=60)
            if res.returncode != 0:
                err_msg = res.stderr.decode("utf-8", errors="replace")
                raise ValueError(f"LibreOffice conversion error: {err_msg}")
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Konversi DOCX ke PDF melebihi batas waktu (timeout).") from exc

        expected_pdf = os.path.join(tmp_dir, "input.pdf")
        if not os.path.exists(expected_pdf):
            raise ValueError("Gagal mengonversi DOCX ke PDF: file output tidak ditemukan.")

        with open(expected_pdf, "rb") as f:
            pdf_bytes = f.read()

        return pdf_bytes


# ============================================================
# 7. Compress PDF
# ============================================================


def compress_pdf_bytes(pdf_bytes: bytes, downsample_dpi: int = 150) -> bytes:
    """
    Compress a PDF document by deflating streams, removing unused objects, and consolidating resources.
    """
    if not pdf_bytes:
        raise ValueError("File PDF kosong.")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.is_encrypted and not doc.authenticate(""):
        doc.close()
        raise ValueError("File PDF terenkripsi/ber-password.")

    compressed = doc.tobytes(garbage=4, deflate=True, clean=True, linear=False)
    doc.close()
    return compressed
