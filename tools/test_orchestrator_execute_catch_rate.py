from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class RunResult:
    ok: bool
    payload: dict[str, Any]


def _post_json(client: httpx.Client, base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{base_url}{path}", json=payload)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response type for {path}: {type(data)!r}")
    return data


def run_case(
    *,
    base_url: str,
    workspace_id: str,
    project_id: str,
    user_id: str,
    delta: int,
    timeout_seconds: float,
) -> RunResult:
    intent = (
        "no arquivo data/scripts/systems/pokemon/pokeballs.lua, "
        f"aumente o catch rate das balls em +{delta} com patch minimo e seguro, "
        "sem alterar outras mecanicas"
    )

    orchestrator_payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "user_id": user_id,
        "intent": intent,
        "mode": "manual",
        "max_iterations": 1,
        "dry_run": False,
        "auto_execute_low_risk": True,
        "auto_execute_medium_risk": False,
        "allow_high_risk": False,
        "block_critical_risk": True,
        "run_reflection": False,
        "metadata": {
            "source": "python-e2e-test",
            "test_case": f"catch_rate_plus_{delta}",
        },
    }

    with httpx.Client(timeout=timeout_seconds) as client:
        orchestrator = _post_json(client, base_url, "/v1/orchestrator/run", orchestrator_payload)

        iterations = orchestrator.get("iterations", [])
        if not isinstance(iterations, list) or not iterations:
            return RunResult(
                ok=False,
                payload={
                    "stage": "plan",
                    "error": "No orchestrator iterations returned",
                    "orchestrator_final_state": orchestrator.get("final_state"),
                    "raw": orchestrator,
                },
            )

        first_iteration = iterations[0] if isinstance(iterations[0], dict) else {}
        plan = first_iteration.get("plan", {}) if isinstance(first_iteration, dict) else {}
        actions = plan.get("actions", []) if isinstance(plan, dict) else []

        if not isinstance(actions, list) or not actions:
            return RunResult(
                ok=False,
                payload={
                    "stage": "plan",
                    "error": "No actions generated in plan",
                    "orchestrator_final_state": orchestrator.get("final_state"),
                    "decision": first_iteration.get("decision"),
                    "plan_summary": plan.get("summary"),
                    "raw": orchestrator,
                },
            )

        execute_payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "user_id": user_id,
            "plan": plan,
            "options": {
                "dry_run": False,
                "allow_high_risk": False,
                "auto_rollback_on_error": True,
                "run_feedback_loop": False,
            },
        }

        execution = _post_json(client, base_url, "/v1/actions/execute", execute_payload)

    validation = execution.get("validation", {}) if isinstance(execution, dict) else {}
    results = execution.get("results", []) if isinstance(execution, dict) else []
    changed_files = execution.get("changed_files", []) if isinstance(execution, dict) else []
    first_action = actions[0] if isinstance(actions[0], dict) else {}

    summary = {
        "stage": "execute",
        "orchestrator_final_state": orchestrator.get("final_state"),
        "orchestrator_decision": (first_iteration.get("decision", {}) if isinstance(first_iteration, dict) else {}).get("state"),
        "orchestrator_reason": (first_iteration.get("decision", {}) if isinstance(first_iteration, dict) else {}).get("reason"),
        "plan_actions": len(actions),
        "plan_summary": plan.get("summary"),
        "first_action_type": first_action.get("type"),
        "first_action_target": first_action.get("target"),
        "first_action_patches": first_action.get("patches", []),
        "execution_id": execution.get("execution_id"),
        "execution_applied": execution.get("applied", 0),
        "execution_failed": execution.get("failed", 0),
        "validation_ok": validation.get("ok", False),
        "validation_issues": validation.get("issues", []),
        "changed_files": changed_files,
        "results": results,
    }

    ok = bool(summary["validation_ok"]) and int(summary["execution_failed"] or 0) == 0 and int(summary["execution_applied"] or 0) > 0
    return RunResult(ok=ok, payload=summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run orchestrator+execute E2E test for catch rate patch.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Runtime API base URL")
    parser.add_argument("--workspace-id", default="mmo_workspace")
    parser.add_argument("--project-id", default="SERVIDOR - ORIGINAL")
    parser.add_argument("--user-id", default="cognitive-user")
    parser.add_argument("--delta", type=int, default=2, help="Catch rate increment")
    parser.add_argument("--timeout", type=float, default=90.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    try:
        result = run_case(
            base_url=args.base_url.rstrip("/"),
            workspace_id=args.workspace_id,
            project_id=args.project_id,
            user_id=args.user_id,
            delta=args.delta,
            timeout_seconds=args.timeout,
        )
    except Exception as exc:
        error_payload = {
            "stage": "error",
            "message": str(exc),
        }
        print(json.dumps(error_payload, ensure_ascii=True, indent=2))
        raise SystemExit(1) from exc

    print(json.dumps(result.payload, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
