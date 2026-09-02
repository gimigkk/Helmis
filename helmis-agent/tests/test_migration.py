import json
from pathlib import Path

from src.memory.migrate import migrate_legacy_tasks
from src.memory.task_repository import TaskRepository


def test_legacy_migration_archives_source_and_preserves_rows(tmp_path: Path) -> None:
    source = tmp_path / "helmis_memory.json"
    database = tmp_path / "helmis.db"
    source.write_text(json.dumps({"tasks": [{"title": "Legacy task", "due": "Tomorrow"}]}))

    result = migrate_legacy_tasks(source, database)

    assert result["status"] == "migrated"
    assert result["imported"] == 1
    assert not source.exists()
    assert Path(str(result["archived_source"])).exists()
    assert [task["title"] for task in TaskRepository(str(database)).list_tasks()] == ["Legacy task"]
