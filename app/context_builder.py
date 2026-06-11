from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.contracts import ContextPacket, RequestEnvelope, RetrievalResult
from app.memory.repository import MemoryRepository
from app.retrieval import ContextRetrievalEngine

if TYPE_CHECKING:
    from app.knowledge.compiler import KnowledgeCompiler


class ContextBuilder:
    def __init__(
        self,
        memory_repository: MemoryRepository,
        max_chars: int = 3500,
        knowledge_compiler: KnowledgeCompiler | None = None,
        project_artifacts_root: Path | None = None,
        embedding_client: object | None = None,
        retrieval_assist_provider: object | None = None,
        retrieval_assist_enabled: bool = False,
        retrieval_assist_model_name: str = "qwen-turbo-latest",
        retrieval_assist_min_candidates: int = 8,
        retrieval_assist_timeout_seconds: float = 12.0,
        auto_reingest_on_weak_context: bool = True,
        auto_reingest_min_selected_context: int = 2,
        auto_reingest_cooldown_seconds: int = 120,
    ) -> None:
        self.memory_repository = memory_repository
        self.max_chars = max_chars
        self.knowledge_compiler = knowledge_compiler
        self.project_artifacts_root = project_artifacts_root or (Path(".") / ".brasa" / "projects")
        self.embedding_client = embedding_client
        self.auto_reingest_on_weak_context = auto_reingest_on_weak_context
        self.auto_reingest_min_selected_context = max(1, int(auto_reingest_min_selected_context))
        self.auto_reingest_cooldown_seconds = max(0, int(auto_reingest_cooldown_seconds))
        self._last_auto_reingest_at: datetime | None = None
        self.retrieval_engine = ContextRetrievalEngine(
            memory_repository=self.memory_repository,
            knowledge_compiler=self.knowledge_compiler,
            project_artifacts_root=self.project_artifacts_root,
            max_chars=self.max_chars,
            embedding_client=self.embedding_client,
            retrieval_assist_provider=retrieval_assist_provider,
            retrieval_assist_enabled=retrieval_assist_enabled,
            retrieval_assist_model_name=retrieval_assist_model_name,
            retrieval_assist_min_candidates=retrieval_assist_min_candidates,
            retrieval_assist_timeout_seconds=retrieval_assist_timeout_seconds,
        )

    def build(self, envelope: RequestEnvelope) -> tuple[ContextPacket, RetrievalResult]:
        packet, retrieval = self.retrieval_engine.assemble(envelope)
        diagnostics = self._auto_reingest_diagnostics(
            envelope=envelope,
            packet=packet,
            retrieval=retrieval,
        )

        if diagnostics.get("triggered"):
            sync_payload = self._run_auto_reingest_sync()
            diagnostics["sync"] = sync_payload
            if sync_payload.get("status") == "ok":
                packet, retrieval = self.retrieval_engine.assemble(envelope)

        assembled = retrieval.assembled if isinstance(retrieval.assembled, dict) else {}
        assembled["auto_reingest"] = diagnostics
        retrieval = retrieval.model_copy(update={"assembled": assembled})
        return packet, retrieval

    def _auto_reingest_diagnostics(
        self,
        *,
        envelope: RequestEnvelope,
        packet: ContextPacket,
        retrieval: RetrievalResult,
    ) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {
            "triggered": False,
            "reason": "not_needed",
            "is_chat": self._is_chat_request(envelope),
        }

        if not diagnostics["is_chat"]:
            diagnostics["reason"] = "non_chat_request"
            return diagnostics

        if not self.auto_reingest_on_weak_context:
            diagnostics["reason"] = "disabled"
            return diagnostics

        if self._knowledge_sync_fn() is None:
            diagnostics["reason"] = "sync_unavailable"
            return diagnostics

        if self._is_reingest_cooldown_active():
            diagnostics["reason"] = "cooldown_active"
            return diagnostics

        weak, reasons = self._is_weak_chat_context(packet=packet, retrieval=retrieval)
        diagnostics["context_reasons"] = reasons
        if not weak:
            diagnostics["reason"] = "context_sufficient"
            return diagnostics

        diagnostics["triggered"] = True
        diagnostics["reason"] = "weak_context"
        return diagnostics

    def _is_chat_request(self, envelope: RequestEnvelope) -> bool:
        metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}
        task_type = str(metadata.get("task_type", "")).strip().lower()
        return task_type == "chat"

    def _is_weak_chat_context(
        self,
        *,
        packet: ContextPacket,
        retrieval: RetrievalResult,
    ) -> tuple[bool, list[str]]:
        assembled = retrieval.assembled if isinstance(retrieval.assembled, dict) else {}
        compression = assembled.get("compression") if isinstance(assembled.get("compression"), dict) else {}
        selected_count = int(compression.get("selected_count") or len(packet.snippets))
        dropped_count = int(compression.get("dropped_count") or 0)
        artifact_sources = [
            source
            for source in packet.provenance
            if str(source).startswith("artifact:file:")
        ]
        risks = [str(item).lower() for item in assembled.get("risks", [])]

        reasons: list[str] = []
        if selected_count < self.auto_reingest_min_selected_context:
            reasons.append("low_selected_context")
        if not artifact_sources and selected_count <= self.auto_reingest_min_selected_context:
            reasons.append("no_artifact_sources")
        if any("no relevant context selected" in risk for risk in risks):
            reasons.append("no_relevant_context")
        if any("stale" in risk for risk in risks):
            reasons.append("stale_context_signal")
        if dropped_count >= 10 and selected_count <= 1:
            reasons.append("high_drop_low_selection")

        return bool(reasons), reasons

    def _is_reingest_cooldown_active(self) -> bool:
        if self.auto_reingest_cooldown_seconds <= 0:
            return False
        if self._last_auto_reingest_at is None:
            return False
        return datetime.now(timezone.utc) < (
            self._last_auto_reingest_at + timedelta(seconds=self.auto_reingest_cooldown_seconds)
        )

    def _knowledge_sync_fn(self):
        if self.knowledge_compiler is None:
            return None
        sync_fn = getattr(self.knowledge_compiler, "sync", None)
        if callable(sync_fn):
            return sync_fn
        return None

    def _run_auto_reingest_sync(self) -> dict[str, Any]:
        sync_fn = self._knowledge_sync_fn()
        if sync_fn is None:
            return {
                "status": "unavailable",
                "notes": ["knowledge compiler sync() is unavailable"],
            }

        try:
            report = sync_fn(force=False)
        except Exception as exc:
            return {
                "status": "failed",
                "notes": [f"auto reingest failed: {exc}"],
            }

        self._last_auto_reingest_at = datetime.now(timezone.utc)

        return {
            "status": "ok",
            "scanned_files": int(getattr(report, "scanned_files", 0) or 0),
            "changed_nodes": int(getattr(report, "changed_nodes", 0) or 0),
            "stale_nodes": int(getattr(report, "stale_nodes", 0) or 0),
            "notes": [str(item) for item in (getattr(report, "notes", []) or [])][:6],
        }
