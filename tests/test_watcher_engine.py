from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.watcher.engine import FileSystemWatcherEngine


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_watcher_detects_incremental_changes_and_rename() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project = root / "MMO"

        inventory = project / "Inventory" / "InventoryManager.cs"
        write_text(
            inventory,
            """
public class InventoryManager {
    public void AddItem() {}
}
""".strip(),
        )

        watcher = FileSystemWatcherEngine(snapshot_root=root / ".brasa" / "watchers")

        first = watcher.check(project_path=project)
        assert first.changes_detected == 1
        assert first.created == 1

        stable = watcher.check(project_path=project)
        assert stable.changes_detected == 0

        write_text(
            inventory,
            """
public class InventoryManager {
    public void AddItem() {}
    public void RemoveItem() {}
}
""".strip(),
        )

        modified = watcher.check(project_path=project)
        assert modified.changes_detected == 1
        assert modified.modified == 1

        renamed_target = project / "Inventory" / "InventoryService.cs"
        inventory.rename(renamed_target)

        renamed = watcher.check(project_path=project)
        assert renamed.renamed == 1
        assert renamed.changes_detected == 1

        event_types = {event.event_type for event in renamed.events}
        assert "renamed" in event_types
