from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.contracts import ActionPlan, ActionStep, ActionType, ModelTier, RetrievalResult, RouteDecision, TaskResponse, TaskType
from app.conversation.repository import ConversationRepository


class StubTaskEngine:
    async def run(self, task):
        response = TaskResponse(
            task_id=task.task_id,
            task_type=TaskType.CHAT,
            answer=f"assistant: {task.prompt}",
            confidence=0.88,
            route=RouteDecision(
                selected_tier=ModelTier.FLASH,
                provider="alibaba",
                model_name="qwen-turbo-latest",
                reason="conversation endpoint test",
                escalation_depth=0,
                estimated_cost_usd=0.004,
            ),
            context_sources=["artifact:file:app/main.py"],
            trace_id="trace-conversation-endpoint",
            pipeline=[],
            retrieval={},
        )
        return response, RetrievalResult(query=task.prompt, entries=[], took_ms=1, assembled={})


class StubActionEngine:
    def plan(self, payload):
        plan = ActionPlan(
            plan_id=payload.plan_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            user_id=payload.user_id,
            prompt=payload.prompt,
            summary="stub action plan",
            actions=[
                ActionStep(
                    type=ActionType.UPDATE_FILE,
                    target="app/router.py",
                    intent="tune routing policy",
                )
            ],
        )
        return plan, RetrievalResult(query=payload.prompt, entries=[], took_ms=1, assembled={})


class StubDiagnosticsEngine:
    def run(self, project_id: str | None = None, user_id: str | None = None):
        return {
            "failure_counts": {"hallucination": 1},
            "recommendations": ["raise retrieval precision"],
            "project_id": project_id,
            "user_id": user_id,
        }


def test_conversation_session_send_and_list_roundtrip(tmp_path: Path) -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(
        conversation_repository=ConversationRepository(tmp_path / "memory.db"),
        task_engine=StubTaskEngine(),
    )

    try:
        client = TestClient(main_module.app)

        create_response = client.post(
            "/v1/conversations/sessions",
            json={
                "workspace_id": "mmo_workspace",
                "project_id": "MMO",
                "user_id": "u1",
                "title": "Loot tuning",
            },
        )
        assert create_response.status_code == 200
        session = create_response.json()
        session_id = session["session_id"]

        send_response = client.post(
            f"/v1/conversations/{session_id}/send",
            json={
                "workspace_id": "mmo_workspace",
                "project_id": "MMO",
                "user_id": "u1",
                "prompt": "increase catch rate by +2",
            },
        )
        assert send_response.status_code == 200
        send_payload = send_response.json()
        assert send_payload["user_message"]["role"] == "user"
        assert send_payload["assistant_message"]["role"] == "assistant"
        assert send_payload["task"]["route"]["provider"] == "alibaba"

        sessions_response = client.get(
            "/v1/conversations/sessions",
            params={
                "workspace_id": "mmo_workspace",
                "project_id": "MMO",
                "user_id": "u1",
            },
        )
        assert sessions_response.status_code == 200
        sessions_payload = sessions_response.json()
        assert len(sessions_payload["items"]) == 1
        assert sessions_payload["items"][0]["last_message_at"] is not None

        messages_response = client.get(
            f"/v1/conversations/{session_id}/messages",
            params={
                "workspace_id": "mmo_workspace",
                "project_id": "MMO",
                "user_id": "u1",
            },
        )
        assert messages_response.status_code == 200
        messages_payload = messages_response.json()
        assert [item["role"] for item in messages_payload["items"]] == ["user", "assistant"]
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")


def test_conversation_send_returns_404_for_unknown_session(tmp_path: Path) -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(
        conversation_repository=ConversationRepository(tmp_path / "memory.db"),
        task_engine=StubTaskEngine(),
    )

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/conversations/unknown-session/send",
            json={
                "workspace_id": "mmo_workspace",
                "project_id": "MMO",
                "user_id": "u1",
                "prompt": "hello",
            },
        )

        assert response.status_code == 404
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")


def test_conversation_send_supports_core_commands(tmp_path: Path) -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(
        conversation_repository=ConversationRepository(tmp_path / "memory.db"),
        task_engine=StubTaskEngine(),
        action_engine=StubActionEngine(),
        diagnostics_engine=StubDiagnosticsEngine(),
    )

    try:
        client = TestClient(main_module.app)

        create_response = client.post(
            "/v1/conversations/sessions",
            json={
                "workspace_id": "mmo_workspace",
                "project_id": "MMO",
                "user_id": "u1",
                "title": "Core commands",
            },
        )
        assert create_response.status_code == 200
        session_id = create_response.json()["session_id"]

        action_plan_response = client.post(
            f"/v1/conversations/{session_id}/send",
            json={
                "workspace_id": "mmo_workspace",
                "project_id": "MMO",
                "user_id": "u1",
                "prompt": "generate a safe action plan",
                "command": "action_plan",
            },
        )
        assert action_plan_response.status_code == 200
        action_plan_payload = action_plan_response.json()
        assert action_plan_payload["operation"] == "action_plan"
        assert action_plan_payload["task"] is None
        assert action_plan_payload["operation_result"]["plan"]["actions"][0]["target"] == "app/router.py"

        diagnostics_response = client.post(
            f"/v1/conversations/{session_id}/send",
            json={
                "workspace_id": "mmo_workspace",
                "project_id": "MMO",
                "user_id": "u1",
                "prompt": "run diagnostics",
                "command": "diagnostics",
            },
        )
        assert diagnostics_response.status_code == 200
        diagnostics_payload = diagnostics_response.json()
        assert diagnostics_payload["operation"] == "diagnostics"
        assert diagnostics_payload["operation_result"]["diagnostics"]["failure_counts"]["hallucination"] == 1
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
