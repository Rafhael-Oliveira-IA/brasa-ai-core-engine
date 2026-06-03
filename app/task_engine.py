from __future__ import annotations

from time import perf_counter

from app.context_builder import ContextBuilder
from app.contracts import (
    MemoryEntry,
    MemoryScope,
    RequestEnvelope,
    RetrievalResult,
    TaskRequest,
    TaskResponse,
    TaskStageResult,
    TaskType,
)
from app.memory.repository import MemoryRepository
from app.reflection.nightly_reflection import ReflectionService
from app.router import AIRouter
from app.telemetry.tracing import TraceLogger


TASK_DIRECTIVES: dict[TaskType, str] = {
    TaskType.CHAT: "Respond with practical guidance.",
    TaskType.SUMMARIZE: "Create a concise technical summary with key systems, risks, and next actions.",
    TaskType.REASONING: "Show a structured line of reasoning with assumptions and trade-offs.",
    TaskType.REFLECTION: "Analyze previous decisions, call out quality gaps, and propose corrections.",
    TaskType.REPAIR: "Propose concrete repair steps for stale or inconsistent project knowledge.",
    TaskType.PLANNING: "Produce an execution plan with milestones, dependencies, and risks.",
    TaskType.ARCHITECTURE: "Focus on architecture-level trade-offs, boundaries, and evolution strategy.",
    TaskType.DEBUGGING: "Prioritize root-cause analysis, hypotheses, and verifiable fixes.",
    TaskType.GENERATION: "Generate implementation-ready output with constraints and validation notes.",
}


class CognitiveTaskEngine:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        router: AIRouter,
        telemetry: TraceLogger,
        memory_repository: MemoryRepository,
        reflection: ReflectionService | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.router = router
        self.telemetry = telemetry
        self.memory_repository = memory_repository
        self.reflection = reflection

    async def run(self, task: TaskRequest) -> tuple[TaskResponse, RetrievalResult]:
        pipeline: list[TaskStageResult] = []

        intent_started = perf_counter()
        task_prompt = self._task_prompt(task)
        envelope = RequestEnvelope(
            request_id=task.task_id,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            user_id=task.user_id,
            prompt=task_prompt,
            tier_hint=task.tier_hint,
            metadata={
                **task.metadata,
                "task_type": task.task_type.value,
                "task_engine_version": "v1",
            },
        )
        pipeline.append(
            TaskStageResult(
                stage="intent_analysis",
                took_ms=self._elapsed_ms(intent_started),
                details={
                    "task_type": task.task_type.value,
                    "prompt_chars": len(task.prompt),
                },
            )
        )

        retrieval_started = perf_counter()
        context_packet, retrieval = self.context_builder.build(envelope)
        assembled = retrieval.assembled or {}
        pipeline.append(
            TaskStageResult(
                stage="context_retrieval",
                took_ms=self._elapsed_ms(retrieval_started),
                details={
                    "user_intent": assembled.get("user_intent", "general-query"),
                    "context_count": len(context_packet.snippets),
                    "hot_context": len(assembled.get("hot_context", [])),
                },
            )
        )

        graph_started = perf_counter()
        pipeline.append(
            TaskStageResult(
                stage="graph_expansion",
                took_ms=self._elapsed_ms(graph_started),
                details={
                    "relevant_systems": len(assembled.get("relevant_systems", [])),
                    "dependencies": len(assembled.get("dependencies", [])),
                },
            )
        )

        routing_started = perf_counter()
        routing_metadata = dict(envelope.metadata)
        routing_metadata["retrieval"] = assembled
        routing_envelope = envelope.model_copy(update={"metadata": routing_metadata})

        response, decision = await self.router.generate(
            envelope=routing_envelope,
            context=context_packet,
        )
        pipeline.append(
            TaskStageResult(
                stage="reasoning",
                took_ms=self._elapsed_ms(routing_started),
                details={
                    "provider": decision.provider,
                    "tier": decision.selected_tier.value,
                    "estimated_cost_usd": decision.estimated_cost_usd,
                },
            )
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

        memory_started = perf_counter()
        if task.options.persist_memory:
            auto_memory = MemoryEntry(
                project_id=envelope.project_id,
                user_id=task.user_id,
                scope=MemoryScope.EPISODIC,
                content=(
                    f"TaskType: {task.task_type.value}\n"
                    f"Request: {task.prompt[:600]}\n"
                    f"Response: {response.answer[:1200]}"
                ),
                tags=["task", task.task_type.value, "auto"],
                confidence=max(0.45, min(0.90, response.confidence - 0.05)),
                provenance={
                    "trace_id": trace_id,
                    "selected_tier": decision.selected_tier.value,
                    "provider": decision.provider,
                },
            )
            self.memory_repository.add_entry(auto_memory)
            pipeline.append(
                TaskStageResult(
                    stage="memory_update",
                    took_ms=self._elapsed_ms(memory_started),
                    details={"stored": True},
                )
            )
        else:
            pipeline.append(
                TaskStageResult(
                    stage="memory_update",
                    status="skipped",
                    took_ms=self._elapsed_ms(memory_started),
                    details={"stored": False},
                )
            )

        if task.options.run_reflection:
            reflection_started = perf_counter()
            if self.reflection is None:
                pipeline.append(
                    TaskStageResult(
                        stage="reflection",
                        status="skipped",
                        took_ms=self._elapsed_ms(reflection_started),
                        details={"reason": "reflection service not configured"},
                    )
                )
            else:
                reflection_report = self.reflection.run_once(
                    trigger="task",
                    project_id=envelope.project_id,
                    user_id=task.user_id,
                )
                pipeline.append(
                    TaskStageResult(
                        stage="reflection",
                        took_ms=self._elapsed_ms(reflection_started),
                        details={
                            "summary_entry_id": reflection_report.summary_entry_id,
                            "duplicates_removed": reflection_report.duplicates_removed,
                        },
                    )
                )

        task_response = TaskResponse(
            task_id=task.task_id,
            task_type=task.task_type,
            answer=response.answer,
            confidence=response.confidence,
            route=decision,
            context_sources=context_packet.provenance,
            trace_id=trace_id,
            pipeline=pipeline,
            retrieval={
                "user_intent": assembled.get("user_intent", "general-query"),
                "relevant_systems": assembled.get("relevant_systems", []),
                "dependencies": assembled.get("dependencies", []),
                "risks": assembled.get("risks", []),
                "compression": assembled.get("compression", {}),
            },
        )

        return task_response, retrieval

    def _task_prompt(self, task: TaskRequest) -> str:
        directive = TASK_DIRECTIVES.get(task.task_type, TASK_DIRECTIVES[TaskType.CHAT])
        if task.task_type == TaskType.CHAT:
            return task.prompt

        return (
            f"TaskType: {task.task_type.value}\n"
            f"Directive: {directive}\n\n"
            f"UserRequest:\n{task.prompt}"
        )

    def _elapsed_ms(self, started: float) -> int:
        return int((perf_counter() - started) * 1000)
