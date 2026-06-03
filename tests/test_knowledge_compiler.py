from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.knowledge.compiler import KnowledgeCompiler


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_state(state_path: Path) -> dict:
    return json.loads(state_path.read_text(encoding="utf-8"))


def test_knowledge_compiler_generates_hierarchy_and_artifacts() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        write_text(
            root / "Inventory" / "InventoryManager.cs",
            """
using System;

public class InventoryManager {
    public void AddItem() {}
}
""".strip(),
        )
        write_text(
            root / "Inventory" / "UI" / "InventoryUI.cs",
            """
public class InventoryUI {
    public void Render() {}
}
""".strip(),
        )
        write_text(
            root / "Networking" / "TcpServer.cs",
            """
using System.Net;

public class TcpServer {
    public void Start() {}
}
""".strip(),
        )

        output_dir = root / "data" / "knowledge"
        state_file = output_dir / "state.json"

        compiler = KnowledgeCompiler(
            project_root=root,
            output_dir=output_dir,
            state_file=state_file,
        )

        report = compiler.sync()

        assert report.scanned_files == 3
        assert report.regenerated_nodes > 0

        tree = compiler.tree()
        levels = {node.level.value for node in tree.nodes}
        assert {"file", "folder", "module", "project", "global"}.issubset(levels)

        assert (output_dir / "project" / "PROJECT_KNOWLEDGE.md").exists()
        assert (output_dir / "global" / "GLOBAL_MEMORY.md").exists()

        state = load_state(state_file)
        inventory_node = state["nodes"]["module:Inventory"]
        assert inventory_node["source_hash"]
        assert inventory_node["file_versions"]
        assert inventory_node["confidence"] > 0.0


def test_knowledge_compiler_incremental_propagation() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        target_file = root / "Inventory" / "InventoryManager.cs"
        write_text(
            target_file,
            """
public class InventoryManager {
    public void AddItem() {}
}
""".strip(),
        )
        write_text(
            root / "Inventory" / "Item.cs",
            """
public class Item {
    public string Id;
}
""".strip(),
        )

        output_dir = root / "data" / "knowledge"
        state_file = output_dir / "state.json"

        compiler = KnowledgeCompiler(
            project_root=root,
            output_dir=output_dir,
            state_file=state_file,
        )

        first_report = compiler.sync()
        stable_report = compiler.sync()

        assert first_report.changed_nodes > 0
        assert stable_report.changed_nodes == 0
        assert stable_report.regenerated_nodes == 0

        before = load_state(state_file)["nodes"]

        write_text(
            target_file,
            """
public class InventoryManager {
    public void AddItem() {}
    public void RemoveItem() {}
}
""".strip(),
        )

        incremental_report = compiler.sync()
        after = load_state(state_file)["nodes"]

        assert incremental_report.changed_nodes > 0
        assert incremental_report.changed_nodes < first_report.changed_nodes

        project_node_id = next(
            node_id
            for node_id, payload in before.items()
            if payload.get("level") == "project"
        )

        tracked_nodes = [
            "file:Inventory/InventoryManager.cs",
            "folder:Inventory",
            "module:Inventory",
            project_node_id,
            "global:default",
        ]

        for node_id in tracked_nodes:
            assert after[node_id]["generation"] > before[node_id]["generation"]


def test_knowledge_compiler_includes_data_lua_and_xml_by_default() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        write_text(
            root / "data" / "talkactions" / "talkactions.xml",
            "<talkactions><talkaction words=\"/rank\" script=\"admin/rank.lua\" /></talkactions>",
        )
        write_text(
            root / "data" / "scripts" / "talkactions" / "rank.lua",
            "local rank = TalkAction(\"/rank\")\nrank:register()",
        )

        output_dir = root / "artifacts" / "knowledge"
        state_file = output_dir / "state.json"

        compiler = KnowledgeCompiler(
            project_root=root,
            output_dir=output_dir,
            state_file=state_file,
        )

        report = compiler.sync()
        assert report.scanned_files == 2

        state = load_state(state_file)
        nodes = state["nodes"]

        assert "file:data/talkactions/talkactions.xml" in nodes
        assert "file:data/scripts/talkactions/rank.lua" in nodes
