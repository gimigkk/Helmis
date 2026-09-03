"""
sandbox.py — Ephemeral Temp Sandbox Workspace & Cache Storage for Helmis.

Provides an isolated, safe temporary directory (/app/data/sandbox or data/sandbox)
for downloaded Google Docs/Sheets exports, temporary file conversions, and web caches.
Guarantees zero database pollution of the permanent Document Vault.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("helmis-sandbox")
TZ = ZoneInfo("Asia/Jakarta")

DATA_DIR = os.environ.get("DATA_DIR") or (
    "/app/data"
    if os.path.exists("/app/data")
    else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
)
SANDBOX_DIR = os.path.join(DATA_DIR, "sandbox")


def get_sandbox_dir() -> str:
    """Return verified absolute path to the sandbox directory."""
    s_dir = os.environ.get("SANDBOX_DIR") or os.path.join(DATA_DIR, "sandbox")
    os.makedirs(s_dir, exist_ok=True)
    return s_dir


def init_sandbox_dir() -> str:
    """Initialize sandbox directory and remove any orphaned .tmp files."""
    s_dir = get_sandbox_dir()
    try:
        for fname in os.listdir(s_dir):
            if fname.endswith(".tmp") or ".tmp." in fname:
                tmp_path = os.path.join(s_dir, fname)
                try:
                    if os.path.isfile(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
    except Exception as e:
        log.warning("Could not clean startup .tmp files in sandbox: %s", e)
    return s_dir


def is_safe_sandbox_path(target_path: str) -> bool:
    """Verify that target_path is strictly within SANDBOX_DIR (prevent path traversal)."""
    try:
        abs_sandbox = os.path.abspath(get_sandbox_dir())
        abs_target = os.path.abspath(target_path)
        return os.path.commonpath([abs_sandbox, abs_target]) == abs_sandbox
    except Exception:
        return False


def save_to_sandbox(
    data: bytes,
    filename: str,
    metadata: dict[str, Any] | None = None,
    ttl_seconds: int = 1800,
) -> dict[str, Any]:
    """
    Save raw bytes and optional metadata to the ephemeral sandbox workspace.
    Returns file metadata record.
    """
    s_dir = get_sandbox_dir()
    clean_name = os.path.basename(filename).strip()
    clean_stem, ext = os.path.splitext(clean_name)
    if not clean_stem:
        clean_stem = f"sandbox_{int(time.time())}"

    file_id = f"sbx_{uuid.uuid4().hex[:8]}"
    final_filename = f"{clean_stem}_{file_id}{ext}"
    final_path = os.path.join(s_dir, final_filename)
    meta_path = f"{final_path}.meta.json"

    if not is_safe_sandbox_path(final_path):
        raise ValueError(f"Target path is outside sandbox: {final_path}")

    # Atomic write for binary data
    tmp_path = f"{final_path}.tmp.{uuid.uuid4().hex[:6]}"
    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, final_path)

    now_ts = time.time()
    now_dt = datetime.now(TZ)
    now_str = now_dt.strftime("%A, %d %B %Y - %H:%M WIB")

    record: dict[str, Any] = {
        "file_id": file_id,
        "filename": final_filename,
        "original_filename": clean_name,
        "filepath": final_path,
        "relative_path": os.path.relpath(final_path, s_dir).replace("\\", "/"),
        "size_bytes": len(data),
        "content_hash": hashlib.sha256(data).hexdigest(),
        "created_at": now_str,
        "created_ts": now_ts,
        "expires_at_ts": now_ts + ttl_seconds,
        "ttl_seconds": ttl_seconds,
        "metadata": metadata or {},
    }

    # Save meta sidecar
    tmp_meta = f"{meta_path}.tmp.{uuid.uuid4().hex[:6]}"
    with open(tmp_meta, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_meta, meta_path)

    log.debug("Saved ephemeral file to sandbox: %s (%d bytes)", final_filename, len(data))
    return record


def get_from_sandbox(filename_or_id: str) -> tuple[dict[str, Any], bytes] | None:
    """Retrieve sandbox record and raw bytes if not expired."""
    s_dir = get_sandbox_dir()
    target_id = filename_or_id.strip()

    for fname in os.listdir(s_dir):
        if fname.endswith(".meta.json"):
            meta_path = os.path.join(s_dir, fname)
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("file_id") == target_id or meta.get("filename") == target_id or meta.get("original_filename") == target_id:
                    # Check TTL
                    if meta.get("expires_at_ts", 0) < time.time():
                        log.debug("Sandbox file %s has expired", fname)
                        return None
                    data_file = meta.get("filepath")
                    if data_file and os.path.exists(data_file) and is_safe_sandbox_path(data_file):
                        with open(data_file, "rb") as df:
                            return meta, df.read()
            except Exception as e:
                log.warning("Could not read sandbox meta %s: %s", meta_path, e)
    return None


def get_cached_url_snapshot(url: str) -> tuple[dict[str, Any], bytes] | None:
    """Check if a valid unexpired snapshot for a given URL exists in sandbox cache."""
    s_dir = get_sandbox_dir()
    url_clean = url.strip()

    for fname in os.listdir(s_dir):
        if fname.endswith(".meta.json"):
            meta_path = os.path.join(s_dir, fname)
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                cached_url = meta.get("metadata", {}).get("source_url")
                if cached_url and cached_url.strip() == url_clean:
                    if meta.get("expires_at_ts", 0) >= time.time():
                        data_file = meta.get("filepath")
                        if data_file and os.path.exists(data_file) and is_safe_sandbox_path(data_file):
                            with open(data_file, "rb") as df:
                                return meta, df.read()
            except Exception:
                continue
    return None


def cleanup_sandbox(max_age_seconds: int = 3600, max_total_mb: int = 250) -> int:
    """
    Remove expired sandbox files and enforce maximum directory size limit (LRU).
    Returns number of deleted files.
    """
    s_dir = get_sandbox_dir()
    now = time.time()
    deleted_count = 0

    entries: list[tuple[str, float, int]] = []  # (path, mtime, size)
    total_size = 0

    for fname in os.listdir(s_dir):
        fpath = os.path.join(s_dir, fname)
        if not os.path.isfile(fpath):
            continue

        try:
            stat = os.stat(fpath)
            age = now - stat.st_mtime
            size = stat.st_size
            total_size += size
            entries.append((fpath, stat.st_mtime, size))

            # Delete if older than max_age
            if age > max_age_seconds:
                os.remove(fpath)
                deleted_count += 1
                total_size -= size
        except Exception as ex:
            log.warning("Could not stat/clean sandbox file %s: %s", fpath, ex)

    # If still exceeding max_total_mb, delete oldest files (LRU)
    max_bytes = max_total_mb * 1024 * 1024
    if total_size > max_bytes:
        entries.sort(key=lambda x: x[1])  # Sort by oldest mtime
        for path, _, sz in entries:
            if total_size <= max_bytes:
                break
            if os.path.exists(path):
                try:
                    os.remove(path)
                    deleted_count += 1
                    total_size -= sz
                except Exception:
                    pass

    if deleted_count > 0:
        log.info("Cleaned %d expired/overflow file(s) from sandbox", deleted_count)
    return deleted_count
