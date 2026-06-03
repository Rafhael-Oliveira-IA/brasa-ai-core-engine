from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.contracts import MemoryEntry, MemoryScope


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_project_user_updated
                ON memory_entries(project_id, user_id, updated_at DESC)
                """
            )
            conn.commit()

    def add_entry(self, entry: MemoryEntry) -> MemoryEntry:
        now = datetime.now(timezone.utc)
        prepared = entry.model_copy(update={"updated_at": now})

        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO memory_entries (
                    id,
                    project_id,
                    user_id,
                    scope,
                    content,
                    tags_json,
                    confidence,
                    provenance_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prepared.id,
                    prepared.project_id,
                    prepared.user_id,
                    prepared.scope.value,
                    prepared.content,
                    json.dumps(prepared.tags),
                    prepared.confidence,
                    json.dumps(prepared.provenance),
                    prepared.created_at.isoformat(),
                    prepared.updated_at.isoformat(),
                ),
            )
            conn.commit()

        return prepared

    def search(
        self,
        *,
        project_id: str,
        user_id: str,
        query: str,
        limit: int = 8,
    ) -> list[MemoryEntry]:
        normalized_query = (query or "").strip().lower()

        clauses = ["project_id = ?", "user_id = ?"]
        params: list[object] = [project_id, user_id]

        if normalized_query:
            terms = [term for term in normalized_query.split() if len(term) >= 2][:6]
            if terms:
                term_clauses: list[str] = []
                for term in terms:
                    term_clauses.append("LOWER(content) LIKE ?")
                    params.append(f"%{term}%")
                clauses.append("(" + " OR ".join(term_clauses) + ")")

        sql = (
            "SELECT * FROM memory_entries "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        params.append(max(1, min(limit, 50)))

        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._from_row(row) for row in rows]

    def list_recent(
        self,
        *,
        limit: int = 200,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> list[MemoryEntry]:
        clauses: list[str] = []
        params: list[object] = []

        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)

        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)

        where_clause = ""
        if clauses:
            where_clause = " WHERE " + " AND ".join(clauses)

        sql = (
            "SELECT * FROM memory_entries"
            + where_clause
            + " ORDER BY updated_at DESC LIMIT ?"
        )
        params.append(max(1, min(limit, 1000)))

        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._from_row(row) for row in rows]

    def compact_duplicates(
        self,
        *,
        project_id: str | None = None,
        user_id: str | None = None,
        limit: int = 500,
    ) -> int:
        recent_entries = self.list_recent(limit=limit, project_id=project_id, user_id=user_id)

        seen: dict[str, str] = {}
        duplicate_ids: list[str] = []

        for entry in recent_entries:
            key = self._normalize_text(entry.content)
            if key in seen:
                duplicate_ids.append(entry.id)
            else:
                seen[key] = entry.id

        if not duplicate_ids:
            return 0

        placeholders = ",".join("?" for _ in duplicate_ids)
        sql = f"DELETE FROM memory_entries WHERE id IN ({placeholders})"

        with self._lock, closing(self._connect()) as conn:
            conn.execute(sql, duplicate_ids)
            conn.commit()

        return len(duplicate_ids)

    def _from_row(self, row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            scope=MemoryScope(row["scope"]),
            content=row["content"],
            tags=json.loads(row["tags_json"]),
            confidence=float(row["confidence"]),
            provenance=json.loads(row["provenance_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _normalize_text(self, value: str) -> str:
        return " ".join(value.lower().split())
