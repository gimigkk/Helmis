"""
google_reader.py — Google Workspace & Web URL Direct Snapshot Reader.

Supports:
- Standard Google Spreadsheets (/spreadsheets/d/{id} -> CSV -> Markdown Table)
- Published Google Spreadsheets (/spreadsheets/d/e/{pub_id}/pubhtml or /pub -> Multi-Tab HTML Table Parser)
- Google Docs (Clean UTF-8 plain text export)
- Google Slides (PDF export -> Slide-by-slide text extraction)
- Google Drive Files (Direct download -> Content extraction)
- General Web Pages (Clean HTML text scraper with SSRF protection)

Employs Ephemeral Sandbox Caching and Epistemic Non-Realtime Snapshot Awareness.
"""

import csv
import html
import io
import ipaddress
import logging
import re
import socket
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx

from ..memory.sandbox import get_cached_url_snapshot, save_to_sandbox

log = logging.getLogger("helmis-google-reader")
TZ = ZoneInfo("Asia/Jakarta")

# SSRF Protection: Deny private, loopback, and cloud metadata ranges
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class GoogleSheetsHTMLTableParser(HTMLParser):
    """Zero-dependency HTML table parser for published Google Sheets (pubhtml)."""

    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.in_tr = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_tr:
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self.in_table = False
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            # Clean and strip trailing empty cells
            cleaned = list(self.current_row)
            while cleaned and not cleaned[-1].strip():
                cleaned.pop()
            if any(cleaned):
                self.rows.append(cleaned)
        elif tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            cell_text = " ".join("".join(self.current_cell).split())
            self.current_row.append(html.unescape(cell_text))

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)


def format_parsed_rows_to_markdown(
    rows: list[list[str]],
    query: str = "",
    max_rows: int = 100,
) -> str:
    """Convert parsed 2D row list into a readable markdown table."""
    if not rows:
        return "[Tabel spreadsheet kosong]"

    # Filter row header index if first column is just '1', '2', '3' etc.
    filtered_rows: list[list[str]] = []
    for r in rows:
        if r and r[0].isdigit() and len(r) > 1:
            filtered_rows.append(r[1:])
        else:
            filtered_rows.append(r)

    if not filtered_rows:
        return "[Tabel spreadsheet kosong]"

    header = filtered_rows[0]
    data_rows = filtered_rows[1:] if len(filtered_rows) > 1 else []

    if query:
        q_low = query.lower().strip()
        data_rows = [r for r in data_rows if any(q_low in c.lower() for c in r)]

    total_matching = len(data_rows)
    displayed_rows = data_rows[:max_rows]

    # For very wide sheets (>10 columns), render structured record blocks
    if len(header) > 10:
        lines = [f"> *Tabel Data Spreadsheet* (Total {total_matching} baris)"]
        for idx, r in enumerate(displayed_rows):
            lines.append(f"\n--- Baris {idx + 1} ---")
            for col_idx, col_name in enumerate(header):
                val = r[col_idx] if col_idx < len(r) else ""
                if val.strip():
                    lines.append(f"• *{col_name.strip()}*: {val.strip()}")
        if total_matching > max_rows:
            lines.append(f"\n_... (Dipotong {total_matching - max_rows} baris tambahan karena batasan panjang)_")
        return "\n".join(lines)

    # Standard Markdown Pipe Table
    lines = []
    clean_header = [re.sub(r"[\r\n|]+", " ", h).strip() or f"Kolom_{i+1}" for i, h in enumerate(header)]
    lines.append("| " + " | ".join(clean_header) + " |")
    lines.append("| " + " | ".join(["---"] * len(clean_header)) + " |")

    for r in displayed_rows:
        padded = [re.sub(r"[\r\n|]+", " ", r[i]).strip() if i < len(r) else "" for i in range(len(clean_header))]
        lines.append("| " + " | ".join(padded) + " |")

    if total_matching > max_rows:
        lines.append(f"\n_Menampilkan {max_rows} dari total {total_matching} baris data._")

    return "\n".join(lines)


