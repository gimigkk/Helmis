"""
pdf_ops.py — ReAct Tool Handler for Unified PDF & Document Manipulation.
"""

import logging
import os
from typing import Any

from ..memory.pdf_engine import (
    compress_pdf_bytes,
    docx_to_pdf_bytes,
    images_to_pdf_bytes,
    merge_pdf_bytes,
    pdf_to_docx_bytes,
    render_pdf_page_bytes,
    split_pdf_bytes,
)
from ..memory.store import log_activity
from ..memory.vault import (
    get_vault_file_by_id,
    get_vault_file_by_name,
    save_file_to_vault,
)
from ..whatsapp.client import WahaClient
from .registry import register_tool

log = logging.getLogger("helmis-tools-pdf")


def _resolve_vault_file(target: str) -> tuple[dict[str, Any], bytes] | None:
    """Resolve file record and bytes from vault by ID or filename."""
    t = target.strip()
    if not t:
        return None
    res = get_vault_file_by_id(t)
    if not res:
        res = get_vault_file_by_name(t)
    return res


@register_tool("process_pdf")
async def handle_process_pdf(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    """
    Unified polymorphic tool for PDF operations:
    - merge: Combine PDFs (page_sizing="original" or "a4")
    - split: Extract/slice page ranges ("1-3, 5", "last") with optional rotation
    - render_image: Render page to PNG/JPG (instant WhatsApp photo preview)
    - images_to_pdf: Photos to PDF (page_sizing="fit_image" or "a4")
    - to_docx: Convert PDF to editable Word .docx
    - from_docx: Convert Word .docx to PDF
    - compress: Optimize PDF file size & deflate streams
    """
    action = str(args.get("action", "")).strip().lower()
    if not action:
        return {
            "status": "error",
            "error": "Parameter 'action' wajib diisi (merge, split, render_image, images_to_pdf, to_docx, from_docx, compress).",
        }

    raw_targets = args.get("target_files") or args.get("files") or args.get("file_names") or []
    if isinstance(raw_targets, str):
        target_list = [t.strip() for t in raw_targets.split(",") if t.strip()]
    elif isinstance(raw_targets, list):
        target_list = [str(t).strip() for t in raw_targets if str(t).strip()]
    else:
        target_list = []

    # Single file fallback argument (e.g. target_file="...")
    single_target = str(args.get("target_file") or args.get("file_id_or_name") or "").strip()
    if single_target and single_target not in target_list:
        target_list.insert(0, single_target)

    if not target_list:
        return {"status": "error", "error": "Daftar file 'target_files' tidak boleh kosong."}

    owner = str(args.get("owner", default_sender)).strip()
    output_filename = str(args.get("output_filename", "")).strip()

    try:
        # ============================================================
        # 1. MERGE
        # ============================================================
        if action == "merge":
            pdf_bytes_list: list[bytes] = []
            resolved_names: list[str] = []
            for t in target_list:
                res = _resolve_vault_file(t)
                if not res:
                    return {"status": "error", "error": f"File '{t}' tidak ditemukan di brankas dokumen."}
                rec, b = res
                pdf_bytes_list.append(b)
                resolved_names.append(rec.get("original_filename") or rec["filename"])

            page_sizing = str(args.get("page_sizing", "original")).strip()
            merged_bytes = merge_pdf_bytes(pdf_bytes_list, page_sizing=page_sizing)

            if not output_filename:
                base_first = os.path.splitext(resolved_names[0])[0]
                output_filename = f"{base_first}_merged.pdf"
            elif not output_filename.lower().endswith(".pdf"):
                output_filename = f"{output_filename}.pdf"

            record = save_file_to_vault(
                data=merged_bytes,
                filename=output_filename,
                owner=owner,
                category="documents",
                description=f"Merged PDF from {len(resolved_names)} files: {', '.join(resolved_names)}",
                tags=["merged", "pdf"],
            )
            log_activity(f"Merged {len(resolved_names)} PDFs into '{output_filename}'")
            return {
                "status": "success",
                "action": "merge",
                "file": record,
                "input_count": len(resolved_names),
                "message": f"Berhasil menggabungkan {len(resolved_names)} file PDF menjadi *{record['filename']}* ({len(merged_bytes)} bytes).",
            }

        # ============================================================
        # 2. SPLIT / SLICE / ROTATE
        # ============================================================
        elif action == "split":
            target = target_list[0]
            res = _resolve_vault_file(target)
            if not res:
                return {"status": "error", "error": f"File '{target}' tidak ditemukan di brankas dokumen."}
            rec, b = res
            orig_name = rec.get("original_filename") or rec["filename"]

            pages = str(args.get("pages") or args.get("page_range") or "1").strip()
            rotate_deg = int(args.get("rotate_deg") or 0)

            split_bytes = split_pdf_bytes(b, pages=pages, rotate_deg=rotate_deg)

            if not output_filename:
                base_name = os.path.splitext(orig_name)[0]
                clean_pages_slug = pages.replace(" ", "").replace(",", "_")
                output_filename = f"{base_name}_hal_{clean_pages_slug}.pdf"
            elif not output_filename.lower().endswith(".pdf"):
                output_filename = f"{output_filename}.pdf"

            record = save_file_to_vault(
                data=split_bytes,
                filename=output_filename,
                owner=owner,
                category="documents",
                description=f"Extracted pages '{pages}' from {orig_name}",
                tags=["split", "pdf", "extracted"],
            )
            log_activity(f"Extracted pages '{pages}' from '{orig_name}' into '{output_filename}'")
            return {
                "status": "success",
                "action": "split",
                "file": record,
                "pages": pages,
                "message": f"Berhasil mengekstrak halaman *{pages}* dari file *{orig_name}* menjadi *{record['filename']}*.",
            }

        # ============================================================
        # 3. RENDER PAGE TO IMAGE (PNG/JPG)
        # ============================================================
        elif action in ("render_image", "extract_page_image", "page_to_image"):
            target = target_list[0]
            res = _resolve_vault_file(target)
            if not res:
                return {"status": "error", "error": f"File '{target}' tidak ditemukan di brankas dokumen."}
            rec, b = res
            orig_name = rec.get("original_filename") or rec["filename"]

            page_number = int(args.get("page_number") or args.get("page") or 1)
            dpi = int(args.get("dpi") or 150)
            img_format = str(args.get("format") or "png").strip().lower()
            ext = "jpg" if img_format in ("jpg", "jpeg") else "png"

            img_bytes = render_pdf_page_bytes(b, page_number=page_number, dpi=dpi, fmt=img_format)

            if not output_filename:
                base_name = os.path.splitext(orig_name)[0]
                output_filename = f"{base_name}_hal_{page_number}.{ext}"
            elif not output_filename.lower().endswith(f".{ext}"):
                output_filename = f"{output_filename}.{ext}"

            record = save_file_to_vault(
                data=img_bytes,
                filename=output_filename,
                owner=owner,
                category="media",
                description=f"Rendered image of page {page_number} from {orig_name}",
                tags=["image", "pdf_render", "photo"],
            )
            log_activity(f"Rendered page {page_number} of '{orig_name}' to image '{output_filename}'")
            return {
                "status": "success",
                "action": "render_image",
                "file": record,
                "page_number": page_number,
                "message": f"Berhasil merender halaman *{page_number}* dari file *{orig_name}* menjadi gambar *{record['filename']}*.",
            }

        # ============================================================
        # 4. IMAGES TO MULTI-PAGE PDF
        # ============================================================
        elif action in ("images_to_pdf", "photos_to_pdf", "img_to_pdf"):
            img_bytes_list: list[bytes] = []
            resolved_names: list[str] = []
            for t in target_list:
                res = _resolve_vault_file(t)
                if not res:
                    return {"status": "error", "error": f"File gambar '{t}' tidak ditemukan di brankas dokumen."}
                rec, b = res
                img_bytes_list.append(b)
                resolved_names.append(rec.get("original_filename") or rec["filename"])

            page_sizing = str(args.get("page_sizing", "fit_image")).strip()
            pdf_bytes = images_to_pdf_bytes(img_bytes_list, page_sizing=page_sizing)

            if not output_filename:
                base_first = os.path.splitext(resolved_names[0])[0]
                output_filename = f"{base_first}_compiled.pdf"
            elif not output_filename.lower().endswith(".pdf"):
                output_filename = f"{output_filename}.pdf"

            record = save_file_to_vault(
                data=pdf_bytes,
                filename=output_filename,
                owner=owner,
                category="documents",
                description=f"Compiled PDF from {len(resolved_names)} images: {', '.join(resolved_names)}",
                tags=["images_to_pdf", "compiled"],
            )
            log_activity(f"Compiled {len(resolved_names)} images into PDF '{output_filename}'")
            return {
                "status": "success",
                "action": "images_to_pdf",
                "file": record,
                "input_count": len(resolved_names),
                "message": f"Berhasil menggabungkan {len(resolved_names)} foto/gambar menjadi file PDF *{record['filename']}*.",
            }

        # ============================================================
        # 5. PDF TO DOCX
        # ============================================================
        elif action in ("to_docx", "pdf_to_docx", "convert_docx"):
            target = target_list[0]
            res = _resolve_vault_file(target)
            if not res:
                return {"status": "error", "error": f"File '{target}' tidak ditemukan di brankas dokumen."}
            rec, b = res
            orig_name = rec.get("original_filename") or rec["filename"]

            docx_bytes = pdf_to_docx_bytes(b, filename=orig_name)

            if not output_filename:
                base_name = os.path.splitext(orig_name)[0]
                output_filename = f"{base_name}.docx"
            elif not output_filename.lower().endswith(".docx"):
                output_filename = f"{output_filename}.docx"

            record = save_file_to_vault(
                data=docx_bytes,
                filename=output_filename,
                owner=owner,
                category="documents",
                description=f"Converted Word document from {orig_name}",
                tags=["docx", "word", "converted"],
            )
            log_activity(f"Converted PDF '{orig_name}' to Word DOCX '{output_filename}'")
            return {
                "status": "success",
                "action": "to_docx",
                "file": record,
                "message": f"Berhasil mengonversi file PDF *{orig_name}* menjadi Word DOCX *{record['filename']}*.",
            }

        # ============================================================
        # 6. DOCX TO PDF
        # ============================================================
        elif action in ("from_docx", "docx_to_pdf"):
            target = target_list[0]
            res = _resolve_vault_file(target)
            if not res:
                return {"status": "error", "error": f"File '{target}' tidak ditemukan di brankas dokumen."}
            rec, b = res
            orig_name = rec.get("original_filename") or rec["filename"]

            pdf_bytes = docx_to_pdf_bytes(b)

            if not output_filename:
                base_name = os.path.splitext(orig_name)[0]
                output_filename = f"{base_name}.pdf"
            elif not output_filename.lower().endswith(".pdf"):
                output_filename = f"{output_filename}.pdf"

            record = save_file_to_vault(
                data=pdf_bytes,
                filename=output_filename,
                owner=owner,
                category="documents",
                description=f"Converted PDF from Word document {orig_name}",
                tags=["pdf", "docx_to_pdf", "converted"],
            )
            log_activity(f"Converted DOCX '{orig_name}' to PDF '{output_filename}'")
            return {
                "status": "success",
                "action": "from_docx",
                "file": record,
                "message": f"Berhasil mengonversi file Word *{orig_name}* menjadi PDF *{record['filename']}*.",
            }

        # ============================================================
        # 7. COMPRESS PDF
        # ============================================================
        elif action in ("compress", "optimize", "shrink"):
            target = target_list[0]
            res = _resolve_vault_file(target)
            if not res:
                return {"status": "error", "error": f"File '{target}' tidak ditemukan di brankas dokumen."}
            rec, b = res
            orig_name = rec.get("original_filename") or rec["filename"]
            orig_size = len(b)

            downsample_dpi = int(args.get("downsample_dpi") or 150)
            comp_bytes = compress_pdf_bytes(b, downsample_dpi=downsample_dpi)
            new_size = len(comp_bytes)

            if not output_filename:
                base_name = os.path.splitext(orig_name)[0]
                output_filename = f"{base_name}_compressed.pdf"
            elif not output_filename.lower().endswith(".pdf"):
                output_filename = f"{output_filename}.pdf"

            saved_pct = max(0.0, ((orig_size - new_size) / max(1, orig_size)) * 100.0)

            record = save_file_to_vault(
                data=comp_bytes,
                filename=output_filename,
                owner=owner,
                category="documents",
                description=f"Compressed version of {orig_name} (Saved {saved_pct:.1f}%)",
                tags=["compressed", "pdf", "optimized"],
            )
            log_activity(f"Compressed PDF '{orig_name}': {orig_size}B -> {new_size}B")
            return {
                "status": "success",
                "action": "compress",
                "file": record,
                "original_size": orig_size,
                "compressed_size": new_size,
                "saved_percent": round(saved_pct, 1),
                "message": f"Berhasil mengompres file *{orig_name}* ({orig_size // 1024} KB ➔ {new_size // 1024} KB, hemat {saved_pct:.1f}%).",
            }

        else:
            return {
                "status": "error",
                "error": f"Aksi '{action}' tidak dikenal. Pilih salah satu: merge, split, render_image, images_to_pdf, to_docx, from_docx, compress.",
            }

    except Exception as ex:
        log.exception("Error processing PDF action '%s': %s", action, ex)
        return {"status": "error", "error": f"Gagal memproses PDF ({action}): {ex}"}
