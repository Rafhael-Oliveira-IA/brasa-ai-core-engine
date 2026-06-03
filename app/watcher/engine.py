from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.contracts import WatcherCheckReport, WatcherFileEvent
from app.ingestion.scanner import ProjectScanner


class FileSystemWatcherEngine:
    def __init__(self, *, snapshot_root: Path, max_file_bytes: int = 300_000) -> None:
        self.snapshot_root = snapshot_root
        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        self.scanner = ProjectScanner(max_file_bytes=max_file_bytes)

    def check(self, *, project_path: Path) -> WatcherCheckReport:
        project_path = project_path.resolve()
        if not project_path.exists() or not project_path.is_dir():
            raise ValueError(f"project_path not found or not a folder: {project_path}")

        profile, scanned_files = self.scanner.scan(project_path)
        current = {item.path: item.hash for item in scanned_files}
        previous = self._load_snapshot(project_name=profile.project_name)
        previous_files: dict[str, str] = {
            str(path): str(hash_value)
            for path, hash_value in previous.get("files", {}).items()
        }

        created = {path for path in current if path not in previous_files}
        deleted = {path for path in previous_files if path not in current}
        modified = {
            path
            for path in current
            if path in previous_files and previous_files[path] != current[path]
        }

        renamed_pairs: list[tuple[str, str, str]] = []
        deleted_by_hash: dict[str, list[str]] = {}
        for deleted_path in sorted(deleted):
            hash_value = previous_files.get(deleted_path)
            if not hash_value:
                continue
            deleted_by_hash.setdefault(hash_value, []).append(deleted_path)

        resolved_created: set[str] = set()
        resolved_deleted: set[str] = set()

        for created_path in sorted(created):
            hash_value = current.get(created_path)
            if not hash_value:
                continue

            candidates = deleted_by_hash.get(hash_value, [])
            if not candidates:
                continue

            previous_path = candidates.pop(0)
            renamed_pairs.append((previous_path, created_path, hash_value))
            resolved_created.add(created_path)
            resolved_deleted.add(previous_path)

        created -= resolved_created
        deleted -= resolved_deleted

        events: list[WatcherFileEvent] = []
        for previous_path, current_path, hash_value in renamed_pairs:
            events.append(
                WatcherFileEvent(
                    event_type="renamed",
                    path=current_path,
                    previous_path=previous_path,
                    previous_hash=hash_value,
                    current_hash=hash_value,
                )
            )

        for path in sorted(created):
            events.append(
                WatcherFileEvent(
                    event_type="created",
                    path=path,
                    current_hash=current.get(path),
                )
            )

        for path in sorted(modified):
            events.append(
                WatcherFileEvent(
                    event_type="modified",
                    path=path,
                    previous_hash=previous_files.get(path),
                    current_hash=current.get(path),
                )
            )

        for path in sorted(deleted):
            events.append(
                WatcherFileEvent(
                    event_type="deleted",
                    path=path,
                    previous_hash=previous_files.get(path),
                )
            )

        self._save_snapshot(
            project_name=profile.project_name,
            project_path=project_path,
            files=current,
        )

        total_changes = len(created) + len(modified) + len(deleted) + len(renamed_pairs)
        notes = [
            "Watcher check completed.",
            "Use auto_rebuild to trigger incremental ingestion after changes.",
        ]
        if total_changes == 0:
            notes.append("No filesystem changes detected.")

        return WatcherCheckReport(
            project_name=profile.project_name,
            project_path=project_path.as_posix(),
            scanned_files=len(scanned_files),
            changes_detected=total_changes,
            created=len(created),
            modified=len(modified),
            deleted=len(deleted),
            renamed=len(renamed_pairs),
            events=events,
            notes=notes,
        )

    def _snapshot_path(self, *, project_name: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in project_name)
        return self.snapshot_root / f"{safe_name}.json"

    def _load_snapshot(self, *, project_name: str) -> dict:
        snapshot_path = self._snapshot_path(project_name=project_name)
        if not snapshot_path.exists():
            return {}

        try:
            return json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_snapshot(self, *, project_name: str, project_path: Path, files: dict[str, str]) -> None:
        snapshot_path = self._snapshot_path(project_name=project_name)
        payload = {
            "project_name": project_name,
            "project_path": project_path.as_posix(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        }
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
