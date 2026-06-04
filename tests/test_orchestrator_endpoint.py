from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.action_engine import CognitiveActionEngine
from app.context_builder import ContextBuilder
from app.contracts import (
    ContextPacket,
    OrchestratorDecisionState,
    OrchestratorMode,
    OrchestratorRunReport,
    RetrievalResult,
)
from app.evaluation.engine import EvaluationEngine
from app.ingestion.pipeline import ProjectIngestionPipeline
from app.knowledge.models import KnowledgeSyncReport
from app.memory.repository import MemoryRepository
from app.orchestrator import CognitiveOrchestrator
from app.reflection.nightly_reflection import ReflectionService


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


class StubContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(provenance=["artifact:file:src/gameplay/system.lua"])
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=3,
            assembled={
                "user_intent": "generation",
                "relevant_systems": ["Gameplay"],
                "dependencies": ["CoolDownManager"],
                "risks": [],
                "context_packet": [],
            },
        )
        return packet, retrieval


class StubKnowledgeCompiler:
    def sync(self, *, force: bool = False, include_extensions=None):
        return KnowledgeSyncReport(
            finished_at=datetime.now(timezone.utc),
            scanned_files=5,
            changed_nodes=1,
            regenerated_nodes=1,
            removed_nodes=0,
            stale_nodes=0,
        )

    def estimate_drift(self) -> int:
        return 0


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


