from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.contracts import MemoryEntry, MemoryScope, ReflectionReport, ReflectionTask
from app.memory.repository import MemoryRepository

if TYPE_CHECKING:
    from app.knowledge.compiler import KnowledgeCompiler


class ReflectionService:
    def __init__(
        self,
        repository: MemoryRepository,
        report_dir: Path,
        knowledge_compiler: KnowledgeCompiler | None = None,
    ) -> None:
        self.repository = repository
        self.report_dir = report_dir
        self.knowledge_compiler = knowledge_compiler
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def run_once(
        self,
        *,
        trigger: str = "manual",
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> ReflectionReport:
        task = ReflectionTask(trigger=trigger)

        scanned = self.repository.list_recent(
            limit=300,
            project_id=project_id,
            user_id=user_id,
        )
        duplicates_removed = self.repository.compact_duplicates(
            project_id=project_id,
            user_id=user_id,
            limit=500,
        )
        low_confidence_entries = sum(1 for entry in scanned if entry.confidence < 0.45)

        notes: list[str] = []
        if duplicates_removed:
            notes.append(f"Removed {duplicates_removed} duplicate memory entries.")
        if low_confidence_entries:
            notes.append(f"Found {low_confidence_entries} low-confidence entries for review.")

        if self.knowledge_compiler is not None:
            drift_count = self.knowledge_compiler.estimate_drift()
            if drift_count:
                notes.append(
                    f"Detected {drift_count} potential stale knowledge nodes; run /v1/knowledge/sync."
                )

        if not notes:
            notes.append("No anomalies detected in this cycle.")

        summary_text = "Reflection summary\n" + "\n".join(f"- {note}" for note in notes)
        summary_entry = MemoryEntry(
            project_id=project_id or "global",
            user_id=user_id or "system",
            scope=MemoryScope.PROJECT,
            content=summary_text,
            tags=["reflection", "summary"],
            confidence=0.72,
            provenance={
                "task_id": task.task_id,
                "trigger": trigger,
                "scanned_entries": len(scanned),
            },
        )
        summary_entry = self.repository.add_entry(summary_entry)

        finished_at = datetime.now(timezone.utc)
        report = ReflectionReport(
            task_id=task.task_id,
            started_at=task.started_at,
            finished_at=finished_at,
            scanned_entries=len(scanned),
            duplicates_removed=duplicates_removed,
            low_confidence_entries=low_confidence_entries,
            summary_entry_id=summary_entry.id,
            notes=notes,
        )

        report_file = self.report_dir / f"reflection-{task.task_id}.json"
        report_file.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

        return report

    async def run_forever(
        self,
        *,
        interval_minutes: int,
        stop_event: asyncio.Event,
    ) -> None:
        interval_seconds = max(60, interval_minutes * 60)

        while not stop_event.is_set():
            self.run_once(trigger="scheduled")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue
