from __future__ import annotations

import json
from pathlib import Path

from app.contracts import EvaluationReport


class EvaluationEngine:
    def __init__(self, *, trace_file: Path, report_dir: Path) -> None:
        self.trace_file = trace_file
        self.report_dir = report_dir
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        limit: int = 300,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> EvaluationReport:
        records = self._read_trace_records()
        filtered = [
            item
            for item in records
            if self._matches_scope(item=item, project_id=project_id, user_id=user_id)
        ]

        if limit > 0:
            filtered = filtered[-limit:]

        retrieval_events = [item for item in filtered if item.get("event_type") == "retrieval.assembly"]
        route_events = [item for item in filtered if item.get("event_type") == "route.decision"]
        feedback_events = [item for item in filtered if item.get("event_type") == "cognitive.feedback"]

        retrieval_precision = self._retrieval_precision(retrieval_events)
        stale_context_rate = self._stale_context_rate(retrieval_events)
        hallucination_rate = self._hallucination_rate(route_events)
        architecture_consistency = self._architecture_consistency(retrieval_events)
        token_efficiency = self._token_efficiency(route_events)
        reasoning_success = self._reasoning_success(route_events)
        feedback_correct_rate = self._feedback_verdict_rate(feedback_events, verdict="correct")
        feedback_partial_rate = self._feedback_verdict_rate(feedback_events, verdict="partial")
        feedback_incorrect_rate = self._feedback_verdict_rate(feedback_events, verdict="incorrect")
        feedback_hallucination_rate = self._feedback_issue_rate(feedback_events, issue="hallucination")
        feedback_xml_missing_rate = self._feedback_issue_rate(feedback_events, issue="xml_missing")
        feedback_retrieval_incorrect_rate = self._feedback_issue_rate(feedback_events, issue="retrieval_incorrect")
        feedback_compression_bad_rate = self._feedback_issue_rate(feedback_events, issue="compression_bad")
        feedback_architectural_loss_rate = self._feedback_issue_rate(feedback_events, issue="architectural_loss")

        totals = self._route_totals(route_events)

        notes: list[str] = []
        if len(filtered) < 40:
            notes.append("Low sample size; evaluation confidence is limited.")
        if stale_context_rate >= 0.30:
            notes.append("High stale-context rate detected.")
        if hallucination_rate >= 0.20:
            notes.append("Potential hallucination pressure detected in high-confidence responses.")
        if token_efficiency <= 0.40:
            notes.append("Low token efficiency; context compression and ranking should be tuned.")
        if feedback_incorrect_rate >= 0.25:
            notes.append("User feedback indicates high incorrect-response rate.")
        if feedback_xml_missing_rate >= 0.20:
            notes.append("Frequent XML-missing reports detected; XML ranking should be boosted.")
        if feedback_hallucination_rate >= 0.15:
            notes.append("Frequent hallucination reports detected from daily usage feedback.")

        if not notes:
            notes.append("Evaluation completed without critical degradation signals.")

        report = EvaluationReport(
            project_id=project_id,
            user_id=user_id,
            sample_size=len(filtered),
            retrieval_samples=len(retrieval_events),
            route_samples=len(route_events),
            metrics={
                "retrieval_precision": retrieval_precision,
                "hallucination_rate": hallucination_rate,
                "stale_context_rate": stale_context_rate,
                "architectural_consistency": architecture_consistency,
                "token_efficiency": token_efficiency,
                "reasoning_success": reasoning_success,
                "feedback_correct_rate": feedback_correct_rate,
                "feedback_partial_rate": feedback_partial_rate,
                "feedback_incorrect_rate": feedback_incorrect_rate,
                "feedback_hallucination_rate": feedback_hallucination_rate,
                "feedback_xml_missing_rate": feedback_xml_missing_rate,
                "feedback_retrieval_incorrect_rate": feedback_retrieval_incorrect_rate,
                "feedback_compression_bad_rate": feedback_compression_bad_rate,
                "feedback_architectural_loss_rate": feedback_architectural_loss_rate,
            },
            totals=totals,
            notes=notes,
        )

        output_file = self.report_dir / f"evaluation-{report.report_id}.json"
        output_file.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

        return report

    def read_recent(self, *, limit: int = 20) -> list[dict]:
        if not self.report_dir.exists():
            return []

        files = sorted(self.report_dir.glob("evaluation-*.json"))
        selected = files[-max(1, min(limit, 100)) :]

        records: list[dict] = []
        for file in selected:
            try:
                records.append(json.loads(file.read_text(encoding="utf-8")))
            except Exception:
                continue

        return records

    def _read_trace_records(self) -> list[dict]:
        if not self.trace_file.exists():
            return []

        records: list[dict] = []
        for line in self.trace_file.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(payload, dict):
                records.append(payload)

        return records

    def _matches_scope(self, *, item: dict, project_id: str | None, user_id: str | None) -> bool:
        payload = item.get("payload") if isinstance(item, dict) else None
        if not isinstance(payload, dict):
            return False

        event_project = payload.get("project_id")
        event_user = payload.get("user_id")

        if project_id is not None and event_project != project_id:
            return False
        if user_id is not None and event_user != user_id:
            return False

        return True

    def _retrieval_precision(self, retrieval_events: list[dict]) -> float:
        if not retrieval_events:
            return 0.0

        values: list[float] = []
        for event in retrieval_events:
            retrieval = self._nested_dict(event, "payload", "retrieval")
            values.append(float(retrieval.get("avg_context_score", 0.0)))

        return self._average(values)

    def _hallucination_rate(self, route_events: list[dict]) -> float:
        if not route_events:
            return 0.0

        suspicious = 0
        for event in route_events:
            payload = self._nested_dict(event, "payload")
            confidence = float(payload.get("confidence", 0.0))
            retrieval = self._nested_dict(event, "payload", "retrieval")
            avg_context_score = float(retrieval.get("avg_context_score", 0.0))
            context_count = int(retrieval.get("context_count", 0))

            if confidence >= 0.82 and (avg_context_score < 0.25 or context_count == 0):
                suspicious += 1

        return round(suspicious / max(1, len(route_events)), 4)

    def _stale_context_rate(self, retrieval_events: list[dict]) -> float:
        if not retrieval_events:
            return 0.0

        stale_hits = 0
        for event in retrieval_events:
            payload = self._nested_dict(event, "payload")
            risks = payload.get("risks", [])
            risk_text = " | ".join(str(item).lower() for item in risks)
            if "stale" in risk_text:
                stale_hits += 1

        return round(stale_hits / max(1, len(retrieval_events)), 4)

    def _architecture_consistency(self, retrieval_events: list[dict]) -> float:
        if not retrieval_events:
            return 0.0

        consistent = 0
        for event in retrieval_events:
            payload = self._nested_dict(event, "payload")
            dependencies_count = int(payload.get("dependencies_count", 0))
            relevant_systems = payload.get("relevant_systems", [])
            systems_count = len(relevant_systems) if isinstance(relevant_systems, list) else 0

            if dependencies_count == 0 or systems_count > 0:
                consistent += 1

        return round(consistent / max(1, len(retrieval_events)), 4)

    def _token_efficiency(self, route_events: list[dict]) -> float:
        if not route_events:
            return 0.0

        scores: list[float] = []

        for event in route_events:
            retrieval = self._nested_dict(event, "payload", "retrieval")
            used_chars = int(retrieval.get("used_chars", 0))
            max_chars = int(retrieval.get("max_chars", 0))
            dropped = int(retrieval.get("dropped_by_budget", 0))
            context_count = int(retrieval.get("context_count", 0))

            utilization = (used_chars / max_chars) if max_chars > 0 else 0.0
            drop_rate = dropped / max(1, dropped + context_count)
            score = max(0.0, min(1.0, utilization * (1.0 - drop_rate)))
            scores.append(score)

        return self._average(scores)

    def _reasoning_success(self, route_events: list[dict]) -> float:
        if not route_events:
            return 0.0

        successful = 0
        for event in route_events:
            payload = self._nested_dict(event, "payload")
            confidence = float(payload.get("confidence", 0.0))
            reason = str(payload.get("reason", "")).lower()
            if confidence >= 0.75 and "fallback-local" not in reason:
                successful += 1

        return round(successful / max(1, len(route_events)), 4)

    def _feedback_verdict_rate(self, feedback_events: list[dict], *, verdict: str) -> float:
        if not feedback_events:
            return 0.0

        hits = 0
        for event in feedback_events:
            payload = self._nested_dict(event, "payload")
            if str(payload.get("verdict", "")).strip().lower() == verdict:
                hits += 1

        return round(hits / max(1, len(feedback_events)), 4)

    def _feedback_issue_rate(self, feedback_events: list[dict], *, issue: str) -> float:
        if not feedback_events:
            return 0.0

        hits = 0
        for event in feedback_events:
            payload = self._nested_dict(event, "payload")
            issues = payload.get("issues", [])
            if not isinstance(issues, list):
                continue
            if any(str(item).strip().lower() == issue for item in issues):
                hits += 1

        return round(hits / max(1, len(feedback_events)), 4)

    def _route_totals(self, route_events: list[dict]) -> dict[str, float]:
        total_cost = 0.0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0

        for event in route_events:
            usage = self._nested_dict(event, "payload", "usage")
            total_cost += float(usage.get("cost_usd", 0.0))
            total_prompt_tokens += int(usage.get("prompt_tokens", 0))
            total_completion_tokens += int(usage.get("completion_tokens", 0))
            total_tokens += int(usage.get("total_tokens", 0))

        return {
            "total_cost_usd": round(total_cost, 6),
            "prompt_tokens": float(total_prompt_tokens),
            "completion_tokens": float(total_completion_tokens),
            "total_tokens": float(total_tokens),
        }

    def _nested_dict(self, value: dict, *path: str) -> dict:
        current: object = value
        for part in path:
            if not isinstance(current, dict):
                return {}
            current = current.get(part)
        return current if isinstance(current, dict) else {}

    def _average(self, values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / max(1, len(values)), 4)
