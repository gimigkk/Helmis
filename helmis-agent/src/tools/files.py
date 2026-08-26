import base64
import logging
import mimetypes
import os
from typing import Any

from ..memory.store import log_activity
from ..memory.vault import (
    create_vault_directory,
    delete_vault_directory,
    delete_vault_files,
    get_vault_file_by_id,
    get_vault_file_by_name,
    list_vault_files,
    move_vault_files,
    read_vault_file,
    save_file_to_vault,
    search_vault,
)
from ..whatsapp.client import WahaClient
from .registry import register_tool
from .whatsapp import _resolve_target_jid

log = logging.getLogger("helmis-tools-files")


@register_tool("read_vault_file")
async def handle_read_vault_file(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    """Read the full text or content of a file from the Document Vault."""
    file_id_or_name = str(args.get("file_id_or_name", "")).strip()
    if not file_id_or_name:
        return {"status": "error", "error": "file_id_or_name tidak boleh kosong."}

    max_chars = int(args.get("max_chars") or 8000)
    result = read_vault_file(file_id_or_name=file_id_or_name, max_chars=max_chars)
    if result.get("status") == "success":
        log_activity(f"Read vault file '{file_id_or_name}' (type: {result.get('content_type')})")
    return result


@register_tool("save_vault_file")
async def handle_save_vault_file(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
    media_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    original_filename = str(args.get("original_filename") or "").strip()
    if not original_filename and media_data and media_data.get("filename"):
        original_filename = str(media_data["filename"]).strip()

    filename = str(args.get("filename", "")).strip()
    if not filename:
        if original_filename:
            filename = original_filename
        else:
            return {"status": "error", "error": "Nama file tidak boleh kosong."}

    if not original_filename:
        original_filename = filename

    category = str(args.get("category", "documents")).strip()
    owner = str(args.get("owner", default_sender)).strip()
    subfolder = str(args.get("subfolder", "")).strip()
    description = str(args.get("description", "")).strip()
    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    ocr_summary = str(args.get("ocr_summary", "")).strip()

    content_text = args.get("content_text")
    if media_data and media_data.get("data"):
        try:
            raw_bytes = base64.b64decode(str(media_data["data"]))
            # Auto-infer extension from MIME if filename missing extension
            if not os.path.splitext(filename)[1] and media_data.get("mimeType"):
                ext = mimetypes.guess_extension(str(media_data["mimeType"])) or ".bin"
                filename = f"{filename}{ext}"
                if not os.path.splitext(original_filename)[1]:
                    original_filename = f"{original_filename}{ext}"
        except Exception as ex:
            log.warning("Failed to decode media_data: %s", ex)
            raw_bytes = f"# {filename}\n\nOwner: {owner}\nDescription: {description}".encode()
    elif content_text:
        raw_bytes = str(content_text).encode()
    else:
        raw_bytes = f"# {filename}\n\nOwner: {owner}\nDescription: {description}\nCreated: {category}".encode()

    record = save_file_to_vault(
        data=raw_bytes,
        filename=filename,
        owner=owner,
        category=category,
        subfolder=subfolder,
        description=description,
        tags=tags,
        ocr_summary=ocr_summary,
        original_filename=original_filename,
    )
    log_activity(f"File saved to vault: {record['relative_path']} (Owner: {record['owner']})")
    return {
        "status": "success",
        "file": record,
        "message": f"File *{record.get('original_filename') or record['filename']}* berhasil disimpan di brankas kategori *{record['category']}* ({record['relative_path']}).",
    }


@register_tool("search_vault_files")
async def handle_search_vault_files(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    owner = args.get("owner")
    category = args.get("category")
    limit = int(args.get("limit") or 10)

    matches = search_vault(query=query, owner=owner, category=category, limit=limit)
    return {
        "status": "success",
        "query": query,
        "count": len(matches),
        "files": matches,
    }


@register_tool("list_vault_files")
async def handle_list_vault_files(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    owner = args.get("owner")
    category = args.get("category")
    directory = args.get("directory")

    files = list_vault_files(owner=owner, category=category, directory=directory)
    return {
        "status": "success",
        "count": len(files),
        "files": files,
    }


@register_tool("send_vault_file")
async def handle_send_vault_file(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    file_id_or_name = str(args.get("file_id_or_name", "")).strip()
    recipient = str(args.get("recipient", "current")).strip()
    caption = args.get("caption")

    if not file_id_or_name:
        return {"status": "error", "error": "file_id_or_name tidak boleh kosong."}
    if not client:
        return {"status": "error", "error": "WAHA client tidak tersedia."}

    res = get_vault_file_by_id(file_id_or_name)
    if not res:
        res = get_vault_file_by_name(file_id_or_name)
    if not res:
        return {"status": "error", "error": f"File '{file_id_or_name}' tidak ditemukan di brankas dokumen."}

    record, raw_bytes = res
    file_id = record["id"]
    filename = record["filename"]
    orig_filename = record.get("original_filename") or filename
    mime = record.get("mime_type", "application/octet-stream")

    # For files under 10MB, use self-contained base64 data URI to avoid any bridge networking hiccups
    if len(raw_bytes) <= 10 * 1024 * 1024:
        b64_data = base64.b64encode(raw_bytes).decode("ascii")
        media_url = f"data:{mime};base64,{b64_data}"
    else:
        agent_host = os.environ.get("AGENT_INTERNAL_HOST", "agent")
        agent_port = os.environ.get("PORT", "8644")
        media_url = f"http://{agent_host}:{agent_port}/vault/file/{file_id}"

    target_jid = _resolve_target_jid(recipient, default_sender)
    await client.send_media(
        chat_id=target_jid,
        media_url=media_url,
        caption=caption or f"Dokumen: {orig_filename}",
        filename=orig_filename,
        mimetype=mime,
    )
    log_activity(f"Sent vault file '{orig_filename}' to {recipient} ({target_jid})")

    return {
        "status": "success",
        "filename": orig_filename,
        "recipient": recipient,
        "message": f"File *{orig_filename}* berhasil dikirimkan ke WhatsApp {recipient}.",
    }


@register_tool("move_vault_files")
async def handle_move_vault_files(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    """Dynamic tool to move 1 or many files to a destination folder, category, or owner."""
    target = args.get("target")
    if not target:
        # Fallback to legacy argument names if called
        target = args.get("query_or_file_ids") or args.get("file_id_or_name")

    if not target:
        return {"status": "error", "error": "target (nama file, ID, atau kata kunci pencarian) wajib diisi."}

    dest_dir = args.get("destination_directory") or args.get("new_directory")
    new_cat = args.get("new_category")
    new_own = args.get("new_owner")

    moved = move_vault_files(
        target=target,
        destination_dir=dest_dir,
        new_category=new_cat,
        new_owner=new_own,
    )
    if not moved:
        return {"status": "error", "error": f"Tidak ada file yang ditemukan atau dipindahkan untuk target '{target}'."}

    log_activity(f"Moved {len(moved)} vault file(s) for target: {target}")
    if len(moved) == 1:
        item = moved[0]
        return {
            "status": "success",
            "count": 1,
            "file": item,
            "message": f"File *{item['filename']}* berhasil dipindahkan ke *{item['relative_path']}*.",
        }
    return {
        "status": "success",
        "count": len(moved),
        "moved_files": moved,
        "message": f"Berhasil memindahkan {len(moved)} file ke folder *{dest_dir or new_cat}*.",
    }


@register_tool("delete_vault_files")
async def handle_delete_vault_files(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    """Dynamic tool to delete 1 or many files by ID, filename, or search query."""
    target = args.get("target")
    if not target:
        target = args.get("file_id_or_name") or args.get("query_or_file_ids")

    if not target:
        return {"status": "error", "error": "target (nama file, ID, atau kata kunci) wajib diisi."}

    deleted = delete_vault_files(target=target)
    if not deleted:
        return {"status": "error", "error": f"File '{target}' tidak ditemukan di brankas dokumen."}

    log_activity(f"Deleted {len(deleted)} vault file(s): {', '.join(deleted)}")
    if len(deleted) == 1:
        return {
            "status": "success",
            "count": 1,
            "deleted_files": deleted,
            "message": f"File *{deleted[0]}* berhasil dihapus dari brankas dokumen.",
        }
    return {
        "status": "success",
        "count": len(deleted),
        "deleted_files": deleted,
        "message": f"Berhasil menghapus {len(deleted)} file ({', '.join(deleted)}) dari brankas dokumen.",
    }


@register_tool("create_vault_directory")
async def handle_create_vault_directory(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    dir_path = str(args.get("directory_path", "")).strip()
    if not dir_path:
        return {"status": "error", "error": "directory_path tidak boleh kosong."}

    try:
        created = create_vault_directory(dir_path)
        log_activity(f"Created vault directory: {created}")
        return {
            "status": "success",
            "directory": created,
            "message": f"Direktori *{created}* berhasil dibuat di dalam brankas.",
        }
    except Exception as err:
        return {"status": "error", "error": str(err)}


@register_tool("delete_vault_directory")
async def handle_delete_vault_directory(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    dir_path = str(args.get("directory_path", "")).strip()
    recursive = bool(args.get("recursive", False))
    if not dir_path:
        return {"status": "error", "error": "directory_path tidak boleh kosong."}

    success, msg = delete_vault_directory(dir_path=dir_path, recursive=recursive)
    if success:
        log_activity(f"Deleted vault directory: {dir_path} (recursive={recursive})")
        return {"status": "success", "message": msg}
    return {"status": "error", "error": msg}
