from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.evaluation import EvaluationEngine


def _emit(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=True) + "\n")


def test_evaluation_engine_computes_quality_metrics_from_traces() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        trace_file = root / "traces.jsonl"
        report_dir = root / "evaluations"

        _emit(
            trace_file,
            {
                "request_id": "r1",
                "event_type": "retrieval.assembly",
                "payload": {
                    "project_id": "MMO",
                    "user_id": "u1",
                    "relevant_systems": ["Inventory"],
                    "dependencies_count": 2,
                    "risks": [],
                    "retrieval": {
                        "avg_context_score": 0.82,
                        "context_count": 3,
                        "dropped_by_budget": 0,
                        "used_chars": 3000,
                        "max_chars": 3500,
                    },
                },
            },
        )
        _emit(
            trace_file,
            {
                "request_id": "r2",
                "event_type": "retrieval.assembly",
                "payload": {
                    "project_id": "MMO",
                    "user_id": "u1",
                    "relevant_systems": [],
                    "dependencies_count": 3,
                    "risks": ["2 selected contexts may be stale (low freshness score)."],
                    "retrieval": {
                        "avg_context_score": 0.18,
                        "context_count": 0,
                        "dropped_by_budget": 2,
                        "used_chars": 600,
                        "max_chars": 3500,
                    },
                },
            },
        )
        _emit(
            trace_file,
            {
                "request_id": "r1",
                "event_type": "route.decision",
                "payload": {
                    "project_id": "MMO",
                    "user_id": "u1",
                    "reason": "confidence gate passed",
                    "confidence": 0.90,
                    "usage": {
                        "prompt_tokens": 120,
                        "completion_tokens": 160,
                        "total_tokens": 280,
                        "cost_usd": 0.005,
                    },
                    "retrieval": {
                        "avg_context_score": 0.82,
                        "context_count": 3,
                        "dropped_by_budget": 0,
                        "used_chars": 3000,
                        "max_chars": 3500,
                    },
                },
            },
        )
        _emit(
            trace_file,
            {
                "request_id": "r2",
                "event_type": "route.decision",
                "payload": {
                    "project_id": "MMO",
                    "user_id": "u1",
                    "reason": "confidence gate passed",
                    "confidence": 0.86,
                    "usage": {
                        "prompt_tokens": 80,
                        "completion_tokens": 100,
                        "total_tokens": 180,
                        "cost_usd": 0.003,
                    },
                    "retrieval": {
                        "avg_context_score": 0.10,
                        "context_count": 0,
                        "dropped_by_budget": 2,
                        "used_chars": 600,
                        "max_chars": 3500,
                    },
                },
            },
        )
        _emit(
            trace_file,
            {
                "request_id": "r2",
                "event_type": "cognitive.feedback",
                "payload": {
                    "project_id": "MMO",
                    "user_id": "u1",
                    "verdict": "incorrect",
                    "issues": ["hallucination", "xml_missing", "retrieval_incorrect"],
                },
            },
        )

        engine = EvaluationEngine(trace_file=trace_file, report_dir=report_dir)
        report = engine.run(project_id="MMO", user_id="u1", limit=100)

        assert report.sample_size == 5
        assert report.metrics["retrieval_precision"] > 0.0
        assert report.metrics["stale_context_rate"] > 0.0
        assert report.metrics["hallucination_rate"] > 0.0
        assert report.metrics["feedback_incorrect_rate"] > 0.0
        assert report.metrics["feedback_hallucination_rate"] > 0.0
        assert report.metrics["feedback_xml_missing_rate"] > 0.0
        assert report.totals["total_cost_usd"] == 0.008
        assert (report_dir / f"evaluation-{report.report_id}.json").exists()
