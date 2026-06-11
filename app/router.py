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

CHAT_CLASSIFIER_ALLOWED_ROLES = {
    "default",
    "coding",
    "long_context",
    "planning",
    "compression",
}

CHAT_VERIFIER_ALLOWED_VERDICTS = {
    "ok",
    "needs_repair",
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

        metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}
        task_type = str(metadata.get("task_type", "")).strip().lower()
        is_chat = task_type == "chat"

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
                if is_chat and intent in {"general-query", "testing"}:
                    return ModelTier.FLASH, "chat cost-aware start on flash for large context"
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
        is_chat_task = self._is_chat_task(envelope)
        chat_multi_model_enabled = (
            require_alibaba_final
            and is_chat_task
            and self.settings.chat_qwen_multi_model_enabled
        )
        metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}
        explicit_role = str(metadata.get("model_role", "")).strip().lower()
        has_explicit_role = bool(explicit_role)

        model_role = self._resolve_model_role(envelope)
        provider_prompt = envelope.prompt
        classifier_notes: list[str] = []
        classifier_tier: ModelTier | None = None

        if require_alibaba_final and is_chat_task:
            provider_prompt = await self._build_chat_final_prompt(
                envelope=envelope,
                context=context,
            )

        if (
            chat_multi_model_enabled
            and self.settings.chat_qwen_classification_enabled
            and not has_explicit_role
        ):
            classified_role, classified_tier, classifier_reason = await self._classify_chat_model_role(
                envelope=envelope,
                context=context,
            )
            if classified_role is not None:
                model_role = classified_role
                classifier_notes.append(f"chat_classifier_role={classified_role}")
            if classified_tier is not None:
                classifier_tier = classified_tier
                classifier_notes.append(f"chat_classifier_tier={classified_tier.value}")
            if classifier_reason:
                classifier_notes.append(classifier_reason)

        start_tier, start_reason = self.routing_policy.choose_starting_tier(envelope, context)
        if classifier_tier is not None:
            start_tier = classifier_tier
            start_reason = f"{start_reason}; classifier tier override"

        if classifier_notes:
            start_reason = f"{start_reason}; {'; '.join(classifier_notes[:4])}"

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

            provider, model_name = self._provider_and_model_for_tier(
                tier=tier,
                model_role=model_role,
            )
            effective_tier = self._effective_tier_for_model_name(
                model_name=model_name,
                fallback=tier,
            )

            estimated_cost = self.cost_engine.estimate(
                tier=effective_tier,
                prompt=provider_prompt,
                context=context,
            )
            if effective_tier != ModelTier.LOCAL and estimated_cost > self.settings.request_budget_usd:
                if require_alibaba_final and self.settings.chat_force_alibaba_ignore_budget:
                    last_reason = (
                        "budget cap exceeded but continuing due chat Alibaba policy"
                    )
                else:
                    last_reason = "budget cap reached before external provider"
                    break

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
                selected_tier=effective_tier,
                provider=provider.name,
                model_name=model_name,
                reason=f"confidence gate passed ({start_reason}; role={model_role})",
                escalation_depth=depth,
                estimated_cost_usd=estimated_cost,
            )

            if self._should_escalate(tier=effective_tier, response=response, depth=depth, max_depth=max_depth):
                last_reason = f"confidence {response.confidence:.2f} below target for {effective_tier.value}"
                continue

            if chat_multi_model_enabled and self.settings.chat_qwen_verifier_enabled:
                response, verifier_note = await self._verify_and_repair_chat_answer(
                    envelope=envelope,
                    context=context,
                    provider_prompt=provider_prompt,
                    candidate_response=response,
                )
                if verifier_note:
                    decision = decision.model_copy(
                        update={
                            "reason": f"{decision.reason}; {verifier_note}"
                        }
                    )

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

    async def _classify_chat_model_role(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
    ) -> tuple[str | None, ModelTier | None, str]:
        heuristic_role = self._infer_chat_role_heuristic(envelope=envelope, context=context)
        classifier_prompt = self._build_chat_classifier_prompt(
            envelope=envelope,
            context=context,
        )

        try:
            response = await self.alibaba_provider.generate(
                prompt=classifier_prompt,
                context=ContextPacket(),
                model_name=self.settings.alibaba_model_classification,
            )
        except (ProviderUnavailable, ProviderFailure):
            return heuristic_role, None, "chat_classifier_unavailable"
        except Exception:
            return heuristic_role, None, "chat_classifier_failed"

        payload = self._extract_json_payload(response.answer)
        if payload is None:
            if heuristic_role is not None:
                return heuristic_role, None, "chat_classifier_fallback_heuristic"
            return None, None, "chat_classifier_invalid_payload"

        role_raw = str(payload.get("role") or "").strip().lower()
        role = role_raw if role_raw in CHAT_CLASSIFIER_ALLOWED_ROLES else None
        if role is None:
            role = heuristic_role

        tier_raw = str(payload.get("tier") or "").strip().lower()
        tier = self._safe_model_tier(tier_raw)

        return role, tier, "chat_classifier_ok"

    def _infer_chat_role_heuristic(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
    ) -> str | None:
        metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}
        retrieval = metadata.get("retrieval") if isinstance(metadata.get("retrieval"), dict) else {}
        prompt = (envelope.prompt or "").lower()

        intent = str(retrieval.get("user_intent") or "").strip().lower()
        context_count = len(retrieval.get("context_packet", retrieval.get("contexts", [])))
        dependency_count = len(retrieval.get("dependencies", []))

        if intent == "architecture":
            return "long_context"

        code_markers = {
            ".lua",
            ".xml",
            ".py",
            ".json",
            "arquivo",
            "file",
            "script",
            "function",
            "classe",
            "class",
            "drop",
            "loot",
            "patch",
            "diff",
        }
        if any(marker in prompt for marker in code_markers):
            return "coding"

        if context_count >= 18 or dependency_count >= 100 or len(context.snippets) >= 18:
            return "long_context"

        return None

    async def _verify_and_repair_chat_answer(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
        provider_prompt: str,
        candidate_response: ProviderResponse,
    ) -> tuple[ProviderResponse, str]:
        verifier_prompt = self._build_chat_verifier_prompt(
            envelope=envelope,
            context=context,
            provider_prompt=provider_prompt,
            candidate_answer=candidate_response.answer,
        )

        try:
            verifier_response = await self.alibaba_provider.generate(
                prompt=verifier_prompt,
                context=ContextPacket(),
                model_name=self.settings.alibaba_model_verifier,
            )
        except (ProviderUnavailable, ProviderFailure):
            return candidate_response, "chat_verifier_unavailable"
        except Exception:
            return candidate_response, "chat_verifier_failed"

        aggregated = candidate_response.model_copy(
            update={
                "prompt_tokens": candidate_response.prompt_tokens + verifier_response.prompt_tokens,
                "completion_tokens": candidate_response.completion_tokens + verifier_response.completion_tokens,
                "total_tokens": candidate_response.total_tokens + verifier_response.total_tokens,
                "cost_usd": round(candidate_response.cost_usd + verifier_response.cost_usd, 6),
            }
        )

        payload = self._extract_json_payload(verifier_response.answer)
        if payload is None:
            return aggregated, "chat_verifier_invalid_payload"

        verdict_raw = str(payload.get("verdict") or "").strip().lower()
        verdict = verdict_raw if verdict_raw in CHAT_VERIFIER_ALLOWED_VERDICTS else "ok"

        try:
            verifier_confidence = float(payload.get("confidence") or candidate_response.confidence)
        except Exception:
            verifier_confidence = candidate_response.confidence
        verifier_confidence = max(0.0, min(1.0, verifier_confidence))

        issues_raw = payload.get("issues", [])
        issues: list[str] = []
        if isinstance(issues_raw, list):
            issues = [str(item).strip() for item in issues_raw if str(item).strip()][:8]

        min_confidence = max(0.0, min(1.0, self.settings.chat_qwen_verifier_min_confidence))
        needs_repair = verdict == "needs_repair" or verifier_confidence < min_confidence

        if not needs_repair:
            merged_confidence = max(0.0, min(1.0, (aggregated.confidence + verifier_confidence) / 2.0))
            return (
                aggregated.model_copy(update={"confidence": merged_confidence}),
                f"chat_verifier=ok({self.settings.alibaba_model_verifier})",
            )

        if not self.settings.chat_qwen_repair_enabled:
            return aggregated, "chat_verifier=needs_repair(repair_disabled)"

        repair_prompt = self._build_chat_repair_prompt(
            envelope=envelope,
            context=context,
            candidate_answer=candidate_response.answer,
            verifier_issues=issues,
        )

        try:
            repair_response = await self.alibaba_provider.generate(
                prompt=repair_prompt,
                context=context,
                model_name=self.settings.alibaba_model_repair,
            )
        except (ProviderUnavailable, ProviderFailure):
            return aggregated, "chat_repair_unavailable"
        except Exception:
            return aggregated, "chat_repair_failed"

        repaired_confidence = max(0.40, min(0.95, (repair_response.confidence + verifier_confidence) / 2.0))
        merged = repair_response.model_copy(
            update={
                "confidence": repaired_confidence,
                "prompt_tokens": aggregated.prompt_tokens + repair_response.prompt_tokens,
                "completion_tokens": aggregated.completion_tokens + repair_response.completion_tokens,
                "total_tokens": aggregated.total_tokens + repair_response.total_tokens,
                "cost_usd": round(aggregated.cost_usd + repair_response.cost_usd, 6),
            }
        )

        return (
            merged,
            f"chat_verifier=repair({self.settings.alibaba_model_verifier}->{self.settings.alibaba_model_repair})",
        )

    def _build_chat_classifier_prompt(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
    ) -> str:
        retrieval_summary = self._chat_retrieval_summary(
            envelope=envelope,
            context=context,
        )

        return (
            "You are BRASA Chat Classifier.\n"
            "Return ONLY valid JSON (no markdown) with this schema:\n"
            "{\n"
            '  "role": "default|coding|long_context|planning|compression",\n'
            '  "tier": "flash|plus|max|"\n'
            "}\n"
            "Rules:\n"
            "- role must reflect the best Qwen specialization for the final chat answer.\n"
            "- tier may be empty when no override is needed.\n\n"
            f"User request:\n{envelope.prompt}\n\n"
            f"Retrieval summary:\n{retrieval_summary}"
        )

    def _build_chat_verifier_prompt(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
        provider_prompt: str,
        candidate_answer: str,
    ) -> str:
        retrieval_summary = self._chat_retrieval_summary(
            envelope=envelope,
            context=context,
        )

        return (
            "You are BRASA Chat Verifier.\n"
            "Check if the candidate answer is grounded in project evidence and follows the answer contract.\n"
            "Return ONLY valid JSON with this schema:\n"
            "{\n"
            '  "verdict": "ok|needs_repair",\n'
            '  "confidence": 0.0,\n'
            '  "issues": ["string"]\n'
            "}\n"
            "Rules:\n"
            "- Mark needs_repair when the answer invents facts, omits key evidence, or contradicts context.\n"
            "- Keep issues concise and actionable.\n\n"
            f"User request:\n{envelope.prompt}\n\n"
            f"Retriever context summary:\n{retrieval_summary}\n\n"
            f"Generator prompt:\n{provider_prompt[:3500]}\n\n"
            f"Candidate answer:\n{candidate_answer}"
        )

    def _build_chat_repair_prompt(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
        candidate_answer: str,
        verifier_issues: list[str],
    ) -> str:
        retrieval_summary = self._chat_retrieval_summary(
            envelope=envelope,
            context=context,
        )

        issues_json = json.dumps(verifier_issues[:10], ensure_ascii=True)
        return (
            "You are BRASA Chat Repair model.\n"
            "Rewrite the candidate answer to be fully grounded in project evidence.\n"
            "Return only the repaired final answer in the user's language.\n"
            "Do not mention internal model pipeline, verifier, or repair steps.\n\n"
            "Hard rules:\n"
            "- Keep the same three sections: Confirmed in project, Hypotheses or missing evidence, Quick verification path.\n"
            "- Remove unsupported claims and keep uncertainty explicit.\n"
            "- Cite evidence source identifiers when stating confirmed facts.\n\n"
            f"User request:\n{envelope.prompt}\n\n"
            f"Verifier issues:\n{issues_json}\n\n"
            f"Retrieval summary:\n{retrieval_summary}\n\n"
            f"Candidate answer to repair:\n{candidate_answer}"
        )

    def _safe_model_tier(self, value: str) -> ModelTier | None:
        raw = (value or "").strip().lower()
        mapping = {
            "flash": ModelTier.FLASH,
            "plus": ModelTier.PLUS,
            "max": ModelTier.MAX,
        }
        return mapping.get(raw)

    def _extract_json_payload(self, text: str) -> dict[str, object] | None:
        raw = (text or "").strip()
        if not raw:
            return None

        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        payload = self._try_parse_json(raw)
        if payload is not None:
            return payload

        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            return self._try_parse_json(raw[first : last + 1])

        return None

    def _try_parse_json(self, text: str) -> dict[str, object] | None:
        try:
            payload = json.loads(text)
        except Exception:
            return None

        if isinstance(payload, dict):
            return payload
        return None

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

    def _provider_and_model_for_tier(
        self,
        *,
        tier: ModelTier,
        model_role: str,
    ) -> tuple[BaseProvider, str]:
        if tier == ModelTier.LOCAL:
            return self.local_provider, self.settings.local_model_name

        return self.alibaba_provider, self._model_name_for_role(
            tier=tier,
            model_role=model_role,
        )

    def _model_name_for_role(self, *, tier: ModelTier, model_role: str) -> str:
        role_models = {
            "classification": self.settings.alibaba_model_classification,
            "coding": self.settings.alibaba_model_coding,
            "long_context": self.settings.alibaba_model_long_context,
            "planning": self.settings.alibaba_model_planning,
            "reflection": self.settings.alibaba_model_reflection,
            "compression": self.settings.alibaba_model_compression,
            "repair": self.settings.alibaba_model_repair,
            "verifier": self.settings.alibaba_model_verifier,
        }
        configured = str(role_models.get(model_role, "")).strip()
        if configured:
            return configured
        return self._default_model_name_for_tier(tier)

    def _default_model_name_for_tier(self, tier: ModelTier) -> str:
        if tier == ModelTier.FLASH:
            return self.settings.alibaba_model_flash
        if tier == ModelTier.PLUS:
            return self.settings.alibaba_model_plus
        return self.settings.alibaba_model_max

    def _effective_tier_for_model_name(self, *, model_name: str, fallback: ModelTier) -> ModelTier:
        lowered = (model_name or "").strip().lower()
        if not lowered:
            return fallback

        if "max" in lowered:
            return ModelTier.MAX
        if "plus" in lowered:
            return ModelTier.PLUS
        if "flash" in lowered or "turbo" in lowered:
            return ModelTier.FLASH

        return fallback

    def _resolve_model_role(self, envelope: RequestEnvelope) -> str:
        metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}

        allowed_roles = {
            "default",
            "classification",
            "coding",
            "long_context",
            "planning",
            "reflection",
            "compression",
            "repair",
            "verifier",
        }
        explicit_role = str(metadata.get("model_role", "")).strip().lower()
        if explicit_role in allowed_roles:
            return explicit_role

        if bool(metadata.get("require_verification", False)):
            return "verifier"

        task_type = str(metadata.get("task_type", "")).strip().lower()
        task_role_map = {
            "action_planning": "planning",
            "planning": "planning",
            "architecture": "long_context",
            "reflection": "reflection",
            "repair": "repair",
            "summarize": "compression",
            "debugging": "coding",
            "generation": "coding",
            "classification": "classification",
            "verify": "verifier",
        }
        mapped = task_role_map.get(task_type)
        if mapped is not None:
            return mapped

        retrieval = metadata.get("retrieval") if isinstance(metadata.get("retrieval"), dict) else {}
        intent = str(retrieval.get("user_intent") or "").strip().lower()
        if intent == "architecture":
            return "long_context"
        if intent in {"refactor", "debug"}:
            return "coding"

        return "default"

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
