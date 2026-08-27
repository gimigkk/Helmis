"""
vault.py — Core Document Vault, File Storage Hierarchy, Metadata Catalog, and Safe Dynamic Operations.
"""

import fcntl
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

log = logging.getLogger("helmis-vault")
TZ = ZoneInfo("Asia/Jakarta")

DATA_DIR = os.environ.get("DATA_DIR") or (
    "/app/data" if os.path.exists("/app/data") else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
)
VAULT_DIR = os.path.join(DATA_DIR, "vault")
CATALOG_FILE = os.path.join(DATA_DIR, "file_catalog.json")

DEFAULT_CATEGORIES = ["health", "id_cards", "travel", "receipts", "documents", "media", "projects"]
DEFAULT_OWNERS = ["gilang", "bunga", "shared"]


def _get_vault_dir() -> str:
    import sys
    v_dir = globals().get("VAULT_DIR") or os.path.join(DATA_DIR, "vault")
    for mod_name in ("src.vault", "src.memory", "src.memory.vault"):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            if hasattr(mod, "VAULT_DIR"):
                v_dir = getattr(mod, "VAULT_DIR")
    return v_dir


def _get_catalog_file() -> str:
    import sys
    c_file = globals().get("CATALOG_FILE") or os.path.join(DATA_DIR, "file_catalog.json")
    for mod_name in ("src.vault", "src.memory", "src.memory.vault"):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            if hasattr(mod, "CATALOG_FILE"):
                c_file = getattr(mod, "CATALOG_FILE")
    return c_file


def is_safe_vault_path(target_path: str) -> bool:
    """Verify that target_path is strictly within VAULT_DIR (prevent path traversal)."""
    try:
        abs_vault = os.path.abspath(_get_vault_dir())
        abs_target = os.path.abspath(target_path)
        return os.path.commonpath([abs_vault, abs_target]) == abs_vault
    except Exception:
        return False


