from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module


class StubDiagnosticsEngine:
    def run(self, *, project_id: str | None, user_id: str | None):
        return {
            "project_id": project_id,
            "user_id": user_id,
            "failure_counts": {"xml_missing": 1},
            "recommendations": ["Increase XML boost"],
        }


def test_calibration_diagnostics_endpoint_returns_report() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(diagnostics_engine=StubDiagnosticsEngine())

    try:
        client = TestClient(main_module.app)
        response = client.post(
            "/v1/calibration/diagnostics?workspace_id=mmo_workspace&project_id=SERVIDOR+-+ORIGINAL&user_id=u1"
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["failure_counts"]["xml_missing"] == 1
        assert payload["recommendations"][0] == "Increase XML boost"
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
