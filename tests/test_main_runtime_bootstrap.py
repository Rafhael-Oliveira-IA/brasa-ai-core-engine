from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.knowledge.models import KnowledgeSyncReport, KnowledgeTreeResponse


class StubKnowledgeCompiler:
    def __init__(self) -> None:
        self.sync_calls: list[tuple[bool, list[str] | None]] = []

    def sync(self, *, force: bool = False, include_extensions: list[str] | None = None) -> KnowledgeSyncReport:
        self.sync_calls.append((force, include_extensions))
        return KnowledgeSyncReport(
            finished_at=datetime.now(timezone.utc),
            scanned_files=0,
            changed_nodes=0,
            regenerated_nodes=0,
            removed_nodes=0,
            stale_nodes=0,
        )

    def tree(self) -> KnowledgeTreeResponse:
        return KnowledgeTreeResponse(nodes=[], stale_nodes=0)

    def stale_count(self) -> int:
        return 0


def test_runtime_is_bootstrapped_without_testclient_lifespan(monkeypatch) -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    if had_runtime:
        delattr(main_module.app.state, "runtime")

    compiler = StubKnowledgeCompiler()
    build_calls = {"count": 0}

    def fake_build_runtime(_settings: object) -> SimpleNamespace:
        build_calls["count"] += 1
        return SimpleNamespace(
            settings=SimpleNamespace(
                app_name="test",
                environment="test",
                enable_reflection_scheduler=False,
            ),
            knowledge_compiler=compiler,
        )

    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(main_module, "build_runtime", fake_build_runtime)

    try:
        client = TestClient(main_module.app)

        sync_response = client.post("/v1/knowledge/sync", json={})
        tree_response = client.get("/v1/knowledge/tree")

        assert sync_response.status_code == 200
        assert tree_response.status_code == 200
        assert build_calls["count"] == 1
        assert compiler.sync_calls == [(False, None)]
    finally:
        if hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
