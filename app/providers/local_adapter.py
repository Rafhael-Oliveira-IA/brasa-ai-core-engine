from __future__ import annotations

from app.contracts import ContextPacket, ProviderResponse
from app.providers.base import BaseProvider


class LocalAdapter(BaseProvider):
    name = "local"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    async def generate(
        self,
        *,
        prompt: str,
        context: ContextPacket,
        model_name: str,
    ) -> ProviderResponse:
        confidence = self._estimate_confidence(prompt)
        top_snippets = context.snippets[:3]

        answer_lines = [
            "Local response (fast mode)",
            "",
            "Plan:",
            "1. Keep contracts stable.",
            "2. Ship incrementally with measurable checkpoints.",
            "3. Escalate only when confidence is low.",
            "",
            "Working draft:",
            prompt.strip(),
        ]

        if top_snippets:
            answer_lines.append("")
            answer_lines.append("Context used:")
            for snippet in top_snippets:
                preview = snippet.content.replace("\n", " ").strip()
                answer_lines.append(f"- {preview[:180]}")

        answer = "\n".join(answer_lines).strip()
        prompt_tokens = len(prompt.split()) + sum(len(snippet.content.split()) for snippet in top_snippets)
        completion_tokens = len(answer.split())

        return ProviderResponse(
            answer=answer,
            confidence=confidence,
            provider=self.name,
            model_name=model_name or self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=0.0,
        )

    def _estimate_confidence(self, prompt: str) -> float:
        lower_prompt = prompt.lower()
        score = 0.90

        if len(prompt) > 280:
            score -= 0.15

        complexity_markers = (
            "architecture",
            "refactor",
            "distributed",
            "multi-tenant",
            "deep reasoning",
            "debug",
            "root cause",
            "migration",
            "security",
        )
        if any(marker in lower_prompt for marker in complexity_markers):
            score -= 0.20

        if prompt.count("?") > 1:
            score -= 0.05

        return max(0.25, min(score, 0.95))
