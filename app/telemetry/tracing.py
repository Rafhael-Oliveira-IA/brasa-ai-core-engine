from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.contracts import (
    CognitiveFeedbackEntry,
    ProviderResponse,
    RequestEnvelope,
    RetrievalResult,
    RouteDecision,
    TraceEvent,
)


class TraceLogger:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def new_trace_id(self) -> str:
        return str(uuid4())

    def emit(self, event: TraceEvent) -> None:
        payload = event.model_dump(mode="json")
        line = json.dumps(payload, ensure_ascii=True)
        with self._lock:
            with self.file_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def log_route(
        self,
        *,
        trace_id: str,
        envelope: RequestEnvelope,
        decision: RouteDecision,
        response: ProviderResponse,
        retrieval: RetrievalResult,
    ) -> None:
        event = TraceEvent(
            trace_id=trace_id,
            request_id=envelope.request_id,
            event_type="route.decision",
            payload={
                "project_id": envelope.project_id,
                "user_id": envelope.user_id,
                "selected_tier": decision.selected_tier.value,
                "provider": decision.provider,
                "model": decision.model_name,
                "reason": decision.reason,
                "confidence": response.confidence,
                "usage": {
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "total_tokens": response.total_tokens,
                    "cost_usd": response.cost_usd,
                },
                "retrieval": {
                    **self._retrieval_metrics(retrieval),
                },
            },
        )
        self.emit(event)

    def log_retrieval(
        self,
        *,
        trace_id: str,
        envelope: RequestEnvelope,
        retrieval: RetrievalResult,
    ) -> None:
        assembled = retrieval.assembled or {}
        event = TraceEvent(
            trace_id=trace_id,
            request_id=envelope.request_id,
            event_type="retrieval.assembly",
            payload={
                "project_id": envelope.project_id,
                "user_id": envelope.user_id,
                "query": envelope.prompt[:240],
                "user_intent": assembled.get("user_intent", "general-query"),
                "relevant_systems": assembled.get("relevant_systems", []),
                "dependencies_count": len(assembled.get("dependencies", [])),
                "risks": assembled.get("risks", []),
                "retrieval": self._retrieval_metrics(retrieval),
            },
        )
        self.emit(event)

    def log_feedback(self, *, trace_id: str, entry: CognitiveFeedbackEntry) -> None:
        event = TraceEvent(
            trace_id=trace_id,
            request_id=entry.request_id or "feedback-only",
            event_type="cognitive.feedback",
            payload={
                "workspace_id": entry.workspace_id,
                "project_id": entry.project_id,
                "user_id": entry.user_id,
                "query": entry.query[:240],
                "request_id": entry.request_id,
                "verdict": entry.verdict.value,
                "issues": [item.value for item in entry.issues],
                "notes": entry.notes[:500],
            },
        )
        self.emit(event)

    def _retrieval_metrics(self, retrieval: RetrievalResult) -> dict[str, object]:
        assembled = retrieval.assembled or {}
        contexts = assembled.get("context_packet") or assembled.get("contexts") or []
        compression = assembled.get("compression", {})

        context_count = len(contexts)
        avg_score = 0.0
        hot_count = 0

        if context_count > 0:
            total_score = 0.0
            for item in contexts:
                if not isinstance(item, dict):
                    continue
                total_score += float(item.get("score", 0.0))
                if bool(item.get("hot", False)):
                    hot_count += 1

            avg_score = round(total_score / max(1, context_count), 4)

        return {
            "entries": len(retrieval.entries),
            "took_ms": retrieval.took_ms,
            "context_count": context_count,
            "avg_context_score": avg_score,
            "hot_context_count": hot_count,
            "dropped_by_budget": int(compression.get("dropped_count", 0)),
            "used_chars": int(compression.get("used_chars", 0)),
            "max_chars": int(compression.get("max_chars", 0)),
        }

    def read_recent(self, limit: int = 20) -> list[dict]:
        if not self.file_path.exists():
            return []

        lines = self.file_path.read_text(encoding="utf-8").splitlines()
        selected = lines[-max(1, min(limit, 200)) :]

        records: list[dict] = []
        for line in selected:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return records
