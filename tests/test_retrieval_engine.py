from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import MemoryEntry, MemoryScope, RequestEnvelope
from app.memory.repository import MemoryRepository
from app.retrieval import ContextRetrievalEngine


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


class StubKnowledgeCompiler:
    def search(self, query: str, limit: int = 8) -> list:
        return []


def test_retrieval_engine_assembles_context_with_scores_and_dependencies() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        artifacts = root / ".brasa" / "projects" / "MMO"

        metadata_payload = {
            "path": "Inventory/InventoryManager.cs",
            "hash": "abc123",
            "language": "csharp",
            "modified_at": "2026-06-03T12:00:00+00:00",
            "size": 321,
            "module": "Inventory",
            "folder": "Inventory",
            "dependencies": ["ItemDatabase", "EventBus"],
            "symbols": ["InventoryManager"],
        }
        write_json(
            artifacts / "metadata" / "files" / "Inventory" / "InventoryManager.meta.json",
            metadata_payload,
        )
        write_text(
            artifacts / "summaries" / "files" / "Inventory" / "InventoryManager.summary.md",
            "# InventoryManager\n\nPurpose:\nHandles player inventory operations.\n",
        )
        write_json(
            artifacts / "graphs" / "dependencies.json",
            {
                "generated_at": "2026-06-03T12:00:00+00:00",
                "dependencies": {
                    "Inventory/InventoryManager.cs": ["ItemDatabase", "EventBus"]
                },
            },
        )

        repository = MemoryRepository(root / "memory.db")
        repository.add_entry(
            MemoryEntry(
                project_id="MMO",
                user_id="u1",
                scope=MemoryScope.PROJECT,
                content="Inventory refactor must preserve event ordering.",
                confidence=0.9,
            )
        )

        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa" / "projects",
            knowledge_compiler=StubKnowledgeCompiler(),
            max_chars=3000,
        )

        envelope = RequestEnvelope(
            project_id="MMO",
            user_id="u1",
            prompt="refatore o inventory mantendo eventos e database",
        )

        packet, retrieval = engine.assemble(envelope)

        assert packet.snippets
        assert retrieval.assembled["contexts"]
        assert retrieval.assembled["context_packet"]
        assert retrieval.assembled["user_intent"] == "refactor"
        assert "Inventory" in retrieval.assembled["relevant_systems"]
        assert "ItemDatabase" in retrieval.assembled["dependencies"]
        assert "EventBus" in retrieval.assembled["dependencies"]

        first = retrieval.assembled["contexts"][0]
        assert "scores" in first
        assert "relevance_score" in first["scores"]
        assert 0.0 <= first["scores"]["relevance_score"] <= 1.0


def test_retrieval_keeps_oversized_top_candidate_by_truncating() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        artifacts = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"

        giant_summary = "# actions\n" + ("itemid actionid uniqueid script register\n" * 800)
        write_json(
            artifacts / "metadata" / "files" / "data" / "actions" / "actions.meta.json",
            {
                "path": "data/actions/actions.xml",
                "hash": "abc123",
                "language": "xml",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "size": len(giant_summary),
                "module": "data",
                "folder": "data/actions",
                "dependencies": ["itemid", "actionid", "uniqueid", "script"],
                "symbols": ["action"],
            },
        )
        write_text(
            artifacts / "summaries" / "files" / "data" / "actions" / "actions.summary.md",
            giant_summary,
        )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            knowledge_compiler=StubKnowledgeCompiler(),
            max_chars=600,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id="mmo_workspace::SERVIDOR - ORIGINAL",
            user_id="u1",
            prompt="actions.xml itemid actionid uniqueid",
        )

        packet, retrieval = engine.assemble(envelope)

        assert packet.snippets
        assert packet.snippets[0].source == "artifact:file:data/actions/actions.xml"
        assert packet.snippets[0].content.endswith("...")
        used_chars = retrieval.assembled["compression"]["used_chars"]
        assert used_chars <= 600


def test_intent_terms_filter_stopwords_for_loot_queries() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa" / "projects",
            knowledge_compiler=StubKnowledgeCompiler(),
            max_chars=3000,
        )

        terms = engine._intent_terms("quais os loots do arcanine?")

        assert "os" not in terms
        assert "do" not in terms
        assert "arcanine" in terms
        assert "loots" in terms
        assert "loot" in terms
