from __future__ import annotations

import json

from app.contracts import ContextPacket, ModelTier, ProviderResponse, RequestEnvelope, RouteDecision
from app.providers.base import BaseProvider, ProviderFailure, ProviderUnavailable
from app.settings import Settings


TIER_ORDER = [ModelTier.LOCAL, ModelTier.FLASH, ModelTier.PLUS, ModelTier.MAX]
TIER_COST_FLOOR = {
    ModelTier.LOCAL: 0.0,
    ModelTier.FLASH: 0.003,
    ModelTier.PLUS: 0.012,
    ModelTier.MAX: 0.040,
}
TIER_CONFIDENCE_TARGET = {
    ModelTier.LOCAL: 0.72,
    ModelTier.FLASH: 0.78,
    ModelTier.PLUS: 0.83,
    ModelTier.MAX: 0.00,
}

TIER_TOKEN_RATES = {
    ModelTier.LOCAL: (0.0, 0.0),
    ModelTier.FLASH: (0.0004, 0.0008),
    ModelTier.PLUS: (0.0012, 0.0024),
    ModelTier.MAX: (0.0035, 0.0070),
}


class CostAwarenessEngine:
    def estimate(
        self,
        *,
        tier: ModelTier,
        prompt: str,
        context: ContextPacket,
    ) -> float:
        if tier == ModelTier.LOCAL:
            return 0.0

        prompt_tokens = len(prompt.split()) + sum(len(snippet.content.split()) for snippet in context.snippets)
        completion_tokens = max(120, int(prompt_tokens * 0.75))

        input_rate, output_rate = TIER_TOKEN_RATES[tier]
        variable_cost = (prompt_tokens / 1000.0) * input_rate + (completion_tokens / 1000.0) * output_rate
        return round(max(TIER_COST_FLOOR[tier], variable_cost), 6)


class CognitiveRoutingPolicy:
    def choose_starting_tier(self, envelope: RequestEnvelope, context: ContextPacket) -> tuple[ModelTier, str]:
        if envelope.tier_hint is not None:
            return envelope.tier_hint, "explicit tier hint"

        retrieval = envelope.metadata.get("retrieval") if isinstance(envelope.metadata, dict) else None
        if isinstance(retrieval, dict):
            intent = str(retrieval.get("user_intent") or "").strip().lower()
            dependency_count = len(retrieval.get("dependencies", []))
            risk_count = len(retrieval.get("risks", []))
            context_count = len(retrieval.get("context_packet", retrieval.get("contexts", [])))

            if intent == "architecture":
                return ModelTier.PLUS, "intent architecture"
            if intent == "refactor" and dependency_count >= 8:
                return ModelTier.PLUS, "high dependency refactor"
            if intent == "refactor" and dependency_count >= 3:
                return ModelTier.FLASH, "moderate dependency refactor"
            if intent == "debug" and risk_count > 0:
                return ModelTier.PLUS, "debug with contextual risks"
            if context_count >= 14:
                return ModelTier.PLUS, "large context packet"

        complexity = self._complexity_score(envelope.prompt)
        if complexity >= 0.80:
            return ModelTier.PLUS, "high prompt complexity"
        if complexity >= 0.45:
            return ModelTier.FLASH, "moderate prompt complexity"
        if len(context.snippets) >= 6:
            return ModelTier.FLASH, "rich local context"

        return ModelTier.LOCAL, "low complexity local-first"

    def _complexity_score(self, prompt: str) -> float:
        score = 0.10
        prompt_size = len(prompt)

        if prompt_size > 800:
            score += 0.50
        elif prompt_size > 450:
            score += 0.35
        elif prompt_size > 220:
            score += 0.20

        markers = (
            "architecture",
            "trade-off",
            "multi-tenant",
            "security",
            "migration",
            "root cause",
            "distributed",
            "incident",
            "performance",
        )
        lower_prompt = prompt.lower()
        marker_hits = sum(1 for marker in markers if marker in lower_prompt)
        score += min(0.45, marker_hits * 0.12)

        return min(score, 1.0)


