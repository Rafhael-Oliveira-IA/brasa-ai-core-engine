from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.calibration.diagnostics import CognitiveDiagnosticsEngine
from app.contracts import CognitiveFeedbackEntry, CognitiveFeedbackVerdict, CognitiveIssueTag
from app.feedback.repository import CognitiveFeedbackRepository


def test_cognitive_diagnostics_detects_failure_taxonomy_and_recommendations() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        trace_file = root / "traces.jsonl"
        output_dir = root / "calibration" / "failures"
        usage_dir = root / "evaluations" / "cognitive_usage"
        usage_dir.mkdir(parents=True, exist_ok=True)

        usage_jsonl = usage_dir / "cognitive-usage-20260603-000000.jsonl"
        usage_records = [
            {
                "prompt": "movements.xml register",
                "selected_count": 0,
                "xml_focus": True,
                "xml_selected": False,
                "relevant_systems": [],
                "dependencies": ["classic-action-bind"] * 30,
                "compression": {"dropped_count": 2200},
                "top_sources": ["artifact:file:data/scripts/talkactions/reset.lua"] * 6,
                "risks": ["Token budget dropped 2200 context candidates."],
            }
        ]
        usage_jsonl.write_text(
            "\n".join(json.dumps(item, ensure_ascii=True) for item in usage_records),
            encoding="utf-8",
        )

        feedback_repository = CognitiveFeedbackRepository(root / "memory.db")
        feedback_repository.add_entry(
            CognitiveFeedbackEntry(
                workspace_id="mmo_workspace",
                project_id="mmo_workspace::SERVIDOR - ORIGINAL",
                user_id="u1",
                query="how movement registration works",
                verdict=CognitiveFeedbackVerdict.INCORRECT,
                issues=[CognitiveIssueTag.XML_MISSING, CognitiveIssueTag.HALLUCINATION],
            )
        )

        engine = CognitiveDiagnosticsEngine(
            trace_file=trace_file,
            output_dir=output_dir,
            usage_dataset_dir=usage_dir,
            feedback_repository=feedback_repository,
        )

        report = engine.run(project_id="mmo_workspace::SERVIDOR - ORIGINAL", user_id="u1")

        counts = report["failure_counts"]
        assert counts["xml_missing"] > 0
        assert counts["compression_loss"] > 0
        assert counts["dependency_noise"] > 0
        assert counts["ranking_collision"] > 0
        assert counts["semantic_misdirection"] > 0
        assert report["recommendations"]
