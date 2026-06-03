from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.contracts import CognitiveFeedbackEntry


class StubFeedbackRepository:
    def __init__(self) -> None:
        self.items: list[CognitiveFeedbackEntry] = []

    def add_entry(self, entry: CognitiveFeedbackEntry) -> CognitiveFeedbackEntry:
        self.items.append(entry)
        return entry

    def list_recent(self, *, limit: int, project_id: str | None = None, user_id: str | None = None):
        filtered = [
            item
            for item in self.items
            if (project_id is None or item.project_id == project_id)
            and (user_id is None or item.user_id == user_id)
        ]
        return list(reversed(filtered))[:limit]


class StubTelemetry:
    def __init__(self) -> None:
        self.logged = 0

    def new_trace_id(self) -> str:
        return "trace-feedback"

    def log_feedback(self, **kwargs) -> None:
        self.logged += 1


def test_feedback_endpoints_store_and_return_entries() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    feedback_repository = StubFeedbackRepository()
    telemetry = StubTelemetry()
    main_module.app.state.runtime = SimpleNamespace(
        feedback_repository=feedback_repository,
        telemetry=telemetry,
    )

    try:
        client = TestClient(main_module.app)

        create_response = client.post(
            "/v1/feedback",
            json={
                "workspace_id": "mmo_workspace",
                "project_id": "SERVIDOR - ORIGINAL",
                "user_id": "u1",
                "query": "how opcode routing works",
                "verdict": "incorrect",
                "issues": ["hallucination", "retrieval_incorrect"],
                "notes": "returned ui files only",
            },
        )
        recent_response = client.get(
            "/v1/feedback/recent?workspace_id=mmo_workspace&project_id=SERVIDOR+-+ORIGINAL&user_id=u1&limit=10"
        )

        assert create_response.status_code == 200
        assert recent_response.status_code == 200

        created = create_response.json()
        recent = recent_response.json()

        assert created["verdict"] == "incorrect"
        assert "hallucination" in created["issues"]
        assert telemetry.logged == 1
        assert len(recent["items"]) == 1
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
