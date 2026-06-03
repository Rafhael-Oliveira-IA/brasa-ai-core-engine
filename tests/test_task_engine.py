from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.contracts import (
    ContextPacket,
    ModelTier,
    ProviderResponse,
    RetrievalResult,
    RouteDecision,
    TaskExecutionOptions,
    TaskRequest,
    TaskType,
)
from app.memory.repository import MemoryRepository
from app.task_engine import CognitiveTaskEngine


class StubContextBuilder:
    def build(self, envelope):
        packet = ContextPacket(provenance=["artifact:file:Inventory/InventoryManager.cs"])
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=5,
            assembled={
                "user_intent": "planning",
                "relevant_systems": ["Inventory"],
                "dependencies": ["ItemDatabase", "EventBus"],
                "risks": [],
                "hot_context": ["artifact:file:Inventory/InventoryManager.cs"],
                "compression": {
                    "selected_count": 1,
                    "dropped_count": 0,
                    "max_chars": 3500,
                    "used_chars": 128,
                },
            },
        )
        return packet, retrieval


class StubRouter:
    async def generate(self, *, envelope, context):
        response = ProviderResponse(
            answer="Plan ready with phases and risk controls.",
            confidence=0.86,
            provider="alibaba",
            model_name="qwen-plus",
            prompt_tokens=120,
            completion_tokens=140,
            total_tokens=260,
            cost_usd=0.006,
        )
        decision = RouteDecision(
            selected_tier=ModelTier.PLUS,
            provider="alibaba",
            model_name="qwen-plus",
            reason="confidence gate passed",
            escalation_depth=1,
            estimated_cost_usd=0.006,
        )
        return response, decision


class StubTelemetry:
    def __init__(self) -> None:
        self.retrieval_logged = 0
        self.route_logged = 0

    def new_trace_id(self) -> str:
        return "trace-task-1"

    def log_retrieval(self, **kwargs) -> None:
        self.retrieval_logged += 1

    def log_route(self, **kwargs) -> None:
        self.route_logged += 1


class StubReflection:
    def __init__(self) -> None:
        self.calls = 0

    def run_once(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(summary_entry_id="summary-1", duplicates_removed=0)


def test_task_engine_runs_pipeline_with_memory_and_reflection() -> None:
    with TemporaryDirectory() as temp_dir:
        repository = MemoryRepository(Path(temp_dir) / "memory.db")
        telemetry = StubTelemetry()
        reflection = StubReflection()

        engine = CognitiveTaskEngine(
            context_builder=StubContextBuilder(),
            router=StubRouter(),
            telemetry=telemetry,
            memory_repository=repository,
            reflection=reflection,
        )

        task = TaskRequest(
            project_id="MMO",
            user_id="u1",
            task_type=TaskType.PLANNING,
            prompt="plan phased migration for inventory and events",
            options=TaskExecutionOptions(persist_memory=True, run_reflection=True),
        )

        response, retrieval = asyncio.run(engine.run(task))

        assert response.task_type == TaskType.PLANNING
        assert response.trace_id == "trace-task-1"
        assert retrieval.assembled["user_intent"] == "planning"

        stage_names = [item.stage for item in response.pipeline]
        assert "intent_analysis" in stage_names
        assert "context_retrieval" in stage_names
        assert "graph_expansion" in stage_names
        assert "reasoning" in stage_names
        assert "memory_update" in stage_names
        assert "reflection" in stage_names

        stored = repository.search(project_id="MMO", user_id="u1", query="", limit=20)
        assert any("TaskType: planning" in item.content for item in stored)
        assert reflection.calls == 1
        assert telemetry.retrieval_logged == 1
        assert telemetry.route_logged == 1
