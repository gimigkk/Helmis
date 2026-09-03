import json
from pathlib import Path

from src.memory.migrate import migrate_json_tasks
from src.memory.task_repository import TaskRepository


def test_json_migration_archives_source_and_preserves_rows(tmp_path: Path) -> None:
    source = tmp_path / "helmis_memory.json"
    database = tmp_path / "helmis.db"
    source.write_text(json.dumps({"tasks": [{"title": "Imported task", "due": "Tomorrow"}]}))

    result = migrate_json_tasks(source, database)

    assert result["status"] == "migrated"
    assert result["imported"] == 1
    assert not source.exists()
    assert Path(str(result["archived_source"])).exists()
    assert [task["title"] for task in TaskRepository(str(database)).list_tasks()] == ["Imported task"]
