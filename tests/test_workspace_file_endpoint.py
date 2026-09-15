from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module


def test_workspace_file_endpoint_reads_text_file(tmp_path: Path) -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    file_path = workspace_root / "app" / "demo.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("hello from workspace", encoding="utf-8")

    main_module.app.state.runtime = SimpleNamespace(
        settings=SimpleNamespace(action_workspace_root=workspace_root),
    )

    try:
        client = TestClient(main_module.app)
        response = client.get(
            "/v1/workspace/file",
            params={"path": "app/demo.txt", "max_chars": 5000},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["path"] == "app/demo.txt"
        assert payload["content"] == "hello from workspace"
        assert payload["truncated"] is False
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")


def test_workspace_file_endpoint_blocks_path_traversal(tmp_path: Path) -> None:
    had_runtime = hasattr(main_module.app.state, "runtime")
    previous_runtime = getattr(main_module.app.state, "runtime", None)

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    main_module.app.state.runtime = SimpleNamespace(
        settings=SimpleNamespace(action_workspace_root=workspace_root),
    )

    try:
        client = TestClient(main_module.app)
        response = client.get(
            "/v1/workspace/file",
            params={"path": "../secret.txt"},
        )

        assert response.status_code == 400
    finally:
        if had_runtime:
            main_module.app.state.runtime = previous_runtime
        elif hasattr(main_module.app.state, "runtime"):
            delattr(main_module.app.state, "runtime")
