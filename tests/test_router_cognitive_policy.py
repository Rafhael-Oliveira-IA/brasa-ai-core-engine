from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import ContextPacket, ModelTier, ProviderResponse, RequestEnvelope
from app.providers.base import BaseProvider
from app.router import AIRouter
from app.settings import Settings


class StubProvider(BaseProvider):
    def __init__(self, name: str, confidence: float) -> None:
        self.name = name
        self.confidence = confidence

    async def generate(self, *, prompt: str, context: ContextPacket, model_name: str) -> ProviderResponse:
        return ProviderResponse(
            answer=f"response from {self.name}",
            confidence=self.confidence,
            provider=self.name,
            model_name=model_name,
            prompt_tokens=20,
            completion_tokens=30,
            total_tokens=50,
            cost_usd=0.001,
        )


def build_settings(base_path: Path, *, budget: float = 0.20) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=base_path / "data",
        sqlite_path=base_path / "data" / "memory.db",
        trace_file=base_path / "data" / "traces.jsonl",
        reflection_dir=base_path / "data" / "reflection_reports",
        request_budget_usd=budget,
        alibaba_api_key="test-key",
    )


def test_router_uses_retrieval_intent_to_start_with_plus_tier() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir))
        local_provider = StubProvider(name="local", confidence=0.95)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.90)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="please redesign the architecture of inventory and economy",
            metadata={
                "retrieval": {
                    "user_intent": "architecture",
                    "dependencies": ["Inventory", "Economy", "Database"],
                    "context_packet": [{}, {}, {}],
                    "risks": [],
                }
            },
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.selected_tier == ModelTier.PLUS
        assert "architecture" in decision.reason.lower()


def test_router_cost_awareness_marks_estimated_cost() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir))
        local_provider = StubProvider(name="local", confidence=0.20)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.91)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="Need architecture migration plan with trade-off analysis",
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.selected_tier in {ModelTier.FLASH, ModelTier.PLUS}
        assert decision.estimated_cost_usd > 0.0
