from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json

from app.action_engine import CognitiveActionEngine
from app.context_builder import ContextBuilder
from app.contracts import (
    ActionExecuteRequest,
    ActionExecutionOptions,
    ActionPatchOperation,
    ActionPlan,
    ActionPlanRequest,
    ActionRollbackRequest,
    ActionStep,
    ActionType,
    ContextPacket,
    ModelTier,
    ProviderResponse,
    RetrievalResult,
    RouteDecision,
)
from app.ingestion.pipeline import ProjectIngestionPipeline
from app.memory.repository import MemoryRepository


class StubContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(provenance=["artifact:file:Inventory/InventoryManager.cs"])
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=4,
            assembled={
                "user_intent": "generation",
                "relevant_systems": ["Inventory"],
                "dependencies": ["Item"],
                "risks": [],
                "context_packet": [
                    {
                        "source": "artifact:file:Inventory/InventoryManager.cs",
                        "type": "artifact",
                        "score": 0.9,
                    },
                    {
                        "source": "artifact:file:Inventory/Item.cs",
                        "type": "artifact",
                        "score": 0.82,
                    },
                ],
            },
        )
        return packet, retrieval


class StubBallRateContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(provenance=["artifact:file:data/lib/newfunctions.lua"])
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=5,
            assembled={
                "user_intent": "generation",
                "relevant_systems": ["Pokemon"],
                "dependencies": ["getBallsRate"],
                "risks": [],
                "context_packet": [
                    {
                        "source": "artifact:file:data/lib/newfunctions.lua",
                        "type": "artifact",
                        "score": 0.93,
                    }
                ],
            },
        )
        return packet, retrieval


class StubModelAssistRouter:
    def __init__(self) -> None:
        self.calls = 0
        self.last_prompt = ""

    async def generate(self, *, envelope, context):
        self.calls += 1
        self.last_prompt = envelope.prompt
        payload = {
            "summary": "Model-assisted plan",
            "warnings": ["generated_by_alibaba"],
            "actions": [
                {
                    "type": "patch_file",
                    "target": "data/lib/core/newfunctions.lua",
                    "intent": "adjust catch rate parameter",
                    "risk": "medium",
                    "rationale": "pattern inferred from retrieved context",
                    "patches": [
                        {
                            "find": r"(?im)(catchRate\s*=\s*)(\d+(?:\.\d+)?)",
                            "replace": r"\g<1>40",
                            "replace_all": False,
                            "use_regex": True,
                        }
                    ],
                }
            ],
        }
        response = ProviderResponse(
            answer=json.dumps(payload, ensure_ascii=True),
            confidence=0.91,
            provider="alibaba",
            model_name="qwen-turbo",
            prompt_tokens=120,
            completion_tokens=150,
            total_tokens=270,
            cost_usd=0.004,
        )
        decision = RouteDecision(
            selected_tier=ModelTier.FLASH,
            provider="alibaba",
            model_name="qwen-turbo",
            reason="model-assisted planning",
            escalation_depth=0,
            estimated_cost_usd=0.004,
        )
        return response, decision


def test_action_planner_builds_actions_from_retrieval_context() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "Inventory").mkdir(parents=True, exist_ok=True)
        (root / "Inventory" / "InventoryManager.cs").write_text("public class InventoryManager {}", encoding="utf-8")

        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        request = ActionPlanRequest(
            project_id="MMO",
            user_id="u1",
            prompt="adiciona sistema de cooldown no inventory",
            max_actions=4,
        )

        plan, retrieval = engine.plan(request)

        assert retrieval.assembled["user_intent"] == "generation"
        assert len(plan.actions) >= 1
        assert plan.actions[0].target == "Inventory/InventoryManager.cs"


def test_action_planner_infers_ball_rate_patch_without_explicit_filename() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "data" / "lib").mkdir(parents=True, exist_ok=True)
        (root / "data" / "lib" / "newfunctions.lua").write_text(
            "local config = { ballRate = 25 }\n",
            encoding="utf-8",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubBallRateContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        plan, _ = engine.plan(
            ActionPlanRequest(
                project_id="MMO",
                user_id="u1",
                prompt="aumente o rate das balls para 40 sem alterar outros parametros",
            )
        )

        assert len(plan.actions) == 1
        action = plan.actions[0]
        assert action.target == "data/lib/newfunctions.lua"
        assert action.type == ActionType.PATCH_FILE
        assert action.patches
        assert action.patches[0].use_regex is True
        assert "40" in action.patches[0].replace


def test_action_planner_can_use_model_assist_for_generic_changes() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "data" / "lib" / "core").mkdir(parents=True, exist_ok=True)
        (root / "data" / "lib" / "core" / "newfunctions.lua").write_text(
            "local catchRate = 20\n",
            encoding="utf-8",
        )

        repository = MemoryRepository(root / "memory.db")
        router = StubModelAssistRouter()
        engine = CognitiveActionEngine(
            context_builder=StubBallRateContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
            router=router,
            model_assist_enabled=True,
            model_assist_tier="flash",
        )

        plan, _ = engine.plan(
            ActionPlanRequest(
                project_id="MMO",
                user_id="u1",
                prompt="vamos ajustar a captura em +40 sem quebrar o resto",
            )
        )

        assert router.calls == 1
        assert "Return ONLY valid JSON" in router.last_prompt
        assert plan.summary == "Model-assisted plan"
        assert len(plan.actions) == 1
        assert plan.actions[0].target == "data/lib/core/newfunctions.lua"
        assert plan.actions[0].patches
        assert plan.actions[0].patches[0].use_regex is True


