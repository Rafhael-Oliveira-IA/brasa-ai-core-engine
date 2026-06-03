from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.contracts import ContextPacket, RetrievalResult


class StubContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(provenance=["artifact:file:Inventory/InventoryManager.cs"])
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=4,
            assembled={
                "query": envelope.prompt,
                "user_intent": "refactor",
                "relevant_systems": ["Inventory"],
                "dependencies": ["ItemDatabase", "EventBus"],
                "architecture_notes": ["graph_relations=uses:2"],
                "recent_changes": ["Inventory/InventoryManager.cs"],
                "risks": [],
                "context_packet": [],
                "contexts": [],
                "compression": {
                    "selected_count": 0,
                    "dropped_count": 0,
                    "max_chars": 3500,
                    "used_chars": 0,
                },
            },
        )
        return packet, retrieval


class StubTelemetry:
    def new_trace_id(self) -> str:
        return "trace-1"

    def log_retrieval(self, **kwargs) -> None:
        return None


def test_context_assemble_endpoint_returns_assembled_payload() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(
        context_builder=StubContextBuilder(),
        telemetry=StubTelemetry(),
    )

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/context/assemble",
            json={
                "project_id": "MMO",
                "user_id": "u1",
                "prompt": "refatore o inventory",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["retrieval"]["assembled"]["user_intent"] == "refactor"
        assert "Inventory" in payload["retrieval"]["assembled"]["relevant_systems"]
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
