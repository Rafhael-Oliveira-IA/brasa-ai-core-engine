from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import MemoryEntry, MemoryScope, RequestEnvelope
from app.memory.repository import MemoryRepository
from app.retrieval import ContextRetrievalEngine


class StubEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_retrieval_engine_applies_semantic_scoring_when_embedding_client_is_available() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")
        repository.add_entry(
            MemoryEntry(
                project_id="MMO",
                user_id="u1",
                scope=MemoryScope.PROJECT,
                content="Inventory event ordering and database consistency.",
                confidence=0.9,
            )
        )

        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa" / "projects",
            embedding_client=StubEmbeddingClient(),
            max_chars=2500,
        )

        envelope = RequestEnvelope(
            project_id="MMO",
            user_id="u1",
            prompt="inventory consistency",
        )

        packet, retrieval = engine.assemble(envelope)

        assert packet.snippets
        assert retrieval.assembled["semantic_retrieval"]["enabled"] is True
        assert retrieval.assembled["semantic_retrieval"]["status"] == "ok"

        first = retrieval.assembled["contexts"][0]
        assert first["scores"]["semantic_score"] > 0.0
        assert first["scores"]["blended_relevance_score"] >= first["scores"]["relevance_score"]
