from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.contracts import ActionExecutionReport, ActionPlan, ActionRollbackReport, ActionStep, ActionType, RetrievalResult


class StubMemoryRepository:
    def add_entry(self, entry):
        return entry


class StubActionEngine:
    def plan(self, payload):
        plan = ActionPlan(
            plan_id=payload.plan_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            user_id=payload.user_id,
            prompt=payload.prompt,
            summary="stub plan",
            actions=[
                ActionStep(
                    type=ActionType.UPDATE_FILE,
                    target="app/task_engine.py",
                    intent="add new stage",
                )
            ],
        )
        retrieval = RetrievalResult(query=payload.prompt, entries=[], took_ms=1, assembled={})
        return plan, retrieval

    def execute(self, payload):
        return ActionExecutionReport(
            plan_id=payload.plan.plan_id,
            dry_run=payload.options.dry_run,
            applied=0,
            skipped=1,
            failed=0,
            changed_files=[],
        )

    def rollback(self, payload):
        return ActionRollbackReport(
            execution_id=payload.execution_id,
            restored_files=1,
            removed_files=0,
            skipped_files=0,
            notes=[],
        )


def test_action_plan_endpoint_returns_plan() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(
        action_engine=StubActionEngine(),
        memory_repository=StubMemoryRepository(),
    )

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/actions/plan",
            json={
                "project_id": "MMO",
                "user_id": "u1",
                "prompt": "add cooldown",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"] == "stub plan"
        assert payload["actions"][0]["target"] == "app/task_engine.py"
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")


def test_action_execute_endpoint_returns_execution_report() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(
        action_engine=StubActionEngine(),
        memory_repository=StubMemoryRepository(),
    )

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/actions/execute",
            json={
                "project_id": "MMO",
                "user_id": "u1",
                "plan": {
                    "plan_id": "plan-1",
                    "project_id": "MMO",
                    "user_id": "u1",
                    "prompt": "add cooldown",
                    "actions": [
                        {
                            "type": "update_file",
                            "target": "app/task_engine.py",
                            "intent": "add stage",
                        }
                    ],
                },
                "options": {
                    "dry_run": True,
                    "run_feedback_loop": False,
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["dry_run"] is True
        assert payload["applied"] == 0
        assert payload["skipped"] == 1
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")


def test_action_rollback_endpoint_returns_rollback_report() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(
        action_engine=StubActionEngine(),
        memory_repository=StubMemoryRepository(),
    )

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/actions/rollback",
            json={
                "project_id": "MMO",
                "user_id": "u1",
                "execution_id": "exec-12345678",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["execution_id"] == "exec-12345678"
        assert payload["restored_files"] == 1
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