def init_vault_structure() -> None:
    """Initialize base directory structure under VAULT_DIR if not present."""
    v_dir = _get_vault_dir()
    c_file = _get_catalog_file()
    os.makedirs(v_dir, exist_ok=True)
    for cat in DEFAULT_CATEGORIES:
        for owner in DEFAULT_OWNERS:
            os.makedirs(os.path.join(v_dir, cat, owner), exist_ok=True)
    if not os.path.exists(c_file):
        _save_catalog({"files": [], "version": 1})


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to alphanumeric, underscores, hyphens, and standard extension."""
    clean = os.path.basename(filename).strip()
    name, ext = os.path.splitext(clean)
    name = re.sub(r"[^\w\-\.]+", "_", name).strip("._")
    if not name:
        name = f"file_{int(time.time())}"
    ext = ext.lower()
    return f"{name}{ext}"


def _load_catalog() -> dict[str, Any]:
    init_vault_structure()
    c_file = _get_catalog_file()
    if not os.path.exists(c_file):
        return {"files": [], "version": 1}
    try:
        with open(c_file, encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return cast(dict[str, Any], json.load(f))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as err:
        log.error("Error reading file_catalog.json: %s", err)
        return {"files": [], "version": 1}


def _sanitize_surrogates(obj: Any) -> Any:
    """Recursively sanitize surrogate characters from strings to guarantee valid UTF-8 JSON serialization."""
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {_sanitize_surrogates(k): _sanitize_surrogates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_surrogates(v) for v in obj]
    return obj


def _save_catalog(data: dict[str, Any]) -> None:
    c_file = _get_catalog_file()
    parent = os.path.dirname(c_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_file = f"{c_file}.tmp.{uuid.uuid4().hex[:8]}"
    clean_data = _sanitize_surrogates(data)
    with open(tmp_file, "w", encoding="utf-8", errors="replace") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(clean_data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    os.replace(tmp_file, c_file)


def save_file_to_vault(
    data: bytes,
    filename: str,
    owner: str = "Gilang",
    category: str = "documents",
    subfolder: str = "",
    description: str = "",
    tags: list[str] | None = None,
    ocr_summary: str = "",
    allow_versioning: bool = True,
    original_filename: str | None = None,
) -> dict[str, Any]:
    """Save raw file bytes into the Document Vault with automatic catalog indexing."""
    init_vault_structure()
    clean_name = sanitize_filename(filename)
    orig_name = (original_filename or filename).strip()
    # Strip any directory path traversal from orig_name for display safety
    orig_name = os.path.basename(orig_name) or filename
    owner_clean = owner.strip().lower()
    if owner_clean not in ("gilang", "bunga", "both", "shared"):
        owner_clean = "gilang"
    owner_folder = "shared" if owner_clean in ("both", "shared") else owner_clean
    category_clean = sanitize_filename(category).lower().strip("._") or "documents"

    content_hash = hashlib.sha256(data).hexdigest()

    catalog = _load_catalog()
    files = catalog.get("files", [])

    for existing in files:
        if existing.get("content_hash") == content_hash:
            log.info("Identical file already exists in vault: %s", existing.get("filename"))
            if orig_name and existing.get("original_filename") != orig_name:
                existing["original_filename"] = orig_name
                _save_catalog(catalog)
            return cast(dict[str, Any], existing)

    v_dir = _get_vault_dir()
    if subfolder:
        clean_subfolder = os.path.normpath(subfolder).strip("/\\")
        dest_dir = os.path.join(v_dir, clean_subfolder)
    else:
        dest_dir = os.path.join(v_dir, category_clean, owner_folder)

    if not is_safe_vault_path(dest_dir):
        dest_dir = os.path.join(v_dir, "documents", owner_folder)

    os.makedirs(dest_dir, exist_ok=True)

    final_name = clean_name
    dest_file = os.path.join(dest_dir, final_name)
    if os.path.exists(dest_file) and allow_versioning:
        base_stem, ext = os.path.splitext(clean_name)
        ver = 2
        while os.path.exists(os.path.join(dest_dir, f"{base_stem}_v{ver}{ext}")):
            ver += 1
        final_name = f"{base_stem}_v{ver}{ext}"
        dest_file = os.path.join(dest_dir, final_name)

    tmp_dest = f"{dest_file}.tmp.{uuid.uuid4().hex[:6]}"
    with open(tmp_dest, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_dest, dest_file)

    mime_type, _ = mimetypes.guess_type(dest_file)
    if not mime_type:
        mime_type = "application/octet-stream"

    rel_path = os.path.relpath(dest_file, v_dir).replace("\\", "/")
    now_dt = datetime.now(TZ)
    now_str = now_dt.strftime("%A, %d %B %Y - %H:%M WIB")

    file_record: dict[str, Any] = {
        "id": f"doc_{int(time.time())}_{uuid.uuid4().hex[:6]}",
        "filename": final_name,
        "original_filename": orig_name,
        "relative_path": rel_path,
        "category": category_clean,
        "owner": "Both" if owner_folder == "shared" else owner.capitalize(),
        "mime_type": mime_type,
        "size_bytes": len(data),
        "content_hash": content_hash,
        "tags": tags or [],
        "description": description.strip() or orig_name,
        "ocr_summary": ocr_summary.strip(),
        "created_at": now_str,
        "updated_at": now_str,
    }

    files.append(file_record)
    catalog["files"] = files
    _save_catalog(catalog)
    log.info("Saved file to vault: %s (%s bytes)", rel_path, len(data))
    return file_record


def search_vault(
    query: str,
    owner: str | None = None,
    category: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search files in vault by keyword across filename, original_filename, description, tags, and OCR summary."""
    catalog = _load_catalog()
    files = catalog.get("files", [])
    q = query.lower().strip()
    owner_filter = owner.strip().lower() if owner else None
    cat_filter = category.strip().lower() if category else None

    matches: list[dict[str, Any]] = []
    for f in files:
        if owner_filter:
            f_owner = str(f.get("owner", "")).lower()
            if owner_filter not in f_owner and f_owner not in ("both", "shared"):
                continue
        if cat_filter:
            f_cat = str(f.get("category", "")).lower()
            if cat_filter != f_cat and cat_filter not in str(f.get("relative_path", "")).lower():
                continue

        fn = str(f.get("filename", "")).lower()
        orig_fn = str(f.get("original_filename", "")).lower()
        desc = str(f.get("description", "")).lower()
        tags = [str(t).lower() for t in f.get("tags", [])]
        ocr = str(f.get("ocr_summary", "")).lower()

        searchable_text = f"{fn} {orig_fn} {desc} {' '.join(tags)} {ocr}"
        if q in fn or q in orig_fn or q in desc or any(q in t for t in tags) or q in ocr:
            matches.append(f)
        elif all(word in searchable_text for word in q.split()):
            matches.append(f)

    return matches[:limit]


