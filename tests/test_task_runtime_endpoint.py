from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.contracts import ChatResponse, ModelTier, RetrievalResult, RouteDecision, TaskResponse, TaskType


class StubTaskEngine:
    async def run(self, task):
        response = TaskResponse(
            task_id=task.task_id,
            task_type=task.task_type,
            answer="Task execution complete.",
            confidence=0.82,
            route=RouteDecision(
                selected_tier=ModelTier.FLASH,
                provider="alibaba",
                model_name="qwen-turbo",
                reason="intent-based routing",
                escalation_depth=0,
                estimated_cost_usd=0.003,
            ),
            context_sources=["artifact:file:Inventory/InventoryManager.cs"],
            trace_id="trace-task-endpoint",
            pipeline=[
                {
                    "stage": "intent_analysis",
                    "status": "ok",
                    "took_ms": 1,
                    "details": {"task_type": task.task_type.value},
                }
            ],
            retrieval={"user_intent": "planning"},
        )
        return response, RetrievalResult(query=task.prompt, entries=[], took_ms=2, assembled={})


class StubQueryEngine:
    async def run(self, envelope):
        response = ChatResponse(
            request_id=envelope.request_id,
            answer="Legacy query engine response.",
            confidence=0.74,
            route=RouteDecision(
                selected_tier=ModelTier.LOCAL,
                provider="local",
                model_name="local-lite-v1",
                reason="legacy fallback",
                escalation_depth=0,
                estimated_cost_usd=0.0,
            ),
            context_sources=["memory:episodic:1"],
            trace_id="trace-chat-fallback",
        )
        return response, RetrievalResult(query=envelope.prompt, entries=[], took_ms=1, assembled={})


def test_task_execute_endpoint_returns_task_response() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(task_engine=StubTaskEngine())

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/tasks/execute",
            json={
                "project_id": "MMO",
                "user_id": "u1",
                "task_type": "planning",
                "prompt": "plan refactor for inventory",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["task_type"] == "planning"
        assert payload["route"]["provider"] == "alibaba"
        assert payload["pipeline"][0]["stage"] == "intent_analysis"
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")


def test_chat_endpoint_uses_legacy_query_engine_when_task_engine_is_missing() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(query_engine=StubQueryEngine())

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/chat",
            json={
                "project_id": "MMO",
                "user_id": "u1",
                "prompt": "legacy chat test",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answer"] == "Legacy query engine response."
        assert payload["route"]["selected_tier"] == ModelTier.LOCAL.value
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
