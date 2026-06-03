from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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
    ) -> None:
        self.memory_repository = memory_repository
        self.max_chars = max_chars
        self.knowledge_compiler = knowledge_compiler
        self.project_artifacts_root = project_artifacts_root or (Path(".") / ".brasa" / "projects")
        self.retrieval_engine = ContextRetrievalEngine(
            memory_repository=self.memory_repository,
            knowledge_compiler=self.knowledge_compiler,
            project_artifacts_root=self.project_artifacts_root,
            max_chars=self.max_chars,
        )

    def build(self, envelope: RequestEnvelope) -> tuple[ContextPacket, RetrievalResult]:
        return self.retrieval_engine.assemble(envelope)
