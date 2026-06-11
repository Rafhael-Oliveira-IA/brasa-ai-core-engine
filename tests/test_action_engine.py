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


class StubCatchRateContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(
            provenance=[
                "artifact:file:data/scripts/systems/pokemon/pokeballs.lua",
                "artifact:file:data/actions/scripts/poke/catch.lua",
            ]
        )
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=5,
            assembled={
                "user_intent": "generation",
                "relevant_systems": ["Pokemon"],
                "dependencies": ["getCatchChanceByLevel", "balls"],
                "risks": [],
                "context_packet": [
                    {
                        "source": "artifact:file:data/scripts/systems/pokemon/pokeballs.lua",
                        "type": "artifact",
                        "score": 0.91,
                    },
                    {
                        "source": "artifact:file:data/actions/scripts/poke/catch.lua",
                        "type": "artifact",
                        "score": 0.95,
                    },
                ],
            },
        )
        return packet, retrieval


class StubLootDropContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(
            provenance=[
                "artifact:file:data/actions/scripts/poke/catch.lua",
                "artifact:file:data/monster/arcanine.lua",
                "artifact:file:data/items/items.xml",
            ]
        )
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=5,
            assembled={
                "user_intent": "generation",
                "relevant_systems": ["Pokemon", "Loot"],
                "dependencies": ["monsterDrops", "items"],
                "risks": [],
                "context_packet": [
                    {
                        "source": "artifact:file:data/actions/scripts/poke/catch.lua",
                        "type": "artifact",
                        "score": 0.96,
                    },
                    {
                        "source": "artifact:file:data/monster/arcanine.lua",
                        "type": "artifact",
                        "score": 0.92,
                    },
                    {
                        "source": "artifact:file:data/items/items.xml",
                        "type": "artifact",
                        "score": 0.88,
                    },
                ],
            },
        )
        return packet, retrieval


class StubLootItemsContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(
            provenance=[
                "artifact:file:data/actions/scripts/poke/catch.lua",
                "artifact:file:data/items/items.xml",
            ]
        )
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=5,
            assembled={
                "user_intent": "generation",
                "relevant_systems": ["Pokemon", "Loot"],
                "dependencies": ["items"],
                "risks": [],
                "context_packet": [
                    {
                        "source": "artifact:file:data/actions/scripts/poke/catch.lua",
                        "type": "artifact",
                        "score": 0.97,
                    },
                    {
                        "source": "artifact:file:data/items/items.xml",
                        "type": "artifact",
                        "score": 0.89,
                    },
                ],
            },
        )
        return packet, retrieval


class StubLootScriptsOnlyContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(
            provenance=[
                "artifact:file:data/scripts/pokeprey/pokeprey_base.lua",
                "artifact:file:data/creaturescripts/scripts/basestone_drops.lua",
                "artifact:file:data/actions/scripts/poke/catch.lua",
            ]
        )
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=5,
            assembled={
                "user_intent": "general-query",
                "relevant_systems": ["data/creaturescripts", "data/scripts"],
                "dependencies": ["onKill", "onDropLoot"],
                "risks": ["item_context_missing"],
                "context_packet": [
                    {
                        "source": "artifact:file:data/scripts/pokeprey/pokeprey_base.lua",
                        "type": "artifact",
                        "score": 0.88,
                    },
                    {
                        "source": "artifact:file:data/creaturescripts/scripts/basestone_drops.lua",
                        "type": "artifact",
                        "score": 0.86,
                    },
                    {
                        "source": "artifact:file:data/actions/scripts/poke/catch.lua",
                        "type": "artifact",
                        "score": 0.84,
                    },
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


class StubModelAssistRouterWithNonMatchingPatch:
    async def generate(self, *, envelope, context):
        payload = {
            "summary": "Model-assisted plan",
            "warnings": ["generated_by_alibaba"],
            "actions": [
                {
                    "type": "patch_file",
                    "target": "data/scripts/systems/pokemon/pokeballs.lua",
                    "intent": "increase catch rate by +2",
                    "risk": "medium",
                    "rationale": "attempt patch in pokeballs",
                    "patches": [
                        {
                            "find": "-- Configuracoes de Catch Rate",
                            "replace": "-- Configuracoes de Catch Rate\nlocal CATCH_RATE_BONUS = 2",
                            "replace_all": False,
                            "use_regex": False,
                        }
                    ],
                }
            ],
        }
        response = ProviderResponse(
            answer=json.dumps(payload, ensure_ascii=True),
            confidence=0.89,
            provider="alibaba",
            model_name="qwen-turbo",
            prompt_tokens=120,
            completion_tokens=140,
            total_tokens=260,
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


class StubModelAssistRouterWithEmptyLootPatch:
    async def generate(self, *, envelope, context):
        payload = {
            "summary": "Adiciona fire stone ao drop do Arcanine",
            "warnings": ["generated_by_alibaba"],
            "actions": [
                {
                    "type": "patch_file",
                    "target": "data/actions/scripts/poke/catch.lua",
                    "intent": "Adicionar fire stone ao drop do Arcanine",
                    "risk": "medium",
                    "rationale": "modelo inferiu alvo incorreto",
                    "patches": [],
                    "content": None,
                }
            ],
        }
        response = ProviderResponse(
            answer=json.dumps(payload, ensure_ascii=True),
            confidence=0.88,
            provider="alibaba",
            model_name="qwen-plus-latest",
            prompt_tokens=180,
            completion_tokens=160,
            total_tokens=340,
            cost_usd=0.006,
        )
        decision = RouteDecision(
            selected_tier=ModelTier.PLUS,
            provider="alibaba",
            model_name="qwen-plus-latest",
            reason="model-assisted planning",
            escalation_depth=1,
            estimated_cost_usd=0.006,
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


def test_action_planner_repairs_non_matching_model_patch_for_catch_rate() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        pokeballs = root / "data" / "scripts" / "systems" / "pokemon" / "pokeballs.lua"
        catch_file = root / "data" / "actions" / "scripts" / "poke" / "catch.lua"
        pokeballs.parent.mkdir(parents=True, exist_ok=True)
        catch_file.parent.mkdir(parents=True, exist_ok=True)

        pokeballs.write_text(
            "function pokeball_doOnUse(player, item)\n    return true\nend\n",
            encoding="utf-8",
        )
        catch_file.write_text(
            (
                "local chanceBase = 10\n"
                "local ballKey = 'pokeball'\n"
                "local chance = chanceBase * balls[ballKey].chanceMultiplier\n"
            ),
            encoding="utf-8",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubCatchRateContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
            router=StubModelAssistRouterWithNonMatchingPatch(),
            model_assist_enabled=True,
            model_assist_tier="flash",
        )

        plan, _ = engine.plan(
            ActionPlanRequest(
                project_id="MMO",
                user_id="u1",
                prompt="aumente o catch rate das balls em +2 com patch minimo e seguro",
            )
        )

        assert len(plan.actions) == 1
        action = plan.actions[0]
        assert action.target == "data/actions/scripts/poke/catch.lua"
        assert action.type == ActionType.PATCH_FILE
        assert any("chance = chance + 2" in patch.replace for patch in action.patches)

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
        updated = catch_file.read_text(encoding="utf-8")
        assert "chance = chance + 2" in updated


def test_action_planner_prioritizes_loot_drop_target_and_applies_non_empty_patch_e2e() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        catch_file = root / "data" / "actions" / "scripts" / "poke" / "catch.lua"
        monster_file = root / "data" / "monster" / "arcanine.lua"
        items_file = root / "data" / "items" / "items.xml"

        catch_file.parent.mkdir(parents=True, exist_ok=True)
        monster_file.parent.mkdir(parents=True, exist_ok=True)
        items_file.parent.mkdir(parents=True, exist_ok=True)

        catch_file.write_text(
            "local chance = chanceBase * balls[ballKey].chanceMultiplier\n",
            encoding="utf-8",
        )
        monster_file.write_text(
            (
                "local drops = {\n"
                "    {name = \"heart stone\", chance = 4500},\n"
                "}\n"
            ),
            encoding="utf-8",
        )
        items_file.write_text("<items/>\n", encoding="utf-8")

        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubLootDropContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
        )

        prompt = "confere 3 arquivos e adiciona fire stone no loot/drop do arcanine sem mexer no catch"
        plan, _ = engine.plan(
            ActionPlanRequest(
                project_id="MMO",
                user_id="u1",
                prompt=prompt,
            )
        )

        assert len(plan.actions) == 1
        action = plan.actions[0]
        assert action.target == "data/monster/arcanine.lua"
        assert action.type == ActionType.PATCH_FILE
        assert action.patches

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

        updated_monster = monster_file.read_text(encoding="utf-8")
        assert "heart stone" in updated_monster
        assert "fire stone" in updated_monster

        unchanged_catch = catch_file.read_text(encoding="utf-8")
        assert "fire stone" not in unchanged_catch


def test_action_planner_loot_drop_prompt_variants_remain_stable_e2e() -> None:
    prompts = [
        "confere 3 arquivos e adicionar o loot correto do arcanine",
        "ajusta o drop do arcanine para incluir fire stone junto com heart stone",
        "pode dropar fire stone no loot do arcanine sem mexer no catch",
    ]

    for prompt in prompts:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catch_file = root / "data" / "actions" / "scripts" / "poke" / "catch.lua"
            monster_file = root / "data" / "monster" / "arcanine.lua"

            catch_file.parent.mkdir(parents=True, exist_ok=True)
            monster_file.parent.mkdir(parents=True, exist_ok=True)

            catch_file.write_text(
                "local chance = chanceBase * balls[ballKey].chanceMultiplier\n",
                encoding="utf-8",
            )
            monster_file.write_text(
                (
                    "local drops = {\n"
                    "    {name = \"heart stone\", chance = 4500},\n"
                    "}\n"
                ),
                encoding="utf-8",
            )

            repository = MemoryRepository(root / "memory.db")
            engine = CognitiveActionEngine(
                context_builder=StubLootDropContextBuilder(),
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
                    prompt=prompt,
                )
            )

            assert len(plan.actions) == 1
            action = plan.actions[0]
            assert action.target == "data/monster/arcanine.lua"
            assert action.type == ActionType.PATCH_FILE
            assert action.patches

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
            updated_monster = monster_file.read_text(encoding="utf-8")
            assert "heart stone" in updated_monster
            assert "fire stone" in updated_monster
            unchanged_catch = catch_file.read_text(encoding="utf-8")
            assert "fire stone" not in unchanged_catch


def test_action_planner_loot_drop_falls_back_to_items_xml_when_monster_missing_e2e() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        catch_file = root / "data" / "actions" / "scripts" / "poke" / "catch.lua"
        items_file = root / "data" / "items" / "items.xml"

        catch_file.parent.mkdir(parents=True, exist_ok=True)
        items_file.parent.mkdir(parents=True, exist_ok=True)

        catch_file.write_text(
            "local chance = chanceBase * balls[ballKey].chanceMultiplier\n",
            encoding="utf-8",
        )
        items_file.write_text(
            "<item name=\"heart stone\" chance=\"4500\" />\n",
            encoding="utf-8",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubLootItemsContextBuilder(),
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
                prompt="confere os arquivos e ajusta o loot correto para incluir fire stone",
            )
        )

        assert len(plan.actions) == 1
        action = plan.actions[0]
        assert action.target == "data/items/items.xml"
        assert action.type == ActionType.PATCH_FILE
        assert action.patches

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
        updated_items = items_file.read_text(encoding="utf-8")
        assert "heart stone" in updated_items
        assert "fire stone" in updated_items
        unchanged_catch = catch_file.read_text(encoding="utf-8")
        assert "fire stone" not in unchanged_catch


def test_action_planner_repairs_empty_model_loot_patch_and_avoids_missing_mutation() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        pokeprey_file = root / "data" / "scripts" / "pokeprey" / "pokeprey_base.lua"
        basestone_file = root / "data" / "creaturescripts" / "scripts" / "basestone_drops.lua"
        catch_file = root / "data" / "actions" / "scripts" / "poke" / "catch.lua"

        pokeprey_file.parent.mkdir(parents=True, exist_ok=True)
        basestone_file.parent.mkdir(parents=True, exist_ok=True)
        catch_file.parent.mkdir(parents=True, exist_ok=True)

        pokeprey_file.write_text("function onKill(player, target)\n    return true\nend\n", encoding="utf-8")
        basestone_file.write_text(
            (
                "function onKill(player, target)\n"
                "    local drops = {\n"
                "        {name = \"heart stone\", chance = 4500},\n"
                "    }\n"
                "    return true\n"
                "end\n"
            ),
            encoding="utf-8",
        )
        catch_file.write_text("function onCatch(player, ball)\n    return true\nend\n", encoding="utf-8")

        repository = MemoryRepository(root / "memory.db")
        engine = CognitiveActionEngine(
            context_builder=StubLootScriptsOnlyContextBuilder(),
            memory_repository=repository,
            workspace_root=root,
            backup_root=root / ".backups",
            blocked_path_prefixes=(".git", ".brasa"),
            allow_delete=False,
            max_file_bytes=200000,
            router=StubModelAssistRouterWithEmptyLootPatch(),
            model_assist_enabled=True,
            model_assist_tier="plus",
        )

        plan, _ = engine.plan(
            ActionPlanRequest(
                project_id="MMO",
                user_id="u1",
                prompt="o drop do arcanine esta com heart stone, precisamos adicionar fire stone",
            )
        )

        assert len(plan.actions) == 1
        action = plan.actions[0]
        assert action.target == "data/creaturescripts/scripts/basestone_drops.lua"
        assert action.type == ActionType.PATCH_FILE
        assert action.patches

        report = engine.execute(
            ActionExecuteRequest(
                project_id="MMO",
                user_id="u1",
                plan=plan,
                options=ActionExecutionOptions(dry_run=False, allow_high_risk=True),
            )
        )

        assert report.failed == 0
        assert report.applied == 1
        assert report.validation.ok is True
        assert not any(issue.code == "missing_mutation" for issue in report.validation.issues)

        updated_basestone = basestone_file.read_text(encoding="utf-8")
        assert "heart stone" in updated_basestone
        assert "fire stone" in updated_basestone
        unchanged_catch = catch_file.read_text(encoding="utf-8")
        assert "fire stone" not in unchanged_catch


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