def is_ssrf_safe_url(url: str) -> bool:
    """Verify that URL does not resolve to localhost, private LAN, or cloud metadata."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        hostname_clean = hostname.strip().lower()
        if hostname_clean in ("localhost", "agent", "waha", "scheduler", "host.docker.internal"):
            return False

        addr_info = socket.getaddrinfo(hostname_clean, None)
        for item in addr_info:
            ip_str = item[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            for blocked in BLOCKED_IP_NETWORKS:
                if ip_obj in blocked:
                    return False
        return True
    except Exception:
        return False


def normalize_url(raw_url: str) -> str:
    """Normalize user-provided link by adding missing scheme if needed."""
    url = raw_url.strip()
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith(("docs.google.com", "drive.google.com", "sheets.google.com")):
        return f"https://{url}"
    if "." in url and not url.startswith("/"):
        return f"https://{url}"
    return url


def parse_google_url_type(url: str) -> tuple[str, str | None, dict[str, Any]]:
    """
    Identify Google Workspace service type, Document ID, and relevant parameters (e.g. gid).
    Returns (doc_type, doc_id, extra_params).
    """
    clean_url = normalize_url(url)
    parsed = urlparse(clean_url)
    path = parsed.path
    query_params = parse_qs(parsed.query)

    # 1. Published Google Sheets (/d/e/{pub_id}/pubhtml or /pub)
    if "/spreadsheets/" in clean_url and ("/d/e/" in path or "/pubhtml" in path or "/pub" in path):
        match = re.search(r"/spreadsheets/(?:u/\d+/)?d/e/([a-zA-Z0-9_-]+)", clean_url)
        pub_id = match.group(1) if match else None
        gid = query_params.get("gid", [None])[0]
        if not gid and parsed.fragment:
            frag_match = re.search(r"gid=([0-9]+)", parsed.fragment)
            if frag_match:
                gid = frag_match.group(1)
        return "sheets_pub", pub_id, {"gid": gid}

    # 2. Standard Google Sheets (/spreadsheets/d/{id})
    if "/spreadsheets/d/" in path or "sheets.google.com" in parsed.netloc:
        match = re.search(r"/spreadsheets/(?:u/\d+/)?d/([a-zA-Z0-9_-]+)", clean_url)
        doc_id = match.group(1) if match else None
        gid = query_params.get("gid", [None])[0]
        if not gid and parsed.fragment:
            frag_match = re.search(r"gid=([0-9]+)", parsed.fragment)
            if frag_match:
                gid = frag_match.group(1)
        return "sheets", doc_id, {"gid": gid}

    # 3. Google Docs
    if "/document/d/" in path or "docs.google.com/document" in clean_url:
        match = re.search(r"/document/(?:u/\d+/)?d/([a-zA-Z0-9_-]+)", clean_url)
        doc_id = match.group(1) if match else None
        return "docs", doc_id, {}

    # 4. Google Slides / Presentations
    if "/presentation/d/" in path or "docs.google.com/presentation" in clean_url:
        match = re.search(r"/presentation/(?:u/\d+/)?d/([a-zA-Z0-9_-]+)", clean_url)
        doc_id = match.group(1) if match else None
        return "slides", doc_id, {}

    # 5. Google Forms
    if "/forms/d/" in path or "docs.google.com/forms" in clean_url:
        match = re.search(r"/forms/(?:u/\d+/)?d/([a-zA-Z0-9_-]+)", clean_url)
        doc_id = match.group(1) if match else None
        return "forms", doc_id, {}

    # 6. Google Drive File
    if "/file/d/" in path:
        match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", path)
        doc_id = match.group(1) if match else None
        return "drive_file", doc_id, {}

    if "drive.google.com" in parsed.netloc and "id" in query_params:
        return "drive_file", query_params["id"][0], {}

    return "generic_web", None, {}


def format_csv_to_markdown_table(csv_text: str, query: str = "", max_rows: int = 100) -> str:
    """Format raw CSV string into clean Markdown table or key-value list."""
    if not csv_text or not csv_text.strip():
        return "[Spreadsheet kosong / tidak ada data baris]"

    try:
        reader = csv.reader(io.StringIO(csv_text.strip()))
        rows = list(reader)
        return format_parsed_rows_to_markdown(rows, query=query, max_rows=max_rows)
    except Exception as e:
        log.warning("CSV table formatting error: %s", e)
        return csv_text[:4000]


from ..memory.ocr import perform_vision_ocr

log = logging.getLogger("helmis-google-reader")
TZ = ZoneInfo("Asia/Jakarta")

# SSRF Protection: Deny private, loopback, and cloud metadata ranges
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def extract_pdf_slides_text(pdf_bytes: bytes, force_ocr: bool = False) -> str:
    """Extract slide-by-slide text from Google Slides / PDF documents, running Gemini Vision OCR on diagrams and visual slides."""
    try:
        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        if doc.is_encrypted:
            try:
                doc.authenticate("")
            except Exception:
                return "[Dokumen PDF terenkripsi / ber-password.]"

        total_pages = len(doc)
        if total_pages == 0:
            return "[Dokumen / Presentasi kosong tanpa halaman]"

        slide_texts: list[str] = []
        for idx, page in enumerate(doc):
            raw_txt = page.get_text("text")
            clean_txt = str(raw_txt).strip() if raw_txt else ""
            page_parts: list[str] = []

            if force_ocr or not clean_txt:
                try:
                    pix = page.get_pixmap(dpi=150)
                    rendered_png = pix.tobytes("png")
                    ocr_txt = perform_vision_ocr(
                        rendered_png,
                        "image/png",
                        prompt_hint="Extract all readable text, tabular schedules, dates, deadlines, milestones, and visual details verbatim from this slide / document page into clean Markdown.",
                    )
                    if ocr_txt and ocr_txt.strip():
                        page_parts.append(f"[Hasil Vision OCR (Visual Mode)]\n{ocr_txt.strip()}")
                    elif clean_txt:
                        page_parts.append(clean_txt)
                except Exception as ocr_err:
                    log.warning("Vision OCR failed on PDF page %d: %s", idx + 1, ocr_err)
                    if clean_txt:
                        page_parts.append(clean_txt)
            else:
                page_parts.append(clean_txt)
                # Check for embedded diagrams / pictures on this slide
                try:
                    img_list = page.get_images(full=True)
                    if img_list:
                        for img_info in img_list[:2]:
                            xref = img_info[0]
                            base_img = doc.extract_image(xref)
                            w, h = base_img.get("width", 0), base_img.get("height", 0)
                            img_data = base_img.get("image", b"")
                            if w >= 80 and h >= 80 and len(img_data) >= 200:
                                ocr_sub = perform_vision_ocr(
                                    img_data,
                                    "image/png",
                                    prompt_hint="Extract all readable text, formulas, diagrams, labels, and table data from this diagram image.",
                                )
                                if ocr_sub and ocr_sub.strip():
                                    page_parts.append(f"*(Hasil Vision OCR Diagram/Gambar Slide {idx+1})*:\n{ocr_sub.strip()}")
                except Exception:
                    pass

            if page_parts:
                slide_texts.append(f"--- Slide/Halaman {idx + 1} dari {total_pages} ---\n" + "\n\n".join(page_parts))

        return "\n\n".join(slide_texts)
    except Exception as e:
        log.warning("PDF slide extraction error: %s, falling back to pypdf", e)
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            total = len(reader.pages)
            return "\n\n".join(
                f"--- Slide {i+1} dari {total} ---\n{(p.extract_text() or '').strip()}"
                for i, p in enumerate(reader.pages)
            )
        except Exception as pypdf_err:
            log.warning("Pypdf fallback failed: %s", pypdf_err)
            return "[Gagal mengekstrak teks dari presentasi/dokumen PDF]"


def extract_clean_html_text(html_text: str) -> str:
    """Extract readable clean text from HTML markup, removing script and style tags."""
    cleaned = re.sub(r"<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<(p|br|div|h1|h2|h3|h4|h5|h6|li)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(lines[:300])


async def read_url_content(
    url: str,
    force_refresh: bool = False,
    query: str = "",
    force_ocr: bool = False,
) -> dict[str, Any]:
    """
    Read and parse content from Google Docs, Google Sheets, Google Slides, Drive, or Web URLs.
    Saves snapshot to Temp Sandbox Workspace.
    """
    raw_url = normalize_url(url)
    if not raw_url:
        return {"status": "error", "error": "URL tidak boleh kosong."}

    # 1. Check cached snapshot in Sandbox if force_refresh is False
    if not force_refresh:
        cached = get_cached_url_snapshot(raw_url)
        if cached:
            meta, raw_bytes = cached
            source_type = meta.get("metadata", {}).get("source_type", "url")
            parsed_content = meta.get("metadata", {}).get("parsed_content", "")
            if parsed_content:
                log.debug("Returning cached sandbox snapshot for %s", raw_url)
                cached_ext_mode = meta.get("metadata", {}).get("extraction_mode")
                if not cached_ext_mode:
                    cached_ext_mode = "pubhtml_parser" if source_type == "google_sheets" else "cached_snapshot"
                return {
                    "status": "success",
                    "url": raw_url,
                    "source_type": source_type,
                    "extraction_mode": cached_ext_mode,
                    "is_snapshot": True,
                    "snapshot_at": meta.get("created_at"),
                    "cached": True,
                    "content": parsed_content,
                    "_model_directive": "Snapshot data from sandbox cache. Base your factual answers solely on this verified content.",
                }

    # 2. Parse URL structure
    doc_type, doc_id, extra_params = parse_google_url_type(raw_url)

    # 3. Handle Google Forms notice
    if doc_type == "forms":
        return {
            "status": "success",
            "url": raw_url,
            "source_type": "google_forms",
            "is_snapshot": True,
            "content": f"[Google Form Online]: Link pengisian formulir Google Form ({raw_url}). Untuk mengisi form ini, silakan buka link langsung di browser.",
            "_model_directive": "This is a Google Form link for survey/response submission.",
        }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }

    # 4. Special Handling: Published Google Sheets (/pubhtml or /pub)
    if doc_type == "sheets_pub" and doc_id:
        try:
            gid = extra_params.get("gid")
            all_tab_sections: list[str] = []
            combined_bytes = b""

            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers=headers) as client:
                index_url = f"https://docs.google.com/spreadsheets/d/e/{doc_id}/pubhtml"
                index_resp = await client.get(index_url)
                combined_bytes += index_resp.content

                # Parse all tab metadata from JavaScript items
                tab_matches = re.findall(r'\{\s*name:\s*"([^"]+)"[^}]*pageUrl:\s*"([^"]+)"', index_resp.text)

                if tab_matches:
                    for raw_tname, raw_purl in tab_matches:
                        try:
                            clean_tname = raw_tname.encode("utf-8").decode("unicode_escape", errors="ignore")
                        except Exception:
                            clean_tname = raw_tname
                        clean_purl = raw_purl.replace(r"\/", "/").replace(r"\x3d", "=").replace(r"\x26", "&")

                        # If user asked for specific gid, check matching URL
                        if gid and f"gid={gid}" not in clean_purl and len(tab_matches) > 1:
                            # If gid doesn't match, check if query matches tab name
                            if query and query.lower() not in clean_tname.lower():
                                continue

                        try:
                            sheet_resp = await client.get(clean_purl)
                            combined_bytes += sheet_resp.content
                            parser = GoogleSheetsHTMLTableParser()
                            parser.feed(sheet_resp.text)
                            md_table = format_parsed_rows_to_markdown(parser.rows, query=query)
                            all_tab_sections.append(f"### Sheet: {clean_tname}\n\n{md_table}")
                        except Exception as e:
                            log.warning("Could not fetch tab %s: %s", clean_tname, e)

                # Fallback if no JS tabs found: fetch direct sheet table
                if not all_tab_sections:
                    direct_sheet_url = f"https://docs.google.com/spreadsheets/d/e/{doc_id}/pubhtml/sheet?headers=false"
                    if gid:
                        direct_sheet_url += f"&gid={gid}"
                    sheet_resp = await client.get(direct_sheet_url)
                    combined_bytes += sheet_resp.content
                    parser = GoogleSheetsHTMLTableParser()
                    parser.feed(sheet_resp.text)
                    md_table = format_parsed_rows_to_markdown(parser.rows, query=query)
                    all_tab_sections.append(md_table)

            parsed_text = "\n\n".join(all_tab_sections)
            now_dt = datetime.now(TZ)
            now_str = now_dt.strftime("%A, %d %B %Y - %H:%M WIB")

            sandbox_meta = {
                "source_url": raw_url,
                "source_type": "google_sheets",
                "extraction_mode": "pubhtml_parser",
                "doc_id": doc_id,
                "snapshot_at": now_str,
                "parsed_content": parsed_text,
            }
            save_to_sandbox(
                data=combined_bytes or parsed_text.encode(),
                filename=f"published_sheet_{doc_id}.html",
                metadata=sandbox_meta,
                ttl_seconds=1800,
            )

            log.info("Successfully fetched and parsed published Google Sheet %s (%d chars)", raw_url, len(parsed_text))
            return {
                "status": "success",
                "url": raw_url,
                "source_type": "google_sheets",
                "extraction_mode": "pubhtml_parser",
                "is_snapshot": True,
                "snapshot_at": now_str,
                "content": parsed_text,
                "_model_directive": (
                    f"Point-in-time snapshot of published Google Sheet captured at {now_str}. "
                    "Answer user questions factually and directly based exclusively on this extracted content."
                ),
            }
        except Exception as e:
            log.exception("Error parsing published Google Sheet %s: %s", raw_url, e)
            return {
                "status": "error",
                "error": f"Gagal membaca Google Sheet yang dipublikasikan: {e}",
            }

    # 5. Standard Google Docs/Sheets/Slides/Drive/Web
    target_download_url = raw_url
    export_format_label = "web"
    expected_filename = "document.bin"

    if doc_type == "sheets" and doc_id:
        gid = extra_params.get("gid")
        gid_param = f"&gid={gid}" if gid else ""
        target_download_url = f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv{gid_param}"
        export_format_label = "google_sheets"
        expected_filename = f"spreadsheet_{doc_id}.csv"
    elif doc_type == "docs" and doc_id:
        target_download_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        export_format_label = "google_docs"
        expected_filename = f"doc_{doc_id}.txt"
    elif doc_type == "slides" and doc_id:
        target_download_url = f"https://docs.google.com/presentation/d/{doc_id}/export/pdf"
        export_format_label = "google_slides"
        expected_filename = f"presentation_{doc_id}.pdf"
    elif doc_type == "drive_file" and doc_id:
        target_download_url = f"https://drive.google.com/uc?export=download&id={doc_id}"
        export_format_label = "google_drive"
        expected_filename = f"drive_file_{doc_id}.bin"
    else:
        # SSRF Verification for arbitrary web URLs
        if not is_ssrf_safe_url(raw_url):
            return {
                "status": "error",
                "error": "Akses ke URL diblokir demi keamanan (keamanan jaringan internal / private IP).",
            }
        export_format_label = "generic_web"
        expected_filename = "web_page.html"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(target_download_url)
            final_url = str(resp.url)

            # Detect Google Login Redirect / Permission Denied
            if (
                "accounts.google.com/ServiceLogin" in final_url
                or "accounts.google.com/v3/signin" in final_url
                or resp.status_code in (401, 403)
                or (resp.status_code == 200 and "ServiceLogin" in resp.text and "Sign in" in resp.text and doc_type != "generic_web")
            ):
                return {
                    "status": "permission_denied",
                    "url": raw_url,
                    "error": "Dokumen Google ini berstatus privat.",
                    "message": (
                        "Dokumen Google ini masih berstatus privat (memerlukan izin login). "
                        "Tolong ubah akses sharing menjadi 'Siapa saja yang memiliki link / Anyone with the link' (Viewer), "
                        "lalu kirimkan linknya lagi ya."
                    ),
                    "_model_directive": "The Google document is private and cannot be read without permission. Inform the user directly to change sharing access to Anyone with the link (Viewer).",
                }

            if resp.status_code != 200:
                return {
                    "status": "error",
                    "status_code": resp.status_code,
                    "url": raw_url,
                    "error": f"Server web mengembalikan status HTTP {resp.status_code}.",
                    "message": f"Halaman atau dokumen tidak dapat diakses (HTTP {resp.status_code}).",
                }

            raw_bytes = resp.content
            if len(raw_bytes) == 0:
                return {
                    "status": "success",
                    "url": raw_url,
                    "source_type": export_format_label,
                    "content": "[Dokumen/Halaman ini kosong (0 bytes)]",
                }

            parsed_text = ""
            if raw_bytes.startswith(b"%PDF") or export_format_label == "google_slides":
                parsed_text = extract_pdf_slides_text(raw_bytes, force_ocr=force_ocr)

            elif export_format_label == "google_sheets":
                try:
                    csv_text = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    csv_text = raw_bytes.decode("latin-1", errors="replace")
                parsed_text = format_csv_to_markdown_table(csv_text, query=query)

            elif export_format_label == "google_docs":
                try:
                    parsed_text = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    parsed_text = raw_bytes.decode("latin-1", errors="replace")
                if len(parsed_text) > 15000:
                    parsed_text = parsed_text[:15000] + "\n\n... (Dipotong karena melebihi batas 15.000 karakter)"

            elif export_format_label == "generic_web":
                try:
                    html_text = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    html_text = raw_bytes.decode("latin-1", errors="replace")
                parsed_text = extract_clean_html_text(html_text)

            else:
                try:
                    parsed_text = raw_bytes.decode("utf-8")[:10000]
                except Exception:
                    parsed_text = f"[File biner Google Drive: {len(raw_bytes)} bytes]"

            # Determine extraction mode badge
            extraction_mode = "plain_text"
            if raw_bytes.startswith(b"%PDF") or export_format_label == "google_slides":
                if "[Hasil Vision OCR" in parsed_text or "*(Hasil Vision OCR" in parsed_text or force_ocr:
                    extraction_mode = "vision_ocr"
                else:
                    extraction_mode = "pdf_text"
            elif export_format_label == "google_sheets":
                extraction_mode = "csv_export"
            elif export_format_label == "google_docs":
                extraction_mode = "direct_text"
            elif export_format_label == "generic_web":
                extraction_mode = "html_scraper"

            now_dt = datetime.now(TZ)
            now_str = now_dt.strftime("%A, %d %B %Y - %H:%M WIB")

            sandbox_meta = {
                "source_url": raw_url,
                "source_type": export_format_label,
                "extraction_mode": extraction_mode,
                "doc_id": doc_id,
                "snapshot_at": now_str,
                "parsed_content": parsed_text,
            }
            save_to_sandbox(
                data=raw_bytes,
                filename=expected_filename,
                metadata=sandbox_meta,
                ttl_seconds=1800,
            )

            log.info("Successfully fetched and parsed snapshot for %s (%s, %d bytes)", raw_url, export_format_label, len(raw_bytes))

            return {
                "status": "success",
                "url": raw_url,
                "source_type": export_format_label,
                "extraction_mode": extraction_mode,
                "is_snapshot": True,
                "snapshot_at": now_str,
                "content": parsed_text,
                "_model_directive": (
                    f"Point-in-time snapshot captured at {now_str}. "
                    "This is a downloaded export snapshot (not live-streamed cursor). "
                    "Answer user questions factually and directly based exclusively on this extracted content."
                ),
            }

    except httpx.TimeoutException:
        log.warning("Timeout fetching URL %s", raw_url)
        return {
            "status": "error",
            "error": "Koneksi ke dokumen/halaman web melebihi batas waktu (timeout 10s).",
        }
    except Exception as e:
        log.exception("Error fetching URL %s: %s", raw_url, e)
        return {
            "status": "error",
            "error": f"Gagal membaca URL: {e}",
        }
