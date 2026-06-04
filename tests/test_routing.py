from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import ContextPacket, ModelTier, ProviderResponse, RequestEnvelope
from app.providers.base import BaseProvider, ProviderUnavailable
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
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_usd=0.0,
        )


class RecordingProvider(BaseProvider):
    def __init__(self, name: str, confidence: float) -> None:
        self.name = name
        self.confidence = confidence
        self.prompts: list[str] = []

    async def generate(self, *, prompt: str, context: ContextPacket, model_name: str) -> ProviderResponse:
        self.prompts.append(prompt)
        return ProviderResponse(
            answer=f"response from {self.name}",
            confidence=self.confidence,
            provider=self.name,
            model_name=model_name,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_usd=0.0,
        )


class FailingProvider(BaseProvider):
    def __init__(self, name: str) -> None:
        self.name = name

    async def generate(self, *, prompt: str, context: ContextPacket, model_name: str) -> ProviderResponse:
        raise ProviderUnavailable("provider unavailable")


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


def test_router_escalates_to_flash_when_local_confidence_is_low() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir))
        local_provider = StubProvider(name="local", confidence=0.30)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.92)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="Need architecture migration plan with clear trade-off analysis",
        )

        response, decision = asyncio.run(
            router.generate(envelope=envelope, context=ContextPacket())
        )

        assert decision.selected_tier == ModelTier.FLASH
        assert decision.provider == "alibaba"
        assert response.confidence == 0.92


def test_router_respects_budget_and_falls_back_to_local() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir), budget=0.0001)
        local_provider = StubProvider(name="local", confidence=0.30)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.95)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="Architecture trade-off and migration strategy request",
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.selected_tier == ModelTier.LOCAL
        assert "budget" in decision.reason.lower()


def test_router_chat_policy_forces_alibaba_even_when_local_would_suffice() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir))
        local_provider = StubProvider(name="local", confidence=0.99)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.85)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="quick chat",
            metadata={"task_type": "chat"},
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.provider == "alibaba"
        assert decision.selected_tier != ModelTier.LOCAL


def test_router_chat_uses_local_draft_but_keeps_alibaba_as_final_response() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir))
        local_provider = RecordingProvider(name="local", confidence=0.99)
        alibaba_provider = RecordingProvider(name="alibaba", confidence=0.85)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="explica o impacto da refatoracao no inventario",
            metadata={
                "task_type": "chat",
                "retrieval": {
                    "user_intent": "refactor",
                    "relevant_systems": ["Inventory", "EventBus"],
                    "dependencies": ["ItemDatabase", "EventBus"],
                    "risks": ["state divergence"],
                },
            },
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.provider == "alibaba"
        assert len(local_provider.prompts) == 1
        assert len(alibaba_provider.prompts) >= 1
        assert "Local retrieval summary:" in alibaba_provider.prompts[0]
        assert "Local draft (optional, may be incomplete):" in alibaba_provider.prompts[0]
        assert "Output contract (mandatory):" in alibaba_provider.prompts[0]
        assert "Do not invent formulas" in alibaba_provider.prompts[0]


def test_router_non_chat_alibaba_requirement_skips_chat_local_draft() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir))
        local_provider = RecordingProvider(name="local", confidence=0.99)
        alibaba_provider = RecordingProvider(name="alibaba", confidence=0.90)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="action planning with strict json output",
            metadata={
                "task_type": "action_planning",
                "require_alibaba_final_response": True,
            },
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.provider == "alibaba"
        assert len(local_provider.prompts) == 0
        assert len(alibaba_provider.prompts) == 1
        assert "Local draft (optional, may be incomplete):" not in alibaba_provider.prompts[0]


def test_router_chat_policy_does_not_fallback_to_local_when_alibaba_is_unavailable() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir))
        local_provider = StubProvider(name="local", confidence=0.99)
        alibaba_provider = FailingProvider(name="alibaba")

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="quick chat",
            metadata={"task_type": "chat"},
        )

        try:
            asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))
        except ProviderUnavailable as exc:
            assert "external-chat-required" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected ProviderUnavailable when Alibaba chat policy is enforced")