def list_vault_files(
    owner: str | None = None,
    category: str | None = None,
    directory: str | None = None,
) -> list[dict[str, Any]]:
    """List files registered in the Document Vault filtered by owner, category, or subfolder."""
    catalog = _load_catalog()
    files = catalog.get("files", [])
    owner_filter = owner.strip().lower() if owner else None
    cat_filter = category.strip().lower() if category else None
    dir_filter = directory.strip().lower().replace("\\", "/") if directory else None

    result: list[dict[str, Any]] = []
    for f in files:
        if owner_filter:
            f_owner = str(f.get("owner", "")).lower()
            if owner_filter not in f_owner and f_owner not in ("both", "shared"):
                continue
        if cat_filter:
            f_cat = str(f.get("category", "")).lower()
            if cat_filter != f_cat and cat_filter not in str(f.get("relative_path", "")).lower():
                continue
        if dir_filter:
            rel = str(f.get("relative_path", "")).lower()
            if not rel.startswith(dir_filter):
                continue
        result.append(f)
    return result


def get_vault_file_by_id(file_id: str) -> tuple[dict[str, Any], bytes] | None:
    """Retrieve file record and raw bytes by file_id."""
    catalog = _load_catalog()
    v_dir = _get_vault_dir()
    for f in catalog.get("files", []):
        if f.get("id") == file_id:
            full_path = os.path.join(v_dir, f.get("relative_path", ""))
            if os.path.exists(full_path) and is_safe_vault_path(full_path):
                with open(full_path, "rb") as fp:
                    return f, fp.read()
    return None


def get_vault_file_by_name(filename: str, owner: str | None = None) -> tuple[dict[str, Any], bytes] | None:
    """Retrieve file record and raw bytes by filename match."""
    matches = search_vault(query=filename, owner=owner, limit=1)
    if matches:
        return get_vault_file_by_id(matches[0]["id"])
    return None


def _resolve_target_files(target: str | list[str], exact_only: bool = False) -> list[dict[str, Any]]:
    """Helper to resolve a target (ID, filename, list of IDs, or search query) to file records."""
    catalog = _load_catalog()
    files = catalog.get("files", [])
    if isinstance(target, list):
        ids_or_names = {str(t).lower().strip() for t in target}
        return [f for f in files if f.get("id", "").lower() in ids_or_names or f.get("filename", "").lower() in ids_or_names]

    t_str = str(target).strip()
    if not t_str:
        return []

    # 1. Exact ID match
    for f in files:
        if f.get("id") == t_str:
            return [f]

    # 2. Exact filename match
    for f in files:
        if f.get("filename", "").lower() == t_str.lower():
            return [f]

    if exact_only:
        return []

    # 3. Fallback to keyword search across catalog (requires min 3 chars to prevent accidental broad wipes)
    if len(t_str) >= 3:
        return search_vault(query=t_str, limit=50)
    return []


def move_vault_files(
    target: str | list[str],
    destination_dir: str | None = None,
    new_category: str | None = None,
    new_owner: str | None = None,
) -> list[dict[str, Any]]:
    """
    Polymorphic Move: Moves 1 or many files to a destination directory, category, or owner.
    Target can be a single file ID/name, a list of IDs/names, or a search query string.
    """
    catalog = _load_catalog()
    files = catalog.get("files", [])
    targets = _resolve_target_files(target)

    if not targets:
        return []

    moved_records: list[dict[str, Any]] = []
    target_ids = {t["id"] for t in targets}
    v_dir = _get_vault_dir()

    for record in files:
        if record["id"] not in target_ids:
            continue

        old_rel = record.get("relative_path", "")
        old_full = os.path.join(v_dir, old_rel)
        if not os.path.exists(old_full) or not is_safe_vault_path(old_full):
            continue

        cat = (new_category or record.get("category", "documents")).lower().strip()
        owner_str = (new_owner or record.get("owner", "Gilang")).capitalize()
        owner_folder = "shared" if owner_str.lower() in ("both", "shared") else owner_str.lower()

        if destination_dir:
            dest_dir = os.path.join(v_dir, destination_dir.strip("/\\"))
        else:
            dest_dir = os.path.join(v_dir, cat, owner_folder)

        if not is_safe_vault_path(dest_dir):
            continue

        os.makedirs(dest_dir, exist_ok=True)
        filename = record.get("filename", "")
        new_full = os.path.join(dest_dir, filename)

        # Collision versioning if destination already exists and is different file
        if os.path.exists(new_full) and os.path.abspath(old_full) != os.path.abspath(new_full):
            base_stem, ext = os.path.splitext(filename)
            ver = 2
            while os.path.exists(os.path.join(dest_dir, f"{base_stem}_v{ver}{ext}")):
                ver += 1
            filename = f"{base_stem}_v{ver}{ext}"
            new_full = os.path.join(dest_dir, filename)

        shutil.move(old_full, new_full)
        new_rel = os.path.relpath(new_full, v_dir).replace("\\", "/")

        record["filename"] = filename
        record["relative_path"] = new_rel
        record["category"] = cat
        record["owner"] = owner_str
        record["updated_at"] = datetime.now(TZ).strftime("%A, %d %B %Y - %H:%M WIB")
        moved_records.append(record)
        log.info("Moved vault file from %s to %s", old_rel, new_rel)

    if moved_records:
        _save_catalog(catalog)

    return moved_records


