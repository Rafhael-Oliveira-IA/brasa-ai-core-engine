from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import (
    ContextPacket,
    MemoryEntry,
    MemoryScope,
    ModelTier,
    ProviderResponse,
    RequestEnvelope,
    RetrievalResult,
    RouteDecision,
)
from app.memory.repository import MemoryRepository
from app.query_engine import CognitiveQueryEngine


class StubContextBuilder:
    def build(self, envelope: RequestEnvelope):
        packet = ContextPacket(provenance=["artifact:file:Inventory/InventoryManager.cs"])
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=[],
            took_ms=8,
            assembled={
                "user_intent": "refactor",
                "dependencies": ["ItemDatabase", "EventBus"],
                "contexts": [],
                "context_packet": [],
            },
        )
        return packet, retrieval


class StubRouter:
    def __init__(self) -> None:
        self.last_envelope = None

    async def generate(self, *, envelope: RequestEnvelope, context: ContextPacket):
        self.last_envelope = envelope
        response = ProviderResponse(
            answer="Refactor inventory in three safe phases.",
            confidence=0.84,
            provider="alibaba",
            model_name="qwen-plus",
            prompt_tokens=100,
            completion_tokens=120,
            total_tokens=220,
            cost_usd=0.004,
        )
        decision = RouteDecision(
            selected_tier=ModelTier.PLUS,
            provider="alibaba",
            model_name="qwen-plus",
            reason="confidence gate passed",
            estimated_cost_usd=0.004,
        )
        return response, decision


class StubTelemetry:
    def __init__(self) -> None:
        self.retrieval_logged = 0
        self.route_logged = 0

    def new_trace_id(self) -> str:
        return "trace-1"

    def log_retrieval(self, **kwargs) -> None:
        self.retrieval_logged += 1

    def log_route(self, **kwargs) -> None:
        self.route_logged += 1


def test_query_engine_runs_full_cognitive_flow() -> None:
    with TemporaryDirectory() as temp_dir:
        repository = MemoryRepository(Path(temp_dir) / "memory.db")
        telemetry = StubTelemetry()

        router = StubRouter()
        engine = CognitiveQueryEngine(
            context_builder=StubContextBuilder(),
            router=router,
            telemetry=telemetry,
            memory_repository=repository,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="refactor inventory",
        )

        response, retrieval = asyncio.run(engine.run(envelope))

        assert response.route.selected_tier == ModelTier.PLUS
        assert response.trace_id == "trace-1"
        assert retrieval.assembled["user_intent"] == "refactor"

        stored = repository.search(project_id="project-1", user_id="user-1", query="", limit=10)
        assert any("Request:" in item.content for item in stored)
        assert telemetry.retrieval_logged == 1
        assert telemetry.route_logged == 1
        assert router.last_envelope is not None
        assert router.last_envelope.metadata.get("task_type") == "chat"
        assert router.last_envelope.metadata.get("require_alibaba_final_response") is True
