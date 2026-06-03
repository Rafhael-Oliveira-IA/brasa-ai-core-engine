from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import RequestEnvelope
from app.ingestion.pipeline import ProjectIngestionPipeline
from app.memory.repository import MemoryRepository
from app.retrieval import ContextRetrievalEngine
from app.workspace import scoped_project_id


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def test_ingestion_pipeline_writes_isolated_outputs_per_workspace() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        mmo_project = root / "source" / "mmo" / "SharedProject"
        unity_project = root / "source" / "unity" / "SharedProject"

        write_text(mmo_project / "Inventory" / "InventoryManager.cs", "public class InventoryManager {}")
        write_text(unity_project / "Gameplay" / "StateSync.cs", "public class StateSync {}")

        pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa")

        mmo_report = pipeline.run(
            project_path=mmo_project,
            workspace_id="mmo_workspace",
        )
        unity_report = pipeline.run(
            project_path=unity_project,
            workspace_id="unity_workspace",
        )

        mmo_output = root / ".brasa" / "workspaces" / "mmo_workspace" / "SharedProject"
        unity_output = root / ".brasa" / "workspaces" / "unity_workspace" / "SharedProject"

        assert mmo_report.workspace_id == "mmo_workspace"
        assert unity_report.workspace_id == "unity_workspace"
        assert mmo_output.exists()
        assert unity_output.exists()
        assert mmo_output != unity_output


def test_retrieval_uses_workspace_isolated_project_artifacts() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        now_iso = datetime.now(timezone.utc).isoformat()

        def seed_workspace(workspace_id: str, signature: str) -> None:
            project_root = root / ".brasa" / "workspaces" / workspace_id / "MMO"
            write_json(
                project_root / "metadata" / "files" / "Inventory" / "InventoryManager.meta.json",
                {
                    "path": "Inventory/InventoryManager.cs",
                    "hash": f"hash-{workspace_id}",
                    "language": "csharp",
                    "modified_at": now_iso,
                    "size": 200,
                    "module": "Inventory",
                    "folder": "Inventory",
                    "dependencies": ["ItemDatabase"],
                    "symbols": ["InventoryManager"],
                    "confidence": 0.9,
                },
            )
            write_text(
                project_root / "summaries" / "files" / "Inventory" / "InventoryManager.summary.md",
                f"# InventoryManager\n{signature}\n",
            )
            write_json(
                project_root / "graphs" / "dependencies.json",
                {
                    "generated_at": now_iso,
                    "dependencies": {
                        "Inventory/InventoryManager.cs": ["ItemDatabase"],
                    },
                },
            )

        seed_workspace("mmo_workspace", "MMO_WORKSPACE_SIGNATURE")
        seed_workspace("unity_workspace", "UNITY_WORKSPACE_SIGNATURE")

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=3000,
        )

        mmo_envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="MMO", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="inventory manager",
        )
        unity_envelope = RequestEnvelope(
            workspace_id="unity_workspace",
            project_id=scoped_project_id(project_id="MMO", workspace_id="unity_workspace"),
            user_id="u1",
            prompt="inventory manager",
        )

        mmo_packet, mmo_retrieval = engine.assemble(mmo_envelope)
        unity_packet, unity_retrieval = engine.assemble(unity_envelope)

        mmo_text = "\n".join(item.content for item in mmo_packet.snippets)
        unity_text = "\n".join(item.content for item in unity_packet.snippets)

        assert "MMO_WORKSPACE_SIGNATURE" in mmo_text
        assert "UNITY_WORKSPACE_SIGNATURE" in unity_text
        assert "UNITY_WORKSPACE_SIGNATURE" not in mmo_text
        assert "MMO_WORKSPACE_SIGNATURE" not in unity_text

        assert mmo_retrieval.assembled["workspace_id"] == "mmo_workspace"
        assert unity_retrieval.assembled["workspace_id"] == "unity_workspace"