def test_orchestrator_run_endpoint_executes_full_agent_process() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_project = root / "source-project"
        source_project.mkdir(parents=True, exist_ok=True)
        (source_project / "README.md").write_text("# test project\n", encoding="utf-8")

        memory_repository = MemoryRepository(root / "memory.db")
        action_engine = CognitiveActionEngine(
            context_builder=StubContextBuilder(),
            memory_repository=memory_repository,
            workspace_root=source_project,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        ingestion_pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa")
        evaluation_engine = EvaluationEngine(
            trace_file=root / "traces.jsonl",
            report_dir=root / "evaluations",
        )
        reflection = ReflectionService(
            repository=memory_repository,
            report_dir=root / "reflection",
            knowledge_compiler=None,
            feedback_repository=None,
            diagnostics_engine=None,
        )

        orchestrator = CognitiveOrchestrator(
            action_engine=action_engine,
            context_builder=StubContextBuilder(),
            ingestion_pipeline=ingestion_pipeline,
            knowledge_compiler=StubKnowledgeCompiler(),
            evaluation_engine=evaluation_engine,
            reflection=reflection,
            memory_repository=memory_repository,
        )

        main_module.app.state.runtime = SimpleNamespace(orchestrator=orchestrator)

        try:
            client = TestClient(main_module.app)
            response = client.post(
                "/v1/orchestrator/run",
                json={
                    "workspace_id": "mmo_workspace",
                    "project_id": "MMO",
                    "user_id": "u1",
                    "intent": "create file docs/agent-route-e2e.md",
                    "mode": "autopilot",
                    "max_iterations": 1,
                    "project_path": str(source_project),
                    "dry_run": False,
                    "auto_execute_low_risk": True,
                    "auto_execute_medium_risk": False,
                    "allow_high_risk": False,
                    "block_critical_risk": True,
                    "run_reflection": True,
                },
            )

            assert response.status_code == 200
            payload = response.json()

            assert payload["final_state"] == OrchestratorDecisionState.AUTO_EXECUTE.value, payload
            assert payload["mode"] == OrchestratorMode.AUTOPILOT.value
            assert len(payload["iterations"]) == 1

            iteration = payload["iterations"][0]
            assert iteration["decision"]["state"] == OrchestratorDecisionState.AUTO_EXECUTE.value
            assert iteration["execution"]["applied"] == 1
            assert iteration["execution"]["failed"] == 0
            assert "docs/agent-route-e2e.md" in iteration["execution"]["changed_files"]

            assert "ingestion" in iteration["ingestion"]
            assert "knowledge_sync" in iteration["ingestion"]
            assert iteration["context_refresh"]["user_intent"] == "generation"
            assert "gate" in iteration["evaluation"]
            assert "task_id" in iteration["reflection"]

            created_file = source_project / "docs" / "agent-route-e2e.md"
            assert created_file.exists()
            assert "Auto-generated by BRASA Action Engine" in created_file.read_text(encoding="utf-8")

            recent_memory = memory_repository.list_recent(
                limit=30,
                project_id="mmo_workspace::MMO",
                user_id="u1",
            )
            assert any("Orchestrator run" in item.content for item in recent_memory)
        finally:
            if had_runtime:
                main_module.app.state.runtime = previous_runtime
            elif hasattr(main_module.app.state, "runtime"):
                delattr(main_module.app.state, "runtime")


def test_orchestrator_run_endpoint_updates_ball_rate_without_explicit_filename() -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_project = root / "SERVIDOR - ORIGINAL"
        target_file = source_project / "data" / "lib" / "core" / "newfunctions.lua"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(
            (
                "local config = {}\n"
                "config[\"pokeballsRate\"] = 25\n"
                "config[\"catchRate\"] = 10\n\n"
                "function getBallsRate()\n"
                "    return config[\"pokeballsRate\"]\n"
                "end\n\n"
                "function getCatchRate()\n"
                "    return config[\"catchRate\"]\n"
                "end\n"
            ),
            encoding="utf-8",
        )
        (source_project / "data" / "lib" / "other.lua").write_text(
            "function getSpawnRate() return 3 end\n",
            encoding="utf-8",
        )

        ingestion_pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa")
        ingestion_pipeline.run(project_path=source_project, workspace_id="mmo_workspace")

        memory_repository = MemoryRepository(root / "memory.db")
        context_builder = ContextBuilder(
            memory_repository=memory_repository,
            project_artifacts_root=root / ".brasa",
        )
        action_engine = CognitiveActionEngine(
            context_builder=context_builder,
            memory_repository=memory_repository,
            workspace_root=source_project,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        evaluation_engine = EvaluationEngine(
            trace_file=root / "traces.jsonl",
            report_dir=root / "evaluations",
        )
        reflection = ReflectionService(
            repository=memory_repository,
            report_dir=root / "reflection",
            knowledge_compiler=None,
            feedback_repository=None,
            diagnostics_engine=None,
        )

        orchestrator = CognitiveOrchestrator(
            action_engine=action_engine,
            context_builder=context_builder,
            ingestion_pipeline=ingestion_pipeline,
            knowledge_compiler=StubKnowledgeCompiler(),
            evaluation_engine=evaluation_engine,
            reflection=reflection,
            memory_repository=memory_repository,
        )

        main_module.app.state.runtime = SimpleNamespace(orchestrator=orchestrator)

        try:
            client = TestClient(main_module.app)
            prompt = "ajuste o rate das balls para 40 sem alterar o catchRate"
            response = client.post(
                "/v1/orchestrator/run",
                json={
                    "workspace_id": "mmo_workspace",
                    "project_id": "SERVIDOR - ORIGINAL",
                    "user_id": "u1",
                    "intent": prompt,
                    "mode": "autopilot",
                    "max_iterations": 1,
                    "dry_run": False,
                    "auto_execute_low_risk": True,
                    "auto_execute_medium_risk": True,
                    "allow_high_risk": False,
                    "block_critical_risk": True,
                    "run_reflection": True,
                },
            )

            assert response.status_code == 200
            payload = response.json()

            assert "newfunctions" not in prompt.lower()
            assert payload["final_state"] == OrchestratorDecisionState.AUTO_EXECUTE.value, payload
            assert len(payload["iterations"]) == 1

            iteration = payload["iterations"][0]
            assert iteration["execution"]["applied"] == 1
            assert iteration["execution"]["failed"] == 0
            assert "data/lib/core/newfunctions.lua" in iteration["execution"]["changed_files"]

            changed = target_file.read_text(encoding="utf-8")
            assert 'config["pokeballsRate"] = 40' in changed
            assert 'config["catchRate"] = 10' in changed
        finally:
            if had_runtime:
                main_module.app.state.runtime = previous_runtime
            elif hasattr(main_module.app.state, "runtime"):
                delattr(main_module.app.state, "runtime")
