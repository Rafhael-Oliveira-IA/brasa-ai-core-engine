from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.contracts import (
    OrchestratorDecisionState,
    OrchestratorMode,
    OrchestratorRunReport,
)


class StubOrchestrator:
    def __init__(self) -> None:
        self.payloads = []

    def run(self, payload):
        self.payloads.append(payload)
        return OrchestratorRunReport(
            run_id=payload.run_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            user_id=payload.user_id,
            mode=payload.mode,
            final_state=OrchestratorDecisionState.REQUIRES_APPROVAL,
            iterations=[],
            notes=["stub-orchestrator"],
        )


def test_orchestrator_run_endpoint_returns_report_and_scopes_project() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    stub = StubOrchestrator()
    main_module.app.state.runtime = SimpleNamespace(orchestrator=stub)

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/orchestrator/run",
            json={
                "workspace_id": "MMO Workspace",
                "project_id": "SERVIDOR - ORIGINAL",
                "user_id": "u1",
                "intent": "adicionar cooldown",
                "mode": "autopilot",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["final_state"] == OrchestratorDecisionState.REQUIRES_APPROVAL.value
        assert payload["mode"] == OrchestratorMode.AUTOPILOT.value

        assert len(stub.payloads) == 1
        scoped = stub.payloads[0]
        assert scoped.workspace_id == "mmo_workspace"
        assert scoped.project_id == "mmo_workspace::SERVIDOR - ORIGINAL"
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
