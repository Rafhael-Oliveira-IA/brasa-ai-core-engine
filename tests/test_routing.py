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


class MultiModelChatProvider(BaseProvider):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    async def generate(self, *, prompt: str, context: ContextPacket, model_name: str) -> ProviderResponse:
        self.calls.append(model_name)

        if model_name == "qwen-classifier":
            answer = '{"role":"coding","tier":"flash"}'
            confidence = 0.91
        elif model_name == "qwen-verifier":
            answer = '{"verdict":"needs_repair","confidence":0.44,"issues":["missing source grounding"]}'
            confidence = 0.89
        elif model_name == "qwen-repair":
            answer = "repaired final answer"
            confidence = 0.93
        else:
            answer = "initial answer"
            confidence = 0.88

        return ProviderResponse(
            answer=answer,
            confidence=confidence,
            provider=self.name,
            model_name=model_name,
            prompt_tokens=20,
            completion_tokens=40,
            total_tokens=60,
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


def test_router_uses_planning_role_model_for_action_planning_task() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            data_dir=Path(temp_dir) / "data",
            sqlite_path=Path(temp_dir) / "data" / "memory.db",
            trace_file=Path(temp_dir) / "data" / "traces.jsonl",
            reflection_dir=Path(temp_dir) / "data" / "reflection_reports",
            alibaba_api_key="test-key",
            alibaba_model_flash="qwen-flash-default",
            alibaba_model_planning="qwen-planning-specialized",
        )
        local_provider = StubProvider(name="local", confidence=0.99)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.90)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="build an execution plan",
            tier_hint=ModelTier.FLASH,
            metadata={"task_type": "action_planning"},
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.provider == "alibaba"
        assert decision.model_name == "qwen-planning-specialized"


def test_router_honors_explicit_model_role_override() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            data_dir=Path(temp_dir) / "data",
            sqlite_path=Path(temp_dir) / "data" / "memory.db",
            trace_file=Path(temp_dir) / "data" / "traces.jsonl",
            reflection_dir=Path(temp_dir) / "data" / "reflection_reports",
            alibaba_api_key="test-key",
            alibaba_model_flash="qwen-flash-default",
            alibaba_model_verifier="qwen-verifier-specialized",
        )
        local_provider = StubProvider(name="local", confidence=0.99)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.90)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="validate this patch output",
            tier_hint=ModelTier.FLASH,
            metadata={"model_role": "verifier"},
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.provider == "alibaba"
        assert decision.model_name == "qwen-verifier-specialized"


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
        final_chat_prompts = [
            prompt
            for prompt in alibaba_provider.prompts
            if "Local draft (optional, may be incomplete):" in prompt
        ]
        assert final_chat_prompts
        assert "Local retrieval summary:" in final_chat_prompts[0]
        assert "Output contract (mandatory):" in final_chat_prompts[0]
        assert "Do not invent formulas" in final_chat_prompts[0]


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


def test_router_chat_large_context_starts_on_flash_for_cost_efficiency() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = build_settings(Path(temp_dir))
        settings.chat_qwen_classification_enabled = False
        local_provider = StubProvider(name="local", confidence=0.99)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.90)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        retrieval_context_packet = [
            {"source": f"artifact:file:data/scripts/source_{index}.lua"}
            for index in range(1, 20)
        ]

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="quais os loots do arcanine?",
            metadata={
                "task_type": "chat",
                "retrieval": {
                    "user_intent": "general-query",
                    "dependencies": ["loot", "drop"],
                    "risks": [],
                    "context_packet": retrieval_context_packet,
                },
            },
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.provider == "alibaba"
        assert decision.selected_tier == ModelTier.FLASH


def test_router_chat_multi_model_pipeline_uses_classifier_verifier_and_repair_models() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            data_dir=Path(temp_dir) / "data",
            sqlite_path=Path(temp_dir) / "data" / "memory.db",
            trace_file=Path(temp_dir) / "data" / "traces.jsonl",
            reflection_dir=Path(temp_dir) / "data" / "reflection_reports",
            alibaba_api_key="test-key",
            alibaba_model_flash="qwen-flash-default",
            alibaba_model_coding="qwen-coding-specialized",
            alibaba_model_classification="qwen-classifier",
            alibaba_model_verifier="qwen-verifier",
            alibaba_model_repair="qwen-repair",
            chat_qwen_multi_model_enabled=True,
            chat_qwen_classification_enabled=True,
            chat_qwen_verifier_enabled=True,
            chat_qwen_repair_enabled=True,
        )
        local_provider = StubProvider(name="local", confidence=0.99)
        alibaba_provider = MultiModelChatProvider(name="alibaba")

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="quais os loots do arcanine?",
            metadata={
                "task_type": "chat",
                "retrieval": {
                    "user_intent": "general-query",
                    "dependencies": ["loot", "drop"],
                    "risks": [],
                    "context_packet": [
                        {"source": "artifact:file:data/monster/kanto/arcanine.lua"},
                    ],
                },
            },
        )

        response, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.provider == "alibaba"
        assert decision.selected_tier == ModelTier.FLASH
        assert decision.model_name == "qwen-coding-specialized"
        assert "chat_verifier=repair" in decision.reason
        assert response.answer == "repaired final answer"
        assert alibaba_provider.calls[:4] == [
            "qwen-classifier",
            "qwen-coding-specialized",
            "qwen-verifier",
            "qwen-repair",
        ]


def test_router_effective_tier_tracks_role_specific_model_family() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            data_dir=Path(temp_dir) / "data",
            sqlite_path=Path(temp_dir) / "data" / "memory.db",
            trace_file=Path(temp_dir) / "data" / "traces.jsonl",
            reflection_dir=Path(temp_dir) / "data" / "reflection_reports",
            alibaba_api_key="test-key",
            alibaba_model_flash="qwen3.6-flash",
            alibaba_model_coding="qwen-plus-latest",
        )
        local_provider = StubProvider(name="local", confidence=0.99)
        alibaba_provider = StubProvider(name="alibaba", confidence=0.90)

        router = AIRouter(
            settings=settings,
            local_provider=local_provider,
            alibaba_provider=alibaba_provider,
        )

        envelope = RequestEnvelope(
            project_id="project-1",
            user_id="user-1",
            prompt="quais os loots do arcanine?",
            metadata={
                "task_type": "chat",
                "model_role": "coding",
            },
        )

        _, decision = asyncio.run(router.generate(envelope=envelope, context=ContextPacket()))

        assert decision.model_name == "qwen-plus-latest"
        assert decision.selected_tier == ModelTier.PLUS
