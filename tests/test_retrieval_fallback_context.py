from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import RequestEnvelope
from app.memory.repository import MemoryRepository
from app.retrieval import ContextRetrievalEngine
from app.workspace import scoped_project_id


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def test_retrieval_falls_back_to_src_artifacts_when_lexical_match_is_low() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "src" / "protocolgame.meta.json",
            {
                "path": "src/protocolgame.h",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["OpcodeMap"],
                "symbols": ["ProtocolGame"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "src" / "protocolgame.summary.md",
            "# protocol game\nhandles packet registration and protocol dispatch\n",
        )

        write_json(
            metadata_root / "src" / "raids.meta.json",
            {
                "path": "src/raids.h",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["SpawnManager"],
                "symbols": ["Raids"],
                "confidence": 0.86,
            },
        )
        write_text(
            summaries_root / "src" / "raids.summary.md",
            "# raids\nschedules and manages raid lifecycle\n",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=3000,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="consulta muito abstrata sem token literal de arquivo",
        )

        packet, retrieval = engine.assemble(envelope)

        assert packet.snippets
        assert retrieval.assembled["context_packet"]
        assert any(str(item.source).startswith("artifact:file:src/") for item in packet.snippets)


def test_retrieval_falls_back_to_unity_assets_when_lexical_match_is_low() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "unity_workspace" / "PokemonUnity"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "Assets" / "Scripts" / "Combat" / "AttackController.meta.json",
            {
                "path": "Assets/Scripts/Combat/AttackController.cs",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["Animator", "DamageService"],
                "symbols": ["AttackController"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "Assets" / "Scripts" / "Combat" / "AttackController.summary.md",
            "# attack controller\nhandles runtime combat flow and animation triggers\n",
        )

        write_json(
            metadata_root / "Docs" / "combat_overview.meta.json",
            {
                "path": "Docs/combat_overview.md",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": [],
                "symbols": ["CombatOverview"],
                "confidence": 0.8,
            },
        )
        write_text(
            summaries_root / "Docs" / "combat_overview.summary.md",
            "# combat docs\ndocumentation only\n",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=3000,
        )

        envelope = RequestEnvelope(
            workspace_id="unity_workspace",
            project_id=scoped_project_id(project_id="PokemonUnity", workspace_id="unity_workspace"),
            user_id="u1",
            prompt="consulta abstrata sem nome de arquivo nem classe",
        )

        packet, retrieval = engine.assemble(envelope)

        assert packet.snippets
        assert retrieval.assembled["context_packet"]
        assert any(str(item.source).startswith("artifact:file:Assets/Scripts/") for item in packet.snippets)

        systems_lower = {str(item).lower() for item in retrieval.assembled.get("relevant_systems", [])}
        assert "assets" in systems_lower
