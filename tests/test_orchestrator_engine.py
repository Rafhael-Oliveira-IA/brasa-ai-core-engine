from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import (
    ActionExecutionReport,
    ActionPlan,
    ActionRisk,
    ActionStep,
    ActionType,
    ContextPacket,
    EvaluationReport,
    OrchestratorDecisionState,
    OrchestratorMode,
    OrchestratorRunRequest,
    ReflectionReport,
    RetrievalResult,
)
from app.knowledge.models import KnowledgeSyncReport
from app.memory.repository import MemoryRepository
from app.orchestrator import CognitiveOrchestrator


class StubActionEngine:
    def __init__(self, plan: ActionPlan, execution: ActionExecutionReport) -> None:
        self.plan_payload = plan
        self.execution_payload = execution
        self.execute_calls = 0

    def plan(self, payload):
        retrieval = RetrievalResult(query=payload.prompt, entries=[], took_ms=1, assembled={})
        return self.plan_payload, retrieval

    def execute(self, payload):
        self.execute_calls += 1
        return self.execution_payload


class StubContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(provenance=["artifact:file:app/orchestrator.py"])
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=2,
            assembled={
                "user_intent": "architecture",
                "relevant_systems": ["ActionEngine", "Orchestrator"],
                "risks": [],
            },
        )
        return packet, retrieval


class StubIngestionPipeline:
    def __init__(self, output_projects_root: Path | None = None) -> None:
        self.output_projects_root = output_projects_root or Path(".")
        self.calls: list[dict[str, object]] = []

    def run(self, *, project_path: Path, force: bool, workspace_id: str):
        self.calls.append(
            {
                "project_path": project_path,
                "force": force,
                "workspace_id": workspace_id,
            }
        )
        return {
            "project_path": project_path.as_posix(),
            "force": force,
            "workspace_id": workspace_id,
        }


class StubKnowledgeCompiler:
    def sync(self, *, force: bool = False, include_extensions=None):
        return KnowledgeSyncReport(
            finished_at=datetime.now(timezone.utc),
            scanned_files=10,
            changed_nodes=2,
            regenerated_nodes=2,
            removed_nodes=0,
            stale_nodes=0,
        )

    def estimate_drift(self) -> int:
        return 0


class StubEvaluationEngine:
    def run(self, *, limit: int = 120, project_id: str | None = None, user_id: str | None = None):
        return EvaluationReport(
            project_id=project_id,
            user_id=user_id,
            sample_size=80,
            retrieval_samples=40,
            route_samples=40,
            metrics={
                "retrieval_precision": 0.74,
                "hallucination_rate": 0.08,
                "stale_context_rate": 0.12,
            },
            totals={"total_tokens": 1000.0},
            notes=["ok"],
        )


class StubReflection:
    def run_once(self, *, trigger: str = "manual", project_id: str | None = None, user_id: str | None = None):
        now = datetime.now(timezone.utc)
        return ReflectionReport(
            task_id="reflection-1",
            started_at=now,
            finished_at=now,
            scanned_entries=4,
            duplicates_removed=0,
            low_confidence_entries=0,
            summary_entry_id="mem-1",
            notes=["stable"],
        )


def test_orchestrator_manual_mode_requires_approval_without_execution() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")

        plan = ActionPlan(
            plan_id="plan-manual",
            workspace_id="brasa_ai_workspace",
            project_id="MMO",
            user_id="u1",
            prompt="create docs",
            actions=[
                ActionStep(
                    type=ActionType.CREATE_FILE,
                    target="docs/architecture-note.md",
                    intent="add architecture note",
                    risk=ActionRisk.LOW,
                    content="# Note\n",
                )
            ],
        )
        execution = ActionExecutionReport(
            plan_id="plan-manual",
            dry_run=False,
            applied=1,
            skipped=0,
            failed=0,
            changed_files=["docs/architecture-note.md"],
        )

        action_engine = StubActionEngine(plan=plan, execution=execution)
        orchestrator = CognitiveOrchestrator(
            action_engine=action_engine,
            context_builder=StubContextBuilder(),
            ingestion_pipeline=StubIngestionPipeline(),
            knowledge_compiler=StubKnowledgeCompiler(),
            evaluation_engine=StubEvaluationEngine(),
            reflection=StubReflection(),
            memory_repository=repository,
        )

        request = OrchestratorRunRequest(
            project_id="MMO",
            user_id="u1",
            intent="create docs",
            mode=OrchestratorMode.MANUAL,
        )

        report = orchestrator.run(request)

        assert report.final_state == OrchestratorDecisionState.REQUIRES_APPROVAL
        assert action_engine.execute_calls == 0
        assert len(report.iterations) == 1
        assert report.iterations[0].decision.state == OrchestratorDecisionState.REQUIRES_APPROVAL


