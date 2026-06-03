from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.ingestion.pipeline import ProjectIngestionPipeline


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ingestion_pipeline_generates_expected_artifacts() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_path = root / "MMO"

        write_text(
            project_path / "Inventory" / "InventoryManager.cs",
            """
using System;

public class InventoryManager {
    public void AddItem() {}
}
""".strip(),
        )
        write_text(
            project_path / "Inventory" / "ItemDatabase.cs",
            """
using System;

public class ItemDatabase {
    public void Save() {}
}
""".strip(),
        )

        pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa" / "projects")
        report = pipeline.run(project_path=project_path)

        assert report.project_name == "MMO"
        assert report.scanned_files == 2
        assert report.generated_file_summaries == 2
        assert report.generated_project_summary is True

        output_root = root / ".brasa" / "projects" / "MMO"
        assert (output_root / "raw").exists()
        assert (output_root / "summaries").exists()
        assert (output_root / "memories").exists()
        assert (output_root / "graphs").exists()
        assert (output_root / "contexts").exists()
        assert (output_root / "metadata").exists()

        file_summary = output_root / "summaries" / "files" / "Inventory" / "InventoryManager.summary.md"
        folder_summary = output_root / "summaries" / "folders" / "Inventory" / "README.md"
        project_summary = output_root / "summaries" / "PROJECT_CONTEXT.md"
        metadata_file = output_root / "metadata" / "files" / "Inventory" / "InventoryManager.meta.json"

        assert file_summary.exists()
        assert folder_summary.exists()
        assert project_summary.exists()
        assert metadata_file.exists()

        metadata_payload = json.loads(metadata_file.read_text(encoding="utf-8"))
        assert metadata_payload["path"] == "Inventory/InventoryManager.cs"
        assert metadata_payload["language"] == "csharp"

        graph_payload = json.loads((output_root / "graphs" / "dependencies.json").read_text(encoding="utf-8"))
        assert "nodes" in graph_payload
        assert "edges" in graph_payload
        assert any(edge["relation"] == "related_to" for edge in graph_payload["edges"])
        assert any(edge["relation"] in {"uses", "emits"} for edge in graph_payload["edges"])


def test_ingestion_pipeline_incremental_change_detection() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_path = root / "MMO"

        target_file = project_path / "Inventory" / "InventoryManager.cs"
        write_text(
            target_file,
            """
public class InventoryManager {
    public void AddItem() {}
}
""".strip(),
        )
        write_text(
            project_path / "Inventory" / "ItemDatabase.cs",
            """
public class ItemDatabase {
    public void Save() {}
}
""".strip(),
        )

        pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa" / "projects")
        first = pipeline.run(project_path=project_path)
        stable = pipeline.run(project_path=project_path)

        assert first.changed_files == 2
        assert stable.changed_files == 0

        write_text(
            target_file,
            """
public class InventoryManager {
    public void AddItem() {}
    public void RemoveItem() {}
}
""".strip(),
        )

        incremental = pipeline.run(project_path=project_path)
        assert incremental.changed_files == 1
        assert incremental.generated_file_summaries == 1


def test_ingestion_pipeline_includes_lua_and_xml_action_models() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_path = root / "MMO"

        write_text(
            project_path / "data" / "actions" / "actions.xml",
            "<actions><action itemid=\"2420\" script=\"tools/machete.lua\" /></actions>",
        )
        write_text(
            project_path / "data" / "actions" / "scripts" / "tools" / "machete.lua",
            "function onUse(player, item, fromPosition, target, toPosition, isHotkey) return true end",
        )
        write_text(
            project_path / "data" / "scripts" / "systems" / "pokemon" / "tm_teach.lua",
            "local action = Action()\nfunction action.onUse(player, item, fromPosition, target, toPosition) return true end\naction:id(35286)\naction:register()",
        )

        pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa")
        report = pipeline.run(project_path=project_path, workspace_id="mmo_workspace")

        assert report.scanned_files == 3
        assert report.generated_file_summaries == 3

        output_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "MMO"
        assert (output_root / "metadata" / "files" / "data" / "actions" / "actions.meta.json").exists()
        assert (output_root / "metadata" / "files" / "data" / "actions" / "scripts" / "tools" / "machete.meta.json").exists()
        assert (output_root / "metadata" / "files" / "data" / "scripts" / "systems" / "pokemon" / "tm_teach.meta.json").exists()


def test_ingestion_pipeline_accepts_large_xml_configs_up_to_extended_limit() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_path = root / "MMO"

        large_xml = "<actions>" + ("<action itemid=\"100\" script=\"x.lua\" />" * 12000) + "</actions>"
        assert len(large_xml.encode("utf-8")) > 300000

        write_text(
            project_path / "data" / "actions" / "actions.xml",
            large_xml,
        )

        pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa", max_file_bytes=300000)
        report = pipeline.run(project_path=project_path, workspace_id="mmo_workspace")

        assert report.scanned_files == 1
        output_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "MMO"
        assert (output_root / "metadata" / "files" / "data" / "actions" / "actions.meta.json").exists()
