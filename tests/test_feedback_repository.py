from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import CognitiveFeedbackEntry, CognitiveFeedbackVerdict, CognitiveIssueTag
from app.feedback.repository import CognitiveFeedbackRepository


def test_feedback_repository_persists_and_summarizes_entries() -> None:
    with TemporaryDirectory() as temp_dir:
        repository = CognitiveFeedbackRepository(Path(temp_dir) / "memory.db")

        repository.add_entry(
            CognitiveFeedbackEntry(
                workspace_id="mmo_workspace",
                project_id="mmo_workspace::SERVIDOR - ORIGINAL",
                user_id="u1",
                query="how startup works",
                verdict=CognitiveFeedbackVerdict.INCORRECT,
                issues=[CognitiveIssueTag.HALLUCINATION, CognitiveIssueTag.RETRIEVAL_INCORRECT],
                notes="missed protocol files",
            )
        )
        repository.add_entry(
            CognitiveFeedbackEntry(
                workspace_id="mmo_workspace",
                project_id="mmo_workspace::SERVIDOR - ORIGINAL",
                user_id="u1",
                query="how actions xml works",
                verdict=CognitiveFeedbackVerdict.CORRECT,
                issues=[],
            )
        )

        recent = repository.list_recent(project_id="mmo_workspace::SERVIDOR - ORIGINAL", user_id="u1", limit=10)
        assert len(recent) == 2

        summary = repository.summarize(project_id="mmo_workspace::SERVIDOR - ORIGINAL", user_id="u1")
        assert summary["total"] == 2
        assert summary["verdict_counts"]["incorrect"] == 1
        assert summary["verdict_counts"]["correct"] == 1
        assert summary["issue_counts"]["hallucination"] == 1