def delete_vault_files(target: str | list[str], allow_bulk_query: bool = True) -> list[str]:
    """
    Polymorphic Delete: Deletes 1 or many files matched by ID, filename, list, or search query.
    Returns list of deleted filenames.
    """
    catalog = _load_catalog()
    files = catalog.get("files", [])
    targets = _resolve_target_files(target, exact_only=not allow_bulk_query)

    if not targets:
        return []

    target_ids = {t["id"] for t in targets}
    deleted_names: list[str] = []
    v_dir = _get_vault_dir()

    remaining_files: list[dict[str, Any]] = []
    for f in files:
        if f.get("id") in target_ids:
            full_path = os.path.join(v_dir, f.get("relative_path", ""))
            if os.path.exists(full_path) and is_safe_vault_path(full_path):
                try:
                    os.remove(full_path)
                except Exception as err:
                    log.error("Failed to remove file from disk: %s", err)
            deleted_names.append(f.get("filename", ""))
        else:
            remaining_files.append(f)

    if deleted_names:
        catalog["files"] = remaining_files
        _save_catalog(catalog)

    return deleted_names


def create_vault_directory(dir_path: str) -> str:
    """Create a new custom directory path under the Document Vault."""
    init_vault_structure()
    clean_path = dir_path.strip().replace("..", "").strip("/\\")
    v_dir = _get_vault_dir()
    full_path = os.path.join(v_dir, clean_path)
    if not is_safe_vault_path(full_path):
        raise ValueError(f"Invalid directory path: {dir_path}")
    os.makedirs(full_path, exist_ok=True)
    return os.path.relpath(full_path, v_dir).replace("\\", "/")


def delete_vault_directory(dir_path: str, recursive: bool = False) -> tuple[bool, str]:
    """Delete a directory from the vault (empty or recursive with catalog cleanup)."""
    init_vault_structure()
    clean_path = dir_path.strip().replace("..", "").strip("/\\")
    v_dir = _get_vault_dir()
    full_path = os.path.join(v_dir, clean_path)
    if not is_safe_vault_path(full_path):
        return False, "Direktori di luar brankas tidak dapat dihapus."

    if not os.path.exists(full_path):
        return False, f"Direktori '{clean_path}' tidak ditemukan."

    if full_path == os.path.abspath(v_dir):
        return False, "Direktori root brankas tidak dapat dihapus."

    # Guard core categories from deletion
    if clean_path.lower() in DEFAULT_CATEGORIES:
        return False, f"Kategori utama '{clean_path}' dilindungi dan tidak dapat dihapus."

    entries = os.listdir(full_path)
    if entries and not recursive:
        return False, f"Direktori '{clean_path}' tidak kosong ({len(entries)} item). Gunakan recursive=True untuk menghapus beserta isinya."

    catalog = _load_catalog()
    files = catalog.get("files", [])
    rel_prefix = os.path.relpath(full_path, v_dir).replace("\\", "/")

    updated_files = [f for f in files if not str(f.get("relative_path", "")).startswith(rel_prefix)]
    removed_count = len(files) - len(updated_files)

    shutil.rmtree(full_path)
    catalog["files"] = updated_files
    _save_catalog(catalog)

    return True, f"Direktori '{clean_path}' berhasil dihapus ({removed_count} file di-unregister)."


