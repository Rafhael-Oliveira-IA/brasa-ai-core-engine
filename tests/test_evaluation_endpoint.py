from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module


class StubEvaluationEngine:
    def run(self, *, limit: int, project_id: str | None, user_id: str | None):
        return {
            "report_id": "report-1",
            "generated_at": "2026-06-03T00:00:00+00:00",
            "project_id": project_id,
            "user_id": user_id,
            "sample_size": 2,
            "retrieval_samples": 1,
            "route_samples": 1,
            "metrics": {
                "retrieval_precision": 0.8,
                "hallucination_rate": 0.1,
                "stale_context_rate": 0.0,
                "architectural_consistency": 1.0,
                "token_efficiency": 0.7,
                "reasoning_success": 1.0,
            },
            "totals": {
                "total_cost_usd": 0.004,
                "prompt_tokens": 120,
                "completion_tokens": 140,
                "total_tokens": 260,
            },
            "notes": ["ok"],
        }

    def read_recent(self, *, limit: int):
        return [{"report_id": "report-1"}]


def test_evaluation_endpoints_return_reports() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    main_module.app.state.runtime = SimpleNamespace(evaluation_engine=StubEvaluationEngine())

    try:
        client = TestClient(main_module.app)

        run_response = client.post(
            "/v1/evaluation/run",
            json={
                "project_id": "MMO",
                "user_id": "u1",
                "limit": 100,
            },
        )
        recent_response = client.get("/v1/evaluation/recent?limit=5")

        assert run_response.status_code == 200
        assert recent_response.status_code == 200

        run_payload = run_response.json()
        recent_payload = recent_response.json()

        assert run_payload["report_id"] == "report-1"
        assert run_payload["metrics"]["retrieval_precision"] == 0.8
        assert recent_payload["items"][0]["report_id"] == "report-1"
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
