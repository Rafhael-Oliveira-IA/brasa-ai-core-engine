from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.contracts import CognitiveFeedbackEntry, CognitiveFeedbackVerdict, CognitiveIssueTag


class CognitiveFeedbackRepository:
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
                CREATE TABLE IF NOT EXISTS cognitive_feedback (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    request_id TEXT,
                    verdict TEXT NOT NULL,
                    issues_json TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_scope_created
                ON cognitive_feedback(project_id, user_id, created_at DESC)
                """
            )
            conn.commit()

    def add_entry(self, entry: CognitiveFeedbackEntry) -> CognitiveFeedbackEntry:
        payload = entry.model_copy(update={"created_at": datetime.now(timezone.utc)})

        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO cognitive_feedback (
                    id,
                    workspace_id,
                    project_id,
                    user_id,
                    query,
                    request_id,
                    verdict,
                    issues_json,
                    notes,
                    provenance_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.id,
                    payload.workspace_id,
                    payload.project_id,
                    payload.user_id,
                    payload.query,
                    payload.request_id,
                    payload.verdict.value,
                    json.dumps([item.value for item in payload.issues], ensure_ascii=True),
                    payload.notes,
                    json.dumps(payload.provenance, ensure_ascii=True),
                    payload.created_at.isoformat(),
                ),
            )
            conn.commit()

        return payload

    def list_recent(
        self,
        *,
        limit: int = 200,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> list[CognitiveFeedbackEntry]:
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
            "SELECT * FROM cognitive_feedback"
            + where_clause
            + " ORDER BY created_at DESC LIMIT ?"
        )
        params.append(max(1, min(limit, 5000)))

        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._from_row(row) for row in rows]

    def summarize(
        self,
        *,
        project_id: str | None = None,
        user_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, object]:
        entries = self.list_recent(limit=limit, project_id=project_id, user_id=user_id)
        total = len(entries)

        verdict_counts: dict[str, int] = {
            CognitiveFeedbackVerdict.CORRECT.value: 0,
            CognitiveFeedbackVerdict.PARTIAL.value: 0,
            CognitiveFeedbackVerdict.INCORRECT.value: 0,
        }
        issue_counts: dict[str, int] = {}

        for entry in entries:
            verdict_counts[entry.verdict.value] = verdict_counts.get(entry.verdict.value, 0) + 1
            for issue in entry.issues:
                key = issue.value
                issue_counts[key] = issue_counts.get(key, 0) + 1

        top_issues = sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)[:8]

        return {
            "total": total,
            "verdict_counts": verdict_counts,
            "issue_counts": issue_counts,
            "top_issues": top_issues,
        }

    def _from_row(self, row: sqlite3.Row) -> CognitiveFeedbackEntry:
        issues_raw = json.loads(row["issues_json"])
        issues: list[CognitiveIssueTag] = []
        for value in issues_raw:
            try:
                issues.append(CognitiveIssueTag(value))
            except ValueError:
                continue

        return CognitiveFeedbackEntry(
            id=row["id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            query=row["query"],
            request_id=row["request_id"],
            verdict=CognitiveFeedbackVerdict(row["verdict"]),
            issues=issues,
            notes=row["notes"],
            provenance=json.loads(row["provenance_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
