from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.contracts import (
    ConversationMessage,
    ConversationMessageRole,
    ConversationSession,
    RouteDecision,
)


class ConversationRepository:
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
                CREATE TABLE IF NOT EXISTS conversation_sessions (
                    session_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    archived INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_message_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    request_id TEXT,
                    trace_id TEXT,
                    route_json TEXT NOT NULL,
                    context_sources_json TEXT NOT NULL,
                    confidence REAL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_sessions_project_user_updated
                ON conversation_sessions(project_id, user_id, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_created
                ON conversation_messages(session_id, created_at ASC)
                """
            )
            conn.commit()

    def create_session(self, session: ConversationSession) -> ConversationSession:
        now = datetime.now(timezone.utc)
        title = (session.title or "").strip() or "New Conversation"
        prepared = session.model_copy(update={"title": title, "updated_at": now})

        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO conversation_sessions (
                    session_id,
                    workspace_id,
                    project_id,
                    user_id,
                    title,
                    metadata_json,
                    archived,
                    created_at,
                    updated_at,
                    last_message_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prepared.session_id,
                    prepared.workspace_id,
                    prepared.project_id,
                    prepared.user_id,
                    prepared.title,
                    json.dumps(prepared.metadata),
                    1 if prepared.archived else 0,
                    prepared.created_at.isoformat(),
                    prepared.updated_at.isoformat(),
                    prepared.last_message_at.isoformat() if prepared.last_message_at else None,
                ),
            )
            conn.commit()

        return prepared

    def get_session(
        self,
        *,
        session_id: str,
        project_id: str,
        user_id: str,
    ) -> ConversationSession | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM conversation_sessions
                WHERE session_id = ? AND project_id = ? AND user_id = ?
                """,
                (session_id, project_id, user_id),
            ).fetchone()

        if row is None:
            return None
        return self._session_from_row(row)

    def list_sessions(
        self,
        *,
        project_id: str,
        user_id: str,
        limit: int = 40,
    ) -> list[ConversationSession]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversation_sessions
                WHERE project_id = ? AND user_id = ?
                ORDER BY COALESCE(last_message_at, updated_at) DESC, updated_at DESC
                LIMIT ?
                """,
                (project_id, user_id, max(1, min(limit, 200))),
            ).fetchall()

        return [self._session_from_row(row) for row in rows]

    def add_message(self, message: ConversationMessage) -> ConversationMessage:
        prepared = message.model_copy()

        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages (
                    message_id,
                    session_id,
                    workspace_id,
                    project_id,
                    user_id,
                    role,
                    content,
                    request_id,
                    trace_id,
                    route_json,
                    context_sources_json,
                    confidence,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prepared.message_id,
                    prepared.session_id,
                    prepared.workspace_id,
                    prepared.project_id,
                    prepared.user_id,
                    prepared.role.value,
                    prepared.content,
                    prepared.request_id,
                    prepared.trace_id,
                    json.dumps(prepared.route.model_dump(mode="json") if prepared.route else {}),
                    json.dumps(prepared.context_sources),
                    prepared.confidence,
                    json.dumps(prepared.metadata),
                    prepared.created_at.isoformat(),
                ),
            )
            conn.execute(
                """
                UPDATE conversation_sessions
                SET updated_at = ?, last_message_at = ?
                WHERE session_id = ? AND project_id = ? AND user_id = ?
                """,
                (
                    prepared.created_at.isoformat(),
                    prepared.created_at.isoformat(),
                    prepared.session_id,
                    prepared.project_id,
                    prepared.user_id,
                ),
            )
            conn.commit()

        return prepared

    def list_messages(
        self,
        *,
        session_id: str,
        project_id: str,
        user_id: str,
        limit: int = 300,
    ) -> list[ConversationMessage]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT m.*
                FROM conversation_messages m
                JOIN conversation_sessions s ON s.session_id = m.session_id
                WHERE m.session_id = ? AND s.project_id = ? AND s.user_id = ?
                ORDER BY m.created_at ASC
                LIMIT ?
                """,
                (session_id, project_id, user_id, max(1, min(limit, 1000))),
            ).fetchall()

        return [self._message_from_row(row) for row in rows]

    def _session_from_row(self, row: sqlite3.Row) -> ConversationSession:
        raw_last_message = row["last_message_at"]
        return ConversationSession(
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            title=row["title"],
            metadata=json.loads(row["metadata_json"]),
            archived=bool(row["archived"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_message_at=(datetime.fromisoformat(raw_last_message) if raw_last_message else None),
        )

    def _message_from_row(self, row: sqlite3.Row) -> ConversationMessage:
        route_payload = json.loads(row["route_json"]) if row["route_json"] else {}
        route = RouteDecision.model_validate(route_payload) if route_payload else None

        return ConversationMessage(
            message_id=row["message_id"],
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            role=ConversationMessageRole(row["role"]),
            content=row["content"],
            request_id=row["request_id"],
            trace_id=row["trace_id"],
            route=route,
            context_sources=json.loads(row["context_sources_json"]),
            confidence=(float(row["confidence"]) if row["confidence"] is not None else None),
            metadata=json.loads(row["metadata_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )