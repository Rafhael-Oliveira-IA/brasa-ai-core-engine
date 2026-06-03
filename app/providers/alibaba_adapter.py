from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.contracts import ContextPacket, ProviderResponse
from app.providers.base import BaseProvider, ProviderFailure, ProviderUnavailable


MODEL_TOKEN_PRICING_USD_PER_1K: dict[str, tuple[float, float]] = {
    "qwen-turbo": (0.0004, 0.0008),
    "qwen-flash": (0.0004, 0.0008),
    "qwen-plus": (0.0012, 0.0024),
    "qwen-max": (0.0035, 0.0070),
}

RETRIABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class AlibabaAdapter(BaseProvider):
    name = "alibaba"

    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        timeout_seconds: int = 40,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.35,
        region_base_urls: list[str] | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        normalized_urls = [item.rstrip("/") for item in (region_base_urls or self._parse_region_urls(base_url)) if item]
        if not normalized_urls:
            normalized_urls = [base_url.rstrip("/")]

        self.base_url = normalized_urls[0]
        self.region_base_urls = normalized_urls
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.05, retry_backoff_seconds)

    async def generate(
        self,
        *,
        prompt: str,
        context: ContextPacket,
        model_name: str,
    ) -> ProviderResponse:
        if not self.api_key:
            raise ProviderUnavailable("Alibaba API key is not configured.")

        context_block = "\n\n".join(
            f"[{snippet.source}]\n{snippet.content}" for snippet in context.snippets[:5]
        )
        user_input = prompt if not context_block else f"Context:\n{context_block}\n\nRequest:\n{prompt}"

        payload: dict[str, Any] = {
            "model": model_name,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a pragmatic engineering assistant. "
                        "Prefer concrete steps and call out assumptions."
                    ),
                },
                {
                    "role": "user",
                    "content": user_input,
                },
            ],
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        data = await self._request_with_retries(payload=payload, headers=headers)
        answer = self._extract_text(data)
        usage = data.get("usage") or {}

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))

        if prompt_tokens <= 0:
            prompt_tokens = max(1, len(user_input.split()))
        if completion_tokens <= 0:
            completion_tokens = max(1, len(answer.split()))
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens

        finish_reason = self._extract_finish_reason(data)

        confidence = 0.90 if finish_reason in {"stop", None, ""} else 0.75
        cost_usd = self._estimate_cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model_name=model_name,
        )

        return ProviderResponse(
            answer=answer,
            confidence=confidence,
            provider=self.name,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
        )

    async def stream_generate(
        self,
        *,
        prompt: str,
        context: ContextPacket,
        model_name: str,
    ) -> AsyncIterator[str]:
        response = await self.generate(
            prompt=prompt,
            context=context,
            model_name=model_name,
        )

        for chunk in self._chunk_text(response.answer, max_chars=260):
            yield chunk

    async def _request_with_retries(self, *, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None

        for base_url in self.region_base_urls:
            url = f"{base_url}/chat/completions"

            for attempt in range(self.max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        response = await client.post(url, json=payload, headers=headers)

                    if response.status_code in RETRIABLE_STATUS_CODES and attempt < self.max_retries:
                        await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
                        continue

                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as exc:
                    details = exc.response.text[:400]
                    last_error = ProviderFailure(f"Alibaba HTTP error ({exc.response.status_code}): {details}")
                    if exc.response.status_code in RETRIABLE_STATUS_CODES and attempt < self.max_retries:
                        await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
                        continue
                    break
                except httpx.HTTPError as exc:
                    last_error = ProviderUnavailable(f"Alibaba network error: {exc}")
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
                        continue
                    break

        if last_error is not None:
            raise last_error
        raise ProviderUnavailable("Alibaba request failed without details.")

    def _extract_text(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return "No response from Alibaba model."

        message = choices[0].get("message") or {}
        content = message.get("content")

        if isinstance(content, str):
            return content.strip() or "Empty response from Alibaba model."

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_part = item.get("text")
                    if isinstance(text_part, str):
                        parts.append(text_part)
            combined = "\n".join(parts).strip()
            return combined or "Empty response from Alibaba model."

        return "Unsupported response format from Alibaba model."

    def _extract_finish_reason(self, payload: dict[str, Any]) -> str | None:
        choices = payload.get("choices") or []
        if not choices:
            return None
        value = choices[0].get("finish_reason")
        if isinstance(value, str):
            return value
        return None

    def _estimate_cost(self, *, prompt_tokens: int, completion_tokens: int, model_name: str) -> float:
        input_rate, output_rate = self._pricing_for_model(model_name)
        total = (prompt_tokens / 1000.0) * input_rate + (completion_tokens / 1000.0) * output_rate
        return round(total, 6)

    def _pricing_for_model(self, model_name: str) -> tuple[float, float]:
        lowered = model_name.lower()
        for key, rates in MODEL_TOKEN_PRICING_USD_PER_1K.items():
            if key in lowered:
                return rates
        return (0.0010, 0.0020)

    def _parse_region_urls(self, raw_value: str) -> list[str]:
        parts = [item.strip() for item in (raw_value or "").split(",")]
        return [item for item in parts if item]

    def _chunk_text(self, value: str, *, max_chars: int) -> list[str]:
        text = value.strip()
        if not text:
            return []

        if len(text) <= max_chars:
            return [text]

        chunks: list[str] = []
        cursor = 0
        while cursor < len(text):
            chunks.append(text[cursor : cursor + max_chars])
            cursor += max_chars
        return chunks
