from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.contracts import ContextPacket, ProviderResponse


class ProviderUnavailable(RuntimeError):
    pass


class ProviderFailure(RuntimeError):
    pass


class BaseProvider(ABC):
    name: str

    @abstractmethod
    async def generate(
        self,
        *,
        prompt: str,
        context: ContextPacket,
        model_name: str,
    ) -> ProviderResponse:
        raise NotImplementedError

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
        yield response.answer
