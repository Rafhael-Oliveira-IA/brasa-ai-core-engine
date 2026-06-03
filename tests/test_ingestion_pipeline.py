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
