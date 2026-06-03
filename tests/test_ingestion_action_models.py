from __future__ import annotations

import json
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


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_ingestion_pipeline_extracts_action_model_markers_from_xml_and_lua() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_path = root / "MMO"

        write_text(
            project_path / "data" / "actions" / "actions.xml",
            """
<actions>
    <action itemid="2420" actionid="7546" uniqueid="9001" script="tools/machete.lua" />
    <action fromaid="5000" toaid="5003" fromuid="8000" touid="8010" script="quests/portal.lua" />
</actions>
""".strip(),
        )
        write_text(
            project_path / "data" / "actions" / "scripts" / "tools" / "machete.lua",
            """
function onUse(player, item, fromPosition, target, toPosition, isHotkey)
    return true
end
""".strip(),
        )
        write_text(
            project_path / "data" / "scripts" / "systems" / "pokemon" / "tm_teach.lua",
            """
local tmTeachAction = Action()

function tmTeachAction.onUse(player, item, fromPosition, target, toPosition)
    return true
end

tmTeachAction:id(35286)
tmTeachAction:allowFarUse(true)
tmTeachAction:register()
""".strip(),
        )

        pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa")
        report = pipeline.run(project_path=project_path, workspace_id="mmo_workspace")
        assert report.scanned_files == 3

        output_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "MMO"

        actions_meta = read_json(output_root / "metadata" / "files" / "data" / "actions" / "actions.meta.json")
        machete_meta = read_json(
            output_root / "metadata" / "files" / "data" / "actions" / "scripts" / "tools" / "machete.meta.json"
        )
        tm_meta = read_json(
            output_root / "metadata" / "files" / "data" / "scripts" / "systems" / "pokemon" / "tm_teach.meta.json"
        )

        actions_deps = set(actions_meta["dependencies"])
        assert {"itemid", "actionid", "uniqueid", "fromaid", "toaid", "fromuid", "touid", "script"} <= actions_deps
        assert "script:tools/machete.lua" in actions_deps
        assert "classic-action-bind" in actions_deps

        tm_deps = set(tm_meta["dependencies"])
        assert {"Action()", ":id", ":allowFarUse", ":register", "onUse", "revscripts-action"} <= tm_deps

        machete_deps = set(machete_meta["dependencies"])
        assert "onUse" in machete_deps
        assert "classic-action-script" in machete_deps

        actions_summary = (
            output_root / "summaries" / "files" / "data" / "actions" / "actions.summary.md"
        ).read_text(encoding="utf-8")
        tm_summary = (
            output_root / "summaries" / "files" / "data" / "scripts" / "systems" / "pokemon" / "tm_teach.summary.md"
        ).read_text(encoding="utf-8")

        assert "classic Action XML binds" in actions_summary
        assert "Revscripts Action" in tm_summary


def test_retrieval_prioritizes_xml_and_revscripts_action_models_from_generated_artifacts() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_path = root / "MMO"

        write_text(
            project_path / "data" / "actions" / "actions.xml",
            """
<actions>
    <action itemid="2420" actionid="7546" uniqueid="9001" script="tools/machete.lua" />
</actions>
""".strip(),
        )
        write_text(
            project_path / "data" / "scripts" / "systems" / "pokemon" / "tm_teach.lua",
            """
local tmTeachAction = Action()
function tmTeachAction.onUse(player, item, fromPosition, target, toPosition)
    return true
end
tmTeachAction:id(35286)
tmTeachAction:register()
""".strip(),
        )
        write_text(
            project_path / "src" / "scriptmanager.cpp",
            """
void ScriptingManager::loadScriptSystems() {
    g_actions->loadFromXml();
}
""".strip(),
        )

        pipeline = ProjectIngestionPipeline(output_projects_root=root / ".brasa")
        pipeline.run(project_path=project_path, workspace_id="mmo_workspace")

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=4000,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="MMO", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt=(
                "qual a diferenca entre action xml classico e action revscripts com register "
                "e ordem uniqueid actionid itemid no startup"
            ),
        )

        packet, retrieval = engine.assemble(envelope)
        assert packet.snippets

        top_sources = [item.source for item in packet.snippets[:8]]
        assert "artifact:file:data/actions/actions.xml" in top_sources
        assert "artifact:file:data/scripts/systems/pokemon/tm_teach.lua" in top_sources

        systems_lower = {str(item).lower() for item in retrieval.assembled.get("relevant_systems", [])}
        assert "data/actions" in systems_lower
        assert "data/scripts" in systems_lower

        dependencies_lower = {str(item).lower() for item in retrieval.assembled.get("dependencies", [])}
        assert "uniqueid" in dependencies_lower
        assert ":register" in dependencies_lower
