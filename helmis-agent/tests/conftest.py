"""Shared storage isolation for repository-backed tests."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give each test a fresh SQLite database and JSON sidecar directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("HELMIS_DB_PATH", str(data_dir / "helmis.db"))
    return data_dir
