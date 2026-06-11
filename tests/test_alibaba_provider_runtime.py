from __future__ import annotations

import asyncio

from app.contracts import ContextPacket, ContextSnippet
from app.providers.alibaba_adapter import AlibabaAdapter


def test_alibaba_provider_parses_region_base_urls() -> None:
    adapter = AlibabaAdapter(
        api_key="key",
        base_url="https://a.example.com/v1, https://b.example.com/v1",
    )

    assert adapter.region_base_urls == [
        "https://a.example.com/v1",
        "https://b.example.com/v1",
    ]


def test_alibaba_provider_model_cost_estimation_uses_model_pricing() -> None:
    adapter = AlibabaAdapter(api_key="key", base_url="https://example.com/v1")
    cost = adapter._estimate_cost(
        prompt_tokens=1000,
        completion_tokens=500,
        model_name="qwen-plus-latest",
    )

    assert cost > 0
    assert round(cost, 6) == 0.0024


def test_alibaba_provider_system_prompt_enforces_grounded_answers() -> None:
    adapter = AlibabaAdapter(api_key="key", base_url="https://example.com/v1")

    prompt = adapter._system_prompt(prompt="como funciona catch rate?")

    assert "Ground every factual claim" in prompt
    assert "Do not invent formulas" in prompt


def test_alibaba_provider_system_prompt_respects_strict_json_requests() -> None:
    adapter = AlibabaAdapter(api_key="key", base_url="https://example.com/v1")

    prompt = adapter._system_prompt(prompt="Return ONLY valid JSON with this schema")

    assert "formatting constraints exactly" in prompt


class RecordingAlibabaAdapter(AlibabaAdapter):
    def __init__(self) -> None:
        super().__init__(api_key="key", base_url="https://example.com/v1")
        self.last_payload: dict | None = None

    async def _request_with_retries(self, *, payload: dict, headers: dict) -> dict:
        self.last_payload = payload
        return {
            "choices": [
                {
                    "message": {"content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        }


def test_alibaba_provider_sends_all_context_snippets_without_hard_cap() -> None:
    adapter = RecordingAlibabaAdapter()
    packet = ContextPacket(
        snippets=[
            ContextSnippet(
                source=f"artifact:file:data/scripts/example_{index}.lua",
                content=f"snippet-content-{index}",
                score=0.9,
            )
            for index in range(1, 13)
        ]
    )

    _ = asyncio.run(
        adapter.generate(
            prompt="quais os loots do arcanine?",
            context=packet,
            model_name="qwen-turbo-latest",
        )
    )

    assert adapter.last_payload is not None
    user_content = adapter.last_payload["messages"][1]["content"]
    assert "artifact:file:data/scripts/example_1.lua" in user_content
    assert "artifact:file:data/scripts/example_12.lua" in user_content