def test_action_executor_updates_file_and_rollback_restores_original_content() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        target = root / "Inventory" / "InventoryManager.cs"
        target.parent.mkdir(parents=True, exist_ok=True)
        original_content = """
public class InventoryManager {
    public bool CanUse() {
        return true;
    }
}
""".strip()
        target.write_text(original_content, encoding="utf-8")

        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        plan = ActionPlan(
            plan_id="plan-1",
            workspace_id="brasa_ai_workspace",
            project_id="MMO",
            user_id="u1",
            prompt="add cooldown guard",
            actions=[
                ActionStep(
                    type=ActionType.PATCH_FILE,
                    target="Inventory/InventoryManager.cs",
                    intent="insert cooldown guard before allow",
                    patches=[
                        ActionPatchOperation(
                            find="return true;",
                            replace="if (isCoolingDown) { return false; }\n        return true;",
                        )
                    ],
                )
            ],
        )

        execute_request = ActionExecuteRequest(
            project_id="MMO",
            user_id="u1",
            plan=plan,
            options=ActionExecutionOptions(
                dry_run=False,
                allow_high_risk=True,
                run_feedback_loop=False,
            ),
        )

        report = engine.execute(execute_request)

        assert report.applied == 1
        assert report.failed == 0
        assert "isCoolingDown" in target.read_text(encoding="utf-8")

        rollback = engine.rollback(
            ActionRollbackRequest(
                project_id="MMO",
                user_id="u1",
                execution_id=report.execution_id,
            )
        )

        assert rollback.restored_files == 1
        assert "isCoolingDown" not in target.read_text(encoding="utf-8")


def test_action_executor_blocks_path_traversal_targets() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        plan = ActionPlan(
            plan_id="plan-bad-path",
            workspace_id="brasa_ai_workspace",
            project_id="MMO",
            user_id="u1",
            prompt="dangerous",
            actions=[
                ActionStep(
                    type=ActionType.UPDATE_FILE,
                    target="../outside.py",
                    intent="invalid target",
                    content="print('x')\n",
                )
            ],
        )

        report = engine.execute(
            ActionExecuteRequest(
                project_id="MMO",
                user_id="u1",
                plan=plan,
                options=ActionExecutionOptions(dry_run=False, allow_high_risk=True),
            )
        )

        assert report.applied == 0
        assert report.validation.ok is False
        assert any(issue.code == "invalid_target" for issue in report.validation.issues)


def test_action_executor_resolves_source_project_root_from_artifacts() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        runtime_root = root / "runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)

        source_project = root / "SERVIDOR - ORIGINAL"
        target_file = source_project / "data" / "scripts" / "systems" / "pokemon" / "pokeballs.lua"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(
            "local config = { ballRate = 25 }\n",
            encoding="utf-8",
        )

        ingestion = ProjectIngestionPipeline(output_projects_root=runtime_root / ".brasa")
        ingestion.run(project_path=source_project, workspace_id="mmo_workspace")

        repository = MemoryRepository(root / "memory.db")
        context_builder = ContextBuilder(
            memory_repository=repository,
            project_artifacts_root=runtime_root / ".brasa",
        )
        engine = CognitiveActionEngine(
            context_builder=context_builder,
            memory_repository=repository,
            workspace_root=runtime_root,
            backup_root=runtime_root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        plan = ActionPlan(
            plan_id="plan-artifact-root",
            workspace_id="mmo_workspace",
            project_id="mmo_workspace::SERVIDOR - ORIGINAL",
            user_id="u1",
            prompt="ajuste balls rate",
            actions=[
                ActionStep(
                    type=ActionType.PATCH_FILE,
                    target="data/scripts/systems/pokemon/pokeballs.lua",
                    intent="set ballRate to 40",
                    patches=[
                        ActionPatchOperation(
                            find="ballRate = 25",
                            replace="ballRate = 40",
                        )
                    ],
                )
            ],
        )

        report = engine.execute(
            ActionExecuteRequest(
                workspace_id="mmo_workspace",
                project_id="mmo_workspace::SERVIDOR - ORIGINAL",
                user_id="u1",
                plan=plan,
                options=ActionExecutionOptions(dry_run=False, allow_high_risk=True),
            )
        )

        assert report.applied == 1
        assert report.failed == 0
        assert "ballRate = 40" in target_file.read_text(encoding="utf-8")

        rollback = engine.rollback(
            ActionRollbackRequest(
                workspace_id="mmo_workspace",
                project_id="mmo_workspace::SERVIDOR - ORIGINAL",
                user_id="u1",
                execution_id=report.execution_id,
            )
        )

        assert rollback.restored_files == 1
        assert "ballRate = 25" in target_file.read_text(encoding="utf-8")


def test_action_executor_patches_bracketed_balls_rate_assignment() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        target = root / "data" / "lib" / "core" / "newfunctions.lua"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            (
                "local config = {}\n"
                "config[\"pokeballsRate\"] = 25\n"
                "config[\"catchRate\"] = 10\n"
            ),
            encoding="utf-8",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubBallRateContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        plan, _ = engine.plan(
            ActionPlanRequest(
                project_id="MMO",
                user_id="u1",
                prompt="ajuste o rate das balls para 40 sem alterar catch",
            )
        )

        plan = plan.model_copy(
            update={
                "actions": [
                    action.model_copy(update={"target": "data/lib/core/newfunctions.lua"})
                    for action in plan.actions
                ]
            }
        )

        report = engine.execute(
            ActionExecuteRequest(
                project_id="MMO",
                user_id="u1",
                plan=plan,
                options=ActionExecutionOptions(dry_run=False, allow_high_risk=True),
            )
        )

        assert report.applied == 1
        assert report.failed == 0
        changed = target.read_text(encoding="utf-8")
        assert "config[\"pokeballsRate\"] = 40" in changed
        assert "config[\"catchRate\"] = 10" in changed
