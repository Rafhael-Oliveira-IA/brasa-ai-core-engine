from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.action_engine import CognitiveActionEngine
from app.context_builder import ContextBuilder
from app.contracts import (
    ActionExecutionOptions,
    ActionExecuteRequest,
    ActionPlan,
    ActionPlanRequest,
    ActionRisk,
    ActionStep,
    ActionType,
    MemoryEntry,
    MemoryScope,
    OrchestratorDecision,
    OrchestratorDecisionState,
    OrchestratorIterationReport,
    OrchestratorMode,
    OrchestratorRunReport,
    OrchestratorRunRequest,
    RequestEnvelope,
)
from app.evaluation.engine import EvaluationEngine
from app.ingestion.pipeline import ProjectIngestionPipeline
from app.knowledge.compiler import KnowledgeCompiler
from app.memory.repository import MemoryRepository
from app.reflection.nightly_reflection import ReflectionService


RISK_LEVEL = {
    ActionRisk.LOW: 1,
    ActionRisk.MEDIUM: 2,
    ActionRisk.HIGH: 3,
    ActionRisk.CRITICAL: 4,
}


class OrchestratorDecisionPolicy:
    def decide(self, *, plan: ActionPlan, request: OrchestratorRunRequest) -> OrchestratorDecision:
        if not plan.actions:
            return OrchestratorDecision(
                state=OrchestratorDecisionState.BLOCKED,
                highest_risk=ActionRisk.LOW,
                execute_now=False,
                reason="Planner produced no actions.",
            )

        highest_risk = self._highest_risk(plan.actions)

        if self._requires_patch_authoring(plan.actions):
            return OrchestratorDecision(
                state=OrchestratorDecisionState.REQUIRES_APPROVAL,
                highest_risk=highest_risk,
                execute_now=False,
                reason="Planned mutations require explicit diff/content authoring before execution.",
            )

        if highest_risk == ActionRisk.CRITICAL:
            if request.block_critical_risk:
                return OrchestratorDecision(
                    state=OrchestratorDecisionState.BLOCKED,
                    highest_risk=highest_risk,
                    execute_now=False,
                    reason="Critical-risk plan blocked by policy.",
                )

            return OrchestratorDecision(
                state=OrchestratorDecisionState.REQUIRES_APPROVAL,
                highest_risk=highest_risk,
                execute_now=False,
                reason="Critical-risk plan requires explicit human approval.",
            )

        if request.mode == OrchestratorMode.MANUAL:
            return OrchestratorDecision(
                state=OrchestratorDecisionState.REQUIRES_APPROVAL,
                highest_risk=highest_risk,
                execute_now=False,
                reason="Manual mode requires explicit approval before execution.",
            )

        if highest_risk == ActionRisk.HIGH:
            if not request.allow_high_risk:
                return OrchestratorDecision(
                    state=OrchestratorDecisionState.BLOCKED,
                    highest_risk=highest_risk,
                    execute_now=False,
                    reason="High-risk actions blocked unless allow_high_risk=true.",
                )

            return OrchestratorDecision(
                state=OrchestratorDecisionState.REQUIRES_APPROVAL,
                highest_risk=highest_risk,
                execute_now=False,
                reason="High-risk actions require explicit confirmation.",
            )

        if highest_risk == ActionRisk.MEDIUM and not request.auto_execute_medium_risk:
            return OrchestratorDecision(
                state=OrchestratorDecisionState.REQUIRES_APPROVAL,
                highest_risk=highest_risk,
                execute_now=False,
                reason="Medium-risk actions require approval by current policy.",
            )

        if highest_risk == ActionRisk.LOW and not request.auto_execute_low_risk:
            return OrchestratorDecision(
                state=OrchestratorDecisionState.REQUIRES_APPROVAL,
                highest_risk=highest_risk,
                execute_now=False,
                reason="Low-risk auto-execution disabled by policy.",
            )

        return OrchestratorDecision(
            state=OrchestratorDecisionState.AUTO_EXECUTE,
            highest_risk=highest_risk,
            execute_now=True,
            reason="Autopilot policy authorized execution for current risk profile.",
        )

    def _highest_risk(self, actions: list[ActionStep]) -> ActionRisk:
        current = ActionRisk.LOW
        for action in actions:
            if RISK_LEVEL[action.risk] > RISK_LEVEL[current]:
                current = action.risk
        return current

    def _requires_patch_authoring(self, actions: list[ActionStep]) -> bool:
        for action in actions:
            if action.type in {ActionType.UPDATE_FILE, ActionType.PATCH_FILE}:
                if action.content is None and not action.patches:
                    return True
        return False


