from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.action_engine import CognitiveActionEngine
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
    RetrievalResult,
)
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
