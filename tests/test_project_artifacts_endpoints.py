from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module


def test_project_artifacts_tree_and_file_use_workspace_project_scope(tmp_path: Path) -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    artifacts_root = tmp_path / ".brasa"
    workspace_id = "mmo_workspace"
    project_id = "SERVIDOR - ORIGINAL"

    project_root = artifacts_root / "workspaces" / workspace_id / project_id
    metadata_dir = project_root / "metadata" / "files" / "data" / "actions"
    summary_dir = project_root / "summaries" / "files" / "data" / "actions"
    raw_dir = project_root / "raw"

    metadata_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    source_project_root = tmp_path / "mmo-source"
    source_file = source_project_root / "data" / "actions" / "actions.xml"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("<actions><action itemid=\"1234\"/></actions>", encoding="utf-8")

    summary_file = summary_dir / "actions.summary.md"
    summary_file.write_text("summary placeholder", encoding="utf-8")

    metadata_payload = {
        "path": "data/actions/actions.xml",
        "summary_path": summary_file.as_posix(),
        "metadata_path": (metadata_dir / "actions.meta.json").as_posix(),
    }
    (metadata_dir / "actions.meta.json").write_text(
        json.dumps(metadata_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    files_index_payload = {
        "project_path": source_project_root.as_posix(),
        "scanned_files": [],
    }
    (raw_dir / "files_index.json").write_text(
        json.dumps(files_index_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    main_module.app.state.runtime = SimpleNamespace(
        context_builder=SimpleNamespace(project_artifacts_root=artifacts_root),
    )

    try:
        client = TestClient(main_module.app)

        tree_response = client.get(
            "/v1/project/artifacts/tree",
            params={
                "workspace_id": workspace_id,
                "project_id": project_id,
            },
        )
        assert tree_response.status_code == 200
        tree_payload = tree_response.json()
        assert tree_payload["ingested"] is True
        assert tree_payload["file_count"] == 1
        assert tree_payload["files"] == ["data/actions/actions.xml"]
        assert tree_payload["source_project_path"] == source_project_root.as_posix()

        file_response = client.get(
            "/v1/project/artifacts/file",
            params={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "path": "data/actions/actions.xml",
            },
        )
        assert file_response.status_code == 200
        file_payload = file_response.json()
        assert file_payload["source"] == "project_source"
        assert "<actions>" in file_payload["content"]
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