class AIRouter:
    def __init__(
        self,
        settings: Settings,
        local_provider: BaseProvider,
        alibaba_provider: BaseProvider,
    ) -> None:
        self.settings = settings
        self.local_provider = local_provider
        self.alibaba_provider = alibaba_provider
        self.cost_engine = CostAwarenessEngine()
        self.routing_policy = CognitiveRoutingPolicy()

    async def generate(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
    ) -> tuple[ProviderResponse, RouteDecision]:
        require_alibaba_final = self._requires_alibaba_final_response(envelope)
        provider_prompt = envelope.prompt

        if require_alibaba_final and self._is_chat_task(envelope):
            provider_prompt = await self._build_chat_final_prompt(
                envelope=envelope,
                context=context,
            )

        start_tier, start_reason = self.routing_policy.choose_starting_tier(envelope, context)
        if require_alibaba_final and start_tier == ModelTier.LOCAL:
            start_tier = ModelTier.FLASH
            start_reason = "chat policy requires Alibaba final response"

        candidate_tiers = self._tiers_from(start_tier)
        if require_alibaba_final:
            candidate_tiers = [tier for tier in candidate_tiers if tier != ModelTier.LOCAL]
        if not candidate_tiers:
            candidate_tiers = [ModelTier.FLASH, ModelTier.PLUS, ModelTier.MAX]

        max_depth = min(self.settings.max_escalation_depth, len(candidate_tiers) - 1)

        last_reason = f"starting tier: {start_reason}"

        for depth, tier in enumerate(candidate_tiers):
            if depth > max_depth:
                break

            estimated_cost = self.cost_engine.estimate(
                tier=tier,
                prompt=provider_prompt,
                context=context,
            )
            if tier != ModelTier.LOCAL and estimated_cost > self.settings.request_budget_usd:
                if require_alibaba_final and self.settings.chat_force_alibaba_ignore_budget:
                    last_reason = (
                        "budget cap exceeded but continuing due chat Alibaba policy"
                    )
                else:
                    last_reason = "budget cap reached before external provider"
                    break

            provider, model_name = self._provider_and_model_for_tier(tier)

            try:
                response = await provider.generate(
                    prompt=provider_prompt,
                    context=context,
                    model_name=model_name,
                )
            except ProviderUnavailable as exc:
                last_reason = f"{provider.name} unavailable: {exc}"
                continue
            except ProviderFailure as exc:
                last_reason = f"{provider.name} failed: {exc}"
                continue

            decision = RouteDecision(
                selected_tier=tier,
                provider=provider.name,
                model_name=model_name,
                reason=f"confidence gate passed ({start_reason})",
                escalation_depth=depth,
                estimated_cost_usd=estimated_cost,
            )

            if self._should_escalate(tier=tier, response=response, depth=depth, max_depth=max_depth):
                last_reason = f"confidence {response.confidence:.2f} below target for {tier.value}"
                continue

            return response, decision

        if require_alibaba_final:
            raise ProviderUnavailable(
                f"external-chat-required: no Alibaba response available ({last_reason})"
            )

        fallback = await self.local_provider.generate(
            prompt=envelope.prompt,
            context=context,
            model_name=self.settings.local_model_name,
        )
        decision = RouteDecision(
            selected_tier=ModelTier.LOCAL,
            provider=self.local_provider.name,
            model_name=self.settings.local_model_name,
            reason=f"fallback-local: {last_reason}",
            escalation_depth=max_depth,
            estimated_cost_usd=0.0,
        )
        return fallback, decision

    async def _build_chat_final_prompt(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
    ) -> str:
        local_draft = ""
        if self.settings.chat_local_assist_enabled:
            local_draft = await self._generate_local_chat_draft(
                prompt=envelope.prompt,
                context=context,
            )

        retrieval_summary = self._chat_retrieval_summary(
            envelope=envelope,
            context=context,
        )
        local_draft_block = local_draft if local_draft else "No local draft available."

        return (
            "You are generating the final user-facing chat answer.\n"
            "Use project evidence from the provided context as the primary source of truth.\n"
            "When evidence is missing, be explicit about uncertainty instead of filling gaps with generic assumptions.\n"
            "Return only the final answer in the same language as the user request.\n"
            "Do not mention internal routing, local drafting, or model selection.\n\n"
            "Output contract (mandatory):\n"
            "1) Confirmed in project: only facts supported by provided sources.\n"
            "2) Hypotheses or missing evidence: list what is uncertain or absent.\n"
            "3) Quick verification path: files/functions to inspect next.\n\n"
            "Hard rules:\n"
            "- Do not invent formulas, constants, percentages, item multipliers, or function names.\n"
            "- If a numeric value is not present in the evidence, explicitly say it is not confirmed.\n"
            "- Prefer citing source identifiers like artifact:file:... when stating confirmed facts.\n\n"
            f"User request:\n{envelope.prompt}\n\n"
            f"Local retrieval summary:\n{retrieval_summary}\n\n"
            f"Local draft (optional, may be incomplete):\n{local_draft_block}"
        )

    async def _generate_local_chat_draft(
        self,
        *,
        prompt: str,
        context: ContextPacket,
    ) -> str:
        try:
            response = await self.local_provider.generate(
                prompt=prompt,
                context=context,
                model_name=self.settings.local_model_name,
            )
        except (ProviderUnavailable, ProviderFailure):
            return ""
        except Exception:
            return ""

        answer = (response.answer or "").strip()
        if not answer:
            return ""

        limit = max(200, min(self.settings.chat_local_assist_max_chars, 6000))
        return answer[:limit]

    def _chat_retrieval_summary(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
    ) -> str:
        metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}
        retrieval = metadata.get("retrieval")
        retrieval_dict = retrieval if isinstance(retrieval, dict) else {}

        evidence_sources: list[dict[str, object]] = []
        for item in retrieval_dict.get("context_packet", []):
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            if not source:
                continue
            evidence_sources.append(
                {
                    "source": source,
                    "score": float(item.get("score") or 0.0),
                    "hot": bool(item.get("hot", False)),
                }
            )
            if len(evidence_sources) >= 12:
                break

        summary = {
            "user_intent": retrieval_dict.get("user_intent", "general-query"),
            "relevant_systems": list(retrieval_dict.get("relevant_systems", []))[:20],
            "dependencies": list(retrieval_dict.get("dependencies", []))[:25],
            "risks": list(retrieval_dict.get("risks", []))[:15],
            "compression": retrieval_dict.get("compression", {}),
            "auto_reingest": retrieval_dict.get("auto_reingest", {}),
            "evidence_sources": evidence_sources,
            "context_sources": list(context.provenance)[:20],
        }
        return json.dumps(summary, ensure_ascii=True, indent=2)

    def _should_escalate(
        self,
        *,
        tier: ModelTier,
        response: ProviderResponse,
        depth: int,
        max_depth: int,
    ) -> bool:
        if depth >= max_depth:
            return False
        target = TIER_CONFIDENCE_TARGET[tier]
        return response.confidence < target

    def _provider_and_model_for_tier(self, tier: ModelTier) -> tuple[BaseProvider, str]:
        if tier == ModelTier.LOCAL:
            return self.local_provider, self.settings.local_model_name

        if tier == ModelTier.FLASH:
            return self.alibaba_provider, self.settings.alibaba_model_flash

        if tier == ModelTier.PLUS:
            return self.alibaba_provider, self.settings.alibaba_model_plus

        return self.alibaba_provider, self.settings.alibaba_model_max

    def _tiers_from(self, starting_tier: ModelTier) -> list[ModelTier]:
        index = TIER_ORDER.index(starting_tier)
        return TIER_ORDER[index:]

    def _is_chat_task(self, envelope: RequestEnvelope) -> bool:
        metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}
        task_type = str(metadata.get("task_type", "")).strip().lower()
        return task_type == "chat"

    def _requires_alibaba_final_response(self, envelope: RequestEnvelope) -> bool:
        metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}

        if bool(metadata.get("require_alibaba_final_response", False)):
            return True

        if not self.settings.chat_force_alibaba_response:
            return False

        task_type = str(metadata.get("task_type", "")).strip().lower()
        return task_type == "chat"
