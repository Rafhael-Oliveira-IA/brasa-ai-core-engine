from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.context_builder import ContextBuilder
from app.contracts import MemoryEntry, MemoryScope, RequestEnvelope
from app.knowledge.models import KnowledgeLevel, KnowledgeNode
from app.memory.repository import MemoryRepository


class StubKnowledgeCompiler:
    def search(self, query: str, limit: int = 4) -> list[KnowledgeNode]:
        return [
            KnowledgeNode(
                node_id="module:Inventory",
                level=KnowledgeLevel.MODULE,
                title="Module Inventory",
                source_path="Inventory",
                source_hash="abc123",
                confidence=0.88,
                summary="Inventory module summary for retrieval context.",
            )
        ]


def test_context_builder_merges_memory_and_knowledge_snippets() -> None:
    with TemporaryDirectory() as temp_dir:
        repository = MemoryRepository(Path(temp_dir) / "memory.db")
        repository.add_entry(
            MemoryEntry(
                project_id="p1",
                user_id="u1",
                scope=MemoryScope.EPISODIC,
                content="Memory snippet about inventory syncing",
                confidence=0.8,
            )
        )

        builder = ContextBuilder(
            memory_repository=repository,
            knowledge_compiler=StubKnowledgeCompiler(),
        )

        envelope = RequestEnvelope(
            project_id="p1",
            user_id="u1",
            prompt="inventory synchronization architecture",
        )

        packet, _ = builder.build(envelope)
        sources = set(packet.provenance)

        assert any(source.startswith("memory:") for source in sources)
        assert any(source.startswith("knowledge:") for source in sources)
