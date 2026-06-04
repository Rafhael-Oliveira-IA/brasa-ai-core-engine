from __future__ import annotations

from app.context_builder import ContextBuilder
from app.contracts import ChatResponse, MemoryEntry, MemoryScope, RequestEnvelope, RetrievalResult
from app.memory.repository import MemoryRepository
from app.router import AIRouter
from app.telemetry.tracing import TraceLogger


class CognitiveQueryEngine:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        router: AIRouter,
        telemetry: TraceLogger,
        memory_repository: MemoryRepository,
    ) -> None:
        self.context_builder = context_builder
        self.router = router
        self.telemetry = telemetry
        self.memory_repository = memory_repository

    async def run(self, envelope: RequestEnvelope) -> tuple[ChatResponse, RetrievalResult]:
        context_packet, retrieval = self.context_builder.build(envelope)

        routing_metadata = dict(envelope.metadata)
        routing_metadata["retrieval"] = retrieval.assembled
        routing_metadata["require_alibaba_final_response"] = True
        routing_metadata.setdefault("task_type", "chat")
        routing_envelope = envelope.model_copy(update={"metadata": routing_metadata})

        response, decision = await self.router.generate(
            envelope=routing_envelope,
            context=context_packet,
        )

        trace_id = self.telemetry.new_trace_id()
        self.telemetry.log_retrieval(
            trace_id=trace_id,
            envelope=envelope,
            retrieval=retrieval,
        )
        self.telemetry.log_route(
            trace_id=trace_id,
            envelope=envelope,
            decision=decision,
            response=response,
            retrieval=retrieval,
        )

        auto_memory = MemoryEntry(
            project_id=envelope.project_id,
            user_id=envelope.user_id,
            scope=MemoryScope.EPISODIC,
            content=(
                f"Request: {envelope.prompt[:600]}\n"
                f"Response: {response.answer[:1200]}"
            ),
            tags=["chat", "auto"],
            confidence=max(0.45, min(0.90, response.confidence - 0.05)),
            provenance={
                "trace_id": trace_id,
                "selected_tier": decision.selected_tier.value,
                "provider": decision.provider,
            },
        )
        self.memory_repository.add_entry(auto_memory)

        chat_response = ChatResponse(
            request_id=envelope.request_id,
            answer=response.answer,
            confidence=response.confidence,
            route=decision,
            context_sources=context_packet.provenance,
            trace_id=trace_id,
        )

        return chat_response, retrieval
