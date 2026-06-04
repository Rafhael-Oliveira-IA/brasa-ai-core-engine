from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

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


class StubKnowledgeCompilerWithSync:
    def __init__(self) -> None:
        self.sync_calls = 0

    def search(self, query: str, limit: int = 4) -> list[KnowledgeNode]:
        return []

    def sync(self, *, force: bool = False, include_extensions: list[str] | None = None):
        self.sync_calls += 1
        return SimpleNamespace(
            scanned_files=12,
            changed_nodes=3,
            stale_nodes=1,
            notes=["Scanned 12 source files."],
        )


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


def test_context_builder_auto_reingests_for_weak_chat_context() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")
        compiler = StubKnowledgeCompilerWithSync()

        builder = ContextBuilder(
            memory_repository=repository,
            knowledge_compiler=compiler,
            project_artifacts_root=root / ".brasa",
            auto_reingest_on_weak_context=True,
            auto_reingest_cooldown_seconds=0,
        )

        envelope = RequestEnvelope(
            project_id="MMO",
            user_id="u1",
            prompt="como funciona o catch rate?",
            metadata={"task_type": "chat"},
        )

        _, retrieval = builder.build(envelope)

        auto_reingest = retrieval.assembled.get("auto_reingest", {})
        assert compiler.sync_calls == 1
        assert auto_reingest.get("triggered") is True
        assert auto_reingest.get("sync", {}).get("status") == "ok"


def test_context_builder_does_not_auto_reingest_for_non_chat_requests() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")
        compiler = StubKnowledgeCompilerWithSync()

        builder = ContextBuilder(
            memory_repository=repository,
            knowledge_compiler=compiler,
            project_artifacts_root=root / ".brasa",
            auto_reingest_on_weak_context=True,
            auto_reingest_cooldown_seconds=0,
        )

        envelope = RequestEnvelope(
            project_id="MMO",
            user_id="u1",
            prompt="planeje uma refatoracao",
            metadata={"task_type": "planning"},
        )

        _, retrieval = builder.build(envelope)

        auto_reingest = retrieval.assembled.get("auto_reingest", {})
        assert compiler.sync_calls == 0
        assert auto_reingest.get("triggered") is False
        assert auto_reingest.get("reason") == "non_chat_request"
