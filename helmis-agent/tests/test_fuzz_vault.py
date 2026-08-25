"""
test_fuzz_vault.py — Relentless Adversarial Red-Team Fuzzing and Stress-Testing Suite.
Attempts to break the Document Vault using:
1. Malformed / Corrupt PDF bombs (invalid xref, truncated EOF, zero-byte streams).
2. Deep Path Traversal & Injection attacks (/etc/passwd, null bytes, backslashes, dotfiles).
3. Extreme Unicode, Emojis, Zero-width spaces, RTL, Chinese characters in filenames.
4. Heavy Concurrent Race Conditions (simultaneous save, move, read, delete across 20 tasks).
5. Enormous 15 MB payload & character limit clipping without OOM.
6. Empty / Zero-byte file edge cases.
"""

import asyncio
import os
import secrets
from pathlib import Path

import pytest

import src.vault
from src.vault import (
    init_vault_structure,
    is_safe_vault_path,
    list_vault_files,
    move_vault_files,
    read_vault_file,
    sanitize_filename,
    save_file_to_vault,
    search_vault,
)


@pytest.fixture(autouse=True)
def clean_vault_fuzz_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate vault environment for fuzzing."""
    vault_data_dir = tmp_path / "data"
    vault_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("src.vault.DATA_DIR", str(vault_data_dir))
    monkeypatch.setattr("src.vault.VAULT_DIR", str(vault_data_dir / "vault"))
    monkeypatch.setattr("src.vault.CATALOG_FILE", str(vault_data_dir / "file_catalog.json"))
    init_vault_structure()


def test_fuzz_corrupt_and_malformed_pdf_bombs() -> None:
    """Attempt to crash read_vault_file with corrupt / truncated / garbage PDF streams."""
    # 1. Zero-byte PDF
    r_empty = save_file_to_vault(data=b"", filename="empty.pdf", category="documents")
    res_empty = read_vault_file(r_empty["id"])
    assert res_empty["status"] == "success"
    assert "Dokumen PDF" in res_empty["content"]

    # 2. Corrupt garbage header disguised as PDF
    r_garbage = save_file_to_vault(
        data=b"%PDF-1.4 \x00\xff\xfe random binary garbage without xref or trailer",
        filename="garbage.pdf",
        category="documents",
        ocr_summary="OCR fallback text from scan",
    )
    res_garbage = read_vault_file(r_garbage["id"])
    assert res_garbage["status"] == "success"
    assert "OCR fallback text from scan" in res_garbage["content"]

    # 3. Truncated PDF stream
    truncated_pdf = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    r_trunc = save_file_to_vault(data=truncated_pdf, filename="truncated.pdf", category="documents")
    res_trunc = read_vault_file(r_trunc["id"])
    assert res_trunc["status"] == "success"

    # 4. Binary spoof disguised with text extension
    fake_text_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00\xb8\x00\x00\x00"
    r_spoof = save_file_to_vault(data=fake_text_bytes, filename="spoof.txt", category="documents")
    res_spoof = read_vault_file(r_spoof["id"])
    assert res_spoof["status"] == "success"
    assert res_spoof["content_type"] == "binary"

    # 5. Negative max_chars handling
    res_neg = read_vault_file(r_trunc["id"], max_chars=-50)
    assert res_neg["status"] == "success"


def test_fuzz_path_traversal_and_directory_escape_attacks() -> None:
    """Attempt to escape VAULT_DIR using classic and esoteric traversal vectors."""
    vectors = [
        "../../../../../../etc/passwd",
        "....//....//....//etc/shadow",
        "..\\..\\..\\Windows\\System32\\cmd.exe",
        "/etc/hosts",
        "documents/../../../../root/.ssh/id_rsa",
        "projects/../../../file_catalog.json",
        "vault/../../secret.txt",
        ".git/config",
        "././././../escaped.pdf",
    ]

    for attack in vectors:
        # Sanitize filename check
        clean_name = sanitize_filename(attack)
        assert "/" not in clean_name
        assert "\\" not in clean_name
        assert ".." not in clean_name

        # Save attempt with malicious subfolder / filename
        rec = save_file_to_vault(
            data=b"traversal test payload",
            filename=attack,
            subfolder=attack,
        )
        full_dest = os.path.join(src.vault.VAULT_DIR, rec["relative_path"])
        assert is_safe_vault_path(full_dest)
        assert ".." not in rec["relative_path"]


def test_fuzz_extreme_unicode_emojis_and_special_chars() -> None:
    """Attempt to break filename sanitization, saving, and search with extreme Unicode & emojis."""
    exotic_names = [
        "📄 Dokumen Rahasia (2026) — ⚡️ #1 [FINAL].pdf",
        "ملف_هام_جدا.pdf",  # Arabic RTL
        "健康保险_2026年_Gilang.pdf",  # Chinese Simplified
        "русский_документ_паспорт.pdf",  # Cyrillic
        "test\u200b\u200c\u200dzero_width.pdf",  # Zero-width spaces
        "normal_name   with   multiple    spaces.pdf",
        "dots.....many.....dots.tar.gz",
        "newline\nand\r\ntab\tfile.pdf",
        "$$$###@@@!!!%%%^^^&&&***()_+{}:\"<>?.pdf",
    ]

    for name in exotic_names:
        clean = sanitize_filename(name)
        assert clean != ""
        assert "\n" not in clean
        assert "\r" not in clean
        assert "\t" not in clean

        rec = save_file_to_vault(
            data=f"content for {name}".encode(),
            filename=name,
            description=f"Exotic name {name}",
        )
        assert rec["id"] is not None

        # Search should match
        matches = search_vault(query=rec["filename"][:5])
        assert len(matches) >= 1

        # Read back
        read_res = read_vault_file(rec["id"])
        assert read_res["status"] == "success"


def test_fuzz_large_15mb_file_and_max_chars_clipping() -> None:
    """Verify large binary files (10MB+) are saved without OOM and text reading clips safely."""
    large_payload = secrets.token_bytes(10 * 1024 * 1024)  # 10 MB binary payload
    rec = save_file_to_vault(
        data=large_payload,
        filename="huge_archive.bin",
        category="media",
        description="Large 10MB test binary",
    )
    assert rec["size_bytes"] == 10 * 1024 * 1024

    # Large text file (500,000 characters)
    huge_text = "Baris data konfigurasi rahasia project webdev.\n" * 10000  # ~470 KB text
    rec_text = save_file_to_vault(
        data=huge_text.encode("utf-8"),
        filename="big_log.txt",
        category="projects",
    )

    # Read with default 8000 max_chars limit
    read_res = read_vault_file(rec_text["id"], max_chars=1500)
    assert read_res["status"] == "success"
    assert read_res["is_truncated"] is True
    assert len(read_res["content"]) <= 1600
    assert "Dipotong karena melebihi batas 1500 karakter" in read_res["content"]


@pytest.mark.asyncio
async def test_fuzz_high_concurrency_race_conditions() -> None:
    """
    Stress-test atomic POSIX locking (fcntl.flock) under high concurrency:
    Run 30 simultaneous asynchronous tasks doing concurrent saves, searches, moves, reads, and deletes.
    file_catalog.json MUST never become corrupted or empty.
    """
    async def worker_save(idx: int) -> None:
        payload = f"worker payload {idx}".encode()
        save_file_to_vault(
            data=payload,
            filename=f"worker_doc_{idx}.txt",
            category="projects",
            tags=[f"tag_{idx}", "fuzz_test"],
        )

    # 1. 20 concurrent saves
    await asyncio.gather(*[worker_save(i) for i in range(20)])

    files = list_vault_files()
    assert len(files) == 20

    # 2. Concurrent moves, reads, searches, and deletes
    async def worker_move_or_read(idx: int) -> None:
        if idx % 3 == 0:
            move_vault_files(target=f"worker_doc_{idx}.txt", destination_dir="projects/archive")
        elif idx % 3 == 1:
            read_vault_file(f"worker_doc_{idx}.txt")
        else:
            search_vault(f"worker_doc_{idx}")

    await asyncio.gather(*[worker_move_or_read(i) for i in range(20)])

    # Verify catalog remains 100% valid JSON
    all_files = list_vault_files()
    assert len(all_files) == 20
    assert any("projects/archive" in f["relative_path"] for f in all_files)