def test_orchestrator_autopilot_executes_low_risk_and_runs_feedback_stages() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")

        plan = ActionPlan(
            plan_id="plan-auto",
            workspace_id="brasa_ai_workspace",
            project_id="MMO",
            user_id="u1",
            prompt="create docs",
            actions=[
                ActionStep(
                    type=ActionType.CREATE_FILE,
                    target="docs/autonomous-loop.md",
                    intent="document autonomous loop",
                    risk=ActionRisk.LOW,
                    content="# Autonomous Loop\n",
                )
            ],
        )
        execution = ActionExecutionReport(
            plan_id="plan-auto",
            dry_run=False,
            applied=1,
            skipped=0,
            failed=0,
            changed_files=["docs/autonomous-loop.md"],
        )

        action_engine = StubActionEngine(plan=plan, execution=execution)
        orchestrator = CognitiveOrchestrator(
            action_engine=action_engine,
            context_builder=StubContextBuilder(),
            ingestion_pipeline=StubIngestionPipeline(),
            knowledge_compiler=StubKnowledgeCompiler(),
            evaluation_engine=StubEvaluationEngine(),
            reflection=StubReflection(),
            memory_repository=repository,
        )

        request = OrchestratorRunRequest(
            project_id="MMO",
            user_id="u1",
            intent="create docs",
            mode=OrchestratorMode.AUTOPILOT,
            max_iterations=1,
            run_reflection=True,
        )

        report = orchestrator.run(request)

        assert report.final_state == OrchestratorDecisionState.AUTO_EXECUTE
        assert action_engine.execute_calls == 1
        assert len(report.iterations) == 1

        iteration = report.iterations[0]
        assert iteration.execution is not None
        assert iteration.execution.applied == 1
        assert iteration.context_refresh.get("context_count") == 0
        assert "knowledge_sync" in iteration.ingestion
        assert iteration.evaluation.get("gate", {}).get("status") == "healthy"
        assert iteration.reflection.get("task_id") == "reflection-1"

        stored = repository.list_recent(limit=5, project_id="MMO", user_id="u1")
        assert any("Orchestrator run" in item.content for item in stored)


def test_orchestrator_requires_approval_for_abstract_update_actions() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")

        plan = ActionPlan(
            plan_id="plan-abstract",
            workspace_id="brasa_ai_workspace",
            project_id="MMO",
            user_id="u1",
            prompt="update cooldown",
            actions=[
                ActionStep(
                    type=ActionType.UPDATE_FILE,
                    target="Inventory/InventoryManager.cs",
                    intent="add cooldown check",
                    risk=ActionRisk.MEDIUM,
                )
            ],
        )
        execution = ActionExecutionReport(
            plan_id="plan-abstract",
            dry_run=False,
            applied=0,
            skipped=1,
            failed=0,
            changed_files=[],
        )

        action_engine = StubActionEngine(plan=plan, execution=execution)
        orchestrator = CognitiveOrchestrator(
            action_engine=action_engine,
            context_builder=StubContextBuilder(),
            ingestion_pipeline=StubIngestionPipeline(),
            knowledge_compiler=StubKnowledgeCompiler(),
            evaluation_engine=StubEvaluationEngine(),
            reflection=StubReflection(),
            memory_repository=repository,
        )

        request = OrchestratorRunRequest(
            project_id="MMO",
            user_id="u1",
            intent="update cooldown",
            mode=OrchestratorMode.AUTOPILOT,
            auto_execute_medium_risk=True,
        )

        report = orchestrator.run(request)

        assert report.final_state == OrchestratorDecisionState.REQUIRES_APPROVAL
        assert action_engine.execute_calls == 0
        assert "explicit diff/content" in report.iterations[0].decision.reason.lower()


def test_orchestrator_resolves_project_path_from_artifacts_without_manual_input() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")

        source_project = root / "source" / "MMO"
        source_project.mkdir(parents=True, exist_ok=True)

        files_index = (
            root
            / "workspaces"
            / "mmo_workspace"
            / "MMO"
            / "raw"
            / "files_index.json"
        )
        files_index.parent.mkdir(parents=True, exist_ok=True)
        files_index.write_text(
            '{"project_path": "' + source_project.as_posix() + '"}',
            encoding="utf-8",
        )

        plan = ActionPlan(
            plan_id="plan-auto-path",
            workspace_id="mmo_workspace",
            project_id="mmo_workspace::MMO",
            user_id="u1",
            prompt="create docs",
            actions=[
                ActionStep(
                    type=ActionType.CREATE_FILE,
                    target="docs/path.md",
                    intent="add file",
                    risk=ActionRisk.LOW,
                    content="# path\n",
                )
            ],
        )
        execution = ActionExecutionReport(
            plan_id="plan-auto-path",
            dry_run=False,
            applied=1,
            skipped=0,
            failed=0,
            changed_files=["docs/path.md"],
        )

        ingestion = StubIngestionPipeline(output_projects_root=root)
        action_engine = StubActionEngine(plan=plan, execution=execution)
        orchestrator = CognitiveOrchestrator(
            action_engine=action_engine,
            context_builder=StubContextBuilder(),
            ingestion_pipeline=ingestion,
            knowledge_compiler=StubKnowledgeCompiler(),
            evaluation_engine=StubEvaluationEngine(),
            reflection=StubReflection(),
            memory_repository=repository,
        )

        request = OrchestratorRunRequest(
            workspace_id="mmo_workspace",
            project_id="MMO",
            user_id="u1",
            intent="create docs",
            mode=OrchestratorMode.AUTOPILOT,
            max_iterations=1,
        )

        report = orchestrator.run(request)

        assert report.final_state == OrchestratorDecisionState.AUTO_EXECUTE
        assert len(ingestion.calls) == 1
        assert ingestion.calls[0]["project_path"] == source_project
