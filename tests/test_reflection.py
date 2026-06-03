from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import MemoryEntry, MemoryScope
from app.memory.repository import MemoryRepository
from app.reflection.nightly_reflection import ReflectionService


def test_reflection_compacts_duplicates_and_generates_summary() -> None:
    with TemporaryDirectory() as temp_dir:
        base_path = Path(temp_dir)
        repository = MemoryRepository(base_path / "memory.db")
        reflection = ReflectionService(repository=repository, report_dir=base_path / "reports")

        duplicate_content = "Incremental migration plan with measurable checkpoints"

        repository.add_entry(
            MemoryEntry(
                project_id="project-1",
                user_id="user-1",
                scope=MemoryScope.PROJECT,
                content=duplicate_content,
                tags=["seed"],
            )
        )
        repository.add_entry(
            MemoryEntry(
                project_id="project-1",
                user_id="user-1",
                scope=MemoryScope.PROJECT,
                content=duplicate_content,
                tags=["seed"],
            )
        )
        repository.add_entry(
            MemoryEntry(
                project_id="project-1",
                user_id="user-1",
                scope=MemoryScope.EPISODIC,
                content="Unique insight from last discussion",
                tags=["chat"],
            )
        )

        report = reflection.run_once(project_id="project-1", user_id="user-1")

        assert report.duplicates_removed >= 1
        assert report.scanned_entries >= 3

        entries = repository.list_recent(project_id="project-1", user_id="user-1", limit=20)
        assert any("Reflection summary" in entry.content for entry in entries)