class CognitiveOrchestrator:
    def __init__(
        self,
        *,
        action_engine: CognitiveActionEngine,
        context_builder: ContextBuilder,
        ingestion_pipeline: ProjectIngestionPipeline,
        knowledge_compiler: KnowledgeCompiler,
        evaluation_engine: EvaluationEngine,
        reflection: ReflectionService,
        memory_repository: MemoryRepository,
    ) -> None:
        self.action_engine = action_engine
        self.context_builder = context_builder
        self.ingestion_pipeline = ingestion_pipeline
        self.knowledge_compiler = knowledge_compiler
        self.evaluation_engine = evaluation_engine
        self.reflection = reflection
        self.memory_repository = memory_repository
        self.policy = OrchestratorDecisionPolicy()

    def run(self, request: OrchestratorRunRequest) -> OrchestratorRunReport:
        report = OrchestratorRunReport(
            run_id=request.run_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            user_id=request.user_id,
            mode=request.mode,
            final_state=OrchestratorDecisionState.REQUIRES_APPROVAL,
        )

        seen_signatures: set[str] = set()

        for iteration in range(1, request.max_iterations + 1):
            plan_request = ActionPlanRequest(
                plan_id=f"{request.run_id}-iter-{iteration}",
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                user_id=request.user_id,
                prompt=request.intent,
                metadata={
                    **request.metadata,
                    "orchestrator_run_id": request.run_id,
                    "orchestrator_iteration": iteration,
                },
                max_actions=12,
            )
            plan, _ = self.action_engine.plan(plan_request)

            signature = self._plan_signature(plan)
            if signature in seen_signatures and iteration > 1:
                decision = OrchestratorDecision(
                    state=OrchestratorDecisionState.REQUIRES_APPROVAL,
                    highest_risk=self.policy._highest_risk(plan.actions) if plan.actions else ActionRisk.LOW,
                    execute_now=False,
                    reason="Planner returned duplicate action graph; loop halted.",
                )
                report.iterations.append(
                    OrchestratorIterationReport(
                        iteration=iteration,
                        plan=plan,
                        decision=decision,
                        notes=[decision.reason],
                    )
                )
                report.final_state = decision.state
                break
            seen_signatures.add(signature)

            decision = self.policy.decide(plan=plan, request=request)
            iteration_report = OrchestratorIterationReport(
                iteration=iteration,
                plan=plan,
                decision=decision,
            )

            if not decision.execute_now:
                iteration_report.notes.append(decision.reason)
                report.iterations.append(iteration_report)
                report.final_state = decision.state
                break

            execution = self.action_engine.execute(
                ActionExecuteRequest(
                    workspace_id=request.workspace_id,
                    project_id=request.project_id,
                    user_id=request.user_id,
                    plan=plan,
                    options=ActionExecutionOptions(
                        dry_run=request.dry_run,
                        allow_high_risk=request.allow_high_risk,
                        auto_rollback_on_error=True,
                        run_feedback_loop=False,
                    ),
                )
            )
            iteration_report.execution = execution
            report.iterations.append(iteration_report)

            if execution.failed > 0:
                iteration_report.notes.append("Execution failed and loop halted.")
                report.final_state = OrchestratorDecisionState.BLOCKED
                break

            if request.dry_run or execution.applied == 0:
                iteration_report.notes.append("No changes applied; loop halted for review.")
                report.final_state = OrchestratorDecisionState.REQUIRES_APPROVAL
                break

            iteration_report.ingestion = self._post_action_ingestion(request=request, notes=iteration_report.notes)
            iteration_report.context_refresh = self._refresh_context(request=request, iteration=iteration)
            iteration_report.evaluation = self._run_evaluation(request=request, notes=iteration_report.notes)
            if request.run_reflection:
                iteration_report.reflection = self._run_reflection(request=request, notes=iteration_report.notes)

            self._persist_memory(
                request=request,
                iteration=iteration,
                iteration_report=iteration_report,
            )

            if not self._should_continue_loop(request=request, iteration_report=iteration_report):
                report.final_state = OrchestratorDecisionState.AUTO_EXECUTE
                break

        if not report.iterations:
            report.notes.append("No iterations executed.")

        report.finished_at = datetime.now(timezone.utc)
        return report

    def _post_action_ingestion(self, *, request: OrchestratorRunRequest, notes: list[str]) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        if request.project_path:
            try:
                ingestion_report = self.ingestion_pipeline.run(
                    project_path=Path(request.project_path),
                    workspace_id=request.workspace_id,
                    force=False,
                )
                payload["ingestion"] = self._to_payload(ingestion_report)
            except Exception as exc:
                notes.append(f"ingestion_failed: {exc}")

        try:
            knowledge_sync = self.knowledge_compiler.sync(force=False)
            payload["knowledge_sync"] = self._to_payload(knowledge_sync)

            drift = int(self.knowledge_compiler.estimate_drift())
            payload["drift_detected"] = drift
            if drift > 0:
                notes.append(f"knowledge_drift_detected:{drift}")
        except Exception as exc:
            notes.append(f"knowledge_sync_failed: {exc}")

        return payload

    def _refresh_context(self, *, request: OrchestratorRunRequest, iteration: int) -> dict[str, Any]:
        envelope = RequestEnvelope(
            request_id=f"{request.run_id}-context-{iteration}",
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            user_id=request.user_id,
            prompt=request.intent,
            metadata={
                **request.metadata,
                "orchestrator_run_id": request.run_id,
                "orchestrator_iteration": iteration,
            },
        )
        packet, retrieval = self.context_builder.build(envelope)
        assembled = retrieval.assembled or {}

        return {
            "context_count": len(packet.snippets),
            "sources": packet.provenance[:20],
            "user_intent": assembled.get("user_intent", "general-query"),
            "relevant_systems": assembled.get("relevant_systems", [])[:20],
            "risks": assembled.get("risks", [])[:10],
        }

    def _run_evaluation(self, *, request: OrchestratorRunRequest, notes: list[str]) -> dict[str, Any]:
        evaluation = self.evaluation_engine.run(
            limit=request.evaluation_limit,
            project_id=request.project_id,
            user_id=request.user_id,
        )
        gate = self._evaluation_gate(evaluation.metrics)
        if gate["status"] != "healthy":
            notes.append(
                f"evaluation_gate={gate['status']}: "
                f"hallucination_rate={evaluation.metrics.get('hallucination_rate', 0.0)}"
            )

        return {
            "report_id": evaluation.report_id,
            "sample_size": evaluation.sample_size,
            "metrics": evaluation.metrics,
            "notes": evaluation.notes[:8],
            "gate": gate,
        }

    def _run_reflection(self, *, request: OrchestratorRunRequest, notes: list[str]) -> dict[str, Any]:
        reflection_report = self.reflection.run_once(
            trigger="orchestrator",
            project_id=request.project_id,
            user_id=request.user_id,
        )
        if reflection_report.low_confidence_entries > 0:
            notes.append(
                f"reflection_low_confidence={reflection_report.low_confidence_entries}"
            )

        return {
            "task_id": reflection_report.task_id,
            "summary_entry_id": reflection_report.summary_entry_id,
            "duplicates_removed": reflection_report.duplicates_removed,
            "low_confidence_entries": reflection_report.low_confidence_entries,
            "notes": reflection_report.notes[:8],
        }

    def _should_continue_loop(
        self,
        *,
        request: OrchestratorRunRequest,
        iteration_report: OrchestratorIterationReport,
    ) -> bool:
        if request.mode != OrchestratorMode.AUTOPILOT:
            return False

        if iteration_report.iteration >= request.max_iterations:
            return False

        evaluation_payload = iteration_report.evaluation
        gate = evaluation_payload.get("gate", {}) if isinstance(evaluation_payload, dict) else {}
        status = str(gate.get("status") or "healthy").lower()

        return status in {"degraded", "critical"}

    def _persist_memory(
        self,
        *,
        request: OrchestratorRunRequest,
        iteration: int,
        iteration_report: OrchestratorIterationReport,
    ) -> None:
        execution = iteration_report.execution
        applied = execution.applied if execution is not None else 0
        failed = execution.failed if execution is not None else 0
        changed_files = execution.changed_files if execution is not None else []

        self.memory_repository.add_entry(
            MemoryEntry(
                project_id=request.project_id,
                user_id=request.user_id,
                scope=MemoryScope.PROJECT,
                content=(
                    f"Orchestrator run {request.run_id} iteration {iteration}.\n"
                    f"Applied={applied}, Failed={failed}.\n"
                    f"Changed files: {', '.join(changed_files[:20])}."
                ),
                tags=["orchestrator", request.mode.value, "auto"],
                confidence=0.80,
                provenance={
                    "run_id": request.run_id,
                    "iteration": iteration,
                    "state": iteration_report.decision.state.value,
                },
            )
        )

    def _evaluation_gate(self, metrics: dict[str, float]) -> dict[str, Any]:
        hallucination_rate = float(metrics.get("hallucination_rate", 0.0))
        stale_context_rate = float(metrics.get("stale_context_rate", 0.0))
        retrieval_precision = float(metrics.get("retrieval_precision", 0.0))

        status = "healthy"
        if hallucination_rate >= 0.40 or stale_context_rate >= 0.60:
            status = "critical"
        elif hallucination_rate >= 0.25 or stale_context_rate >= 0.35 or retrieval_precision <= 0.30:
            status = "degraded"

        return {
            "status": status,
            "hallucination_rate": hallucination_rate,
            "stale_context_rate": stale_context_rate,
            "retrieval_precision": retrieval_precision,
        }

    def _plan_signature(self, plan: ActionPlan) -> str:
        if not plan.actions:
            return ""
        parts = [
            f"{action.type.value}:{action.target}:{action.intent[:120]}"
            for action in plan.actions
        ]
        return "|".join(parts)

    def _to_payload(self, value: object) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump(mode="json")
            except Exception:
                pass

        if isinstance(value, dict):
            return value

        if hasattr(value, "__dict__"):
            return {
                key: raw
                for key, raw in value.__dict__.items()
                if not key.startswith("_")
            }

        return {"value": str(value)}
