from __future__ import annotations

from app.contracts import ContextPacket, ProviderResponse
from app.providers.base import BaseProvider, ProviderUnavailable


class OpenAIAdapter(BaseProvider):
    name = "openai"

    async def generate(
        self,
        *,
        prompt: str,
        context: ContextPacket,
        model_name: str,
    ) -> ProviderResponse:
        raise ProviderUnavailable("OpenAI adapter is not configured in this runtime yet.")


__all__ = ["OpenAIAdapter"]