def read_vault_file(
    file_id_or_name: str,
    max_chars: int = 8000,
) -> dict[str, Any]:
    """
    Read and extract the contents of a file stored in the Document Vault.
    Supports:
    - Text/Markdown/Code/JSON/CSV (decoded UTF-8 with latin-1 fallback)
    - PDF documents (extracts text from all pages via pypdf, falls back to OCR summary if raster)
    - Images/Binary (returns metadata, size, description, and OCR summary)
    """
    res = get_vault_file_by_id(file_id_or_name)
    if not res:
        res = get_vault_file_by_name(file_id_or_name)
    if not res:
        return {"status": "error", "error": f"File '{file_id_or_name}' tidak ditemukan di brankas dokumen."}

    record, raw_bytes = res
    filename = record.get("filename", "")
    mime = record.get("mime_type", "")
    ext = os.path.splitext(filename)[1].lower()

    content_type = "binary"
    extracted_text = ""

    # 1. Plain text / Markdown / JSON / CSV / Code / Configs
    if (
        mime.startswith("text/")
        or ext in (
            ".txt",
            ".md",
            ".json",
            ".csv",
            ".tsv",
            ".py",
            ".yaml",
            ".yml",
            ".env",
            ".log",
            ".html",
            ".css",
            ".js",
        )
    ):
        content_type = "text"
        try:
            extracted_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            extracted_text = raw_bytes.decode("latin-1", errors="replace")

        # Binary spoof detection: if text contains > 5% null bytes or non-printable chars, treat as binary
        if raw_bytes and (extracted_text.count("\x00") / max(1, len(extracted_text)) > 0.02):
            content_type = "binary"
            desc = record.get("description", "")
            extracted_text = f"[File Biner {mime}]: {desc} (Data biner mentah tidak dapat ditampilkan sebagai teks)"

    # 2. PDF Documents
    elif ext == ".pdf" or mime == "application/pdf":
        content_type = "pdf"
        pdf_pages_text: list[str] = []
        is_encrypted = False
        try:
            import io

            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    is_encrypted = True

            if is_encrypted:
                extracted_text = "[Dokumen PDF terenkripsi / ber-password. Konten teks tidak dapat diekstrak tanpa kata sandi.]"
            else:
                total_p = len(reader.pages)
                for i, page in enumerate(reader.pages):
                    try:
                        p_txt = page.extract_text() or ""
                        if p_txt.strip():
                            pdf_pages_text.append(f"--- Halaman {i+1} dari {total_p} ---\n{p_txt.strip()}")
                    except Exception:
                        continue
                if pdf_pages_text:
                    extracted_text = "\n\n".join(pdf_pages_text)
        except Exception as ex:
            log.warning("pypdf text extraction error on %s: %s", filename, ex)

        # Fallback to OCR summary if PDF has no embedded text layer (scanned image)
        if not extracted_text.strip():
            ocr = record.get("ocr_summary", "")
            if ocr:
                extracted_text = f"[Hasil OCR Dokumen Scan]:\n{ocr}"
            else:
                extracted_text = "[Dokumen PDF raster scan tanpa teks digital. Tidak ada teks yang dapat diekstrak.]"

    # 3. Images / Other media
    elif mime.startswith("image/"):
        content_type = "image"
        ocr = record.get("ocr_summary", "")
        desc = record.get("description", "")
        extracted_text = f"[File Gambar/Foto]: {desc}\n[Hasil OCR]: {ocr if ocr else 'Tidak ada ringkasan OCR.'}"

    else:
        content_type = "binary"
        desc = record.get("description", "")
        extracted_text = f"[File Biner {mime}]: {desc}"

    # Apply length clipping if exceeded
    effective_max = max(100, max_chars)
    is_truncated = False
    if len(extracted_text) > effective_max:
        extracted_text = (
            extracted_text[:effective_max]
            + f"\n\n... (Dipotong karena melebihi batas {effective_max} karakter)"
        )
        is_truncated = True

    return {
        "status": "success",
        "file": record,
        "content_type": content_type,
        "content": extracted_text,
        "is_truncated": is_truncated,
        "size_bytes": len(raw_bytes),
    }


def list_vault_directories() -> list[str]:
    """List all directory paths inside the Document Vault."""
    init_vault_structure()
    dirs: list[str] = []
    v_dir = _get_vault_dir()
    for root, dirnames, _ in os.walk(v_dir):
        for d in dirnames:
            full = os.path.join(root, d)
            rel = os.path.relpath(full, v_dir).replace("\\", "/")
            dirs.append(rel)
    return sorted(dirs)
