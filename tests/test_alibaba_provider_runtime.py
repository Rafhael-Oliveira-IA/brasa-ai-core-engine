from __future__ import annotations

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
