from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from app.contracts import RequestEnvelope
from app.knowledge.models import KnowledgeLevel
from app.memory.repository import MemoryRepository
from app.retrieval import ContextRetrievalEngine
from app.workspace import scoped_project_id


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def test_artifact_candidates_filter_build_and_toolchain_noise() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "src" / "boost_guard.meta.json",
            {
                "path": "src/boost_guard.h",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["SpellRegistry"],
                "symbols": ["BoostGuard"],
                "confidence": 0.88,
            },
        )
        write_text(
            summaries_root / "src" / "boost_guard.summary.md",
            "# boost guard\nvalid source file for spells and boost checks\n",
        )

        write_json(
            metadata_root / "vcpkg_installed" / "x64-windows" / "include" / "boost" / "algorithm.meta.json",
            {
                "path": "vcpkg_installed/x64-windows/include/boost/algorithm.hpp",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["fmt"],
                "symbols": ["BoostAlgorithm"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "vcpkg_installed" / "x64-windows" / "include" / "boost" / "algorithm.summary.md",
            "# boost algorithm\nnoise from toolchain\n",
        )

        write_json(
            metadata_root / "build" / "cmake_cache.meta.json",
            {
                "path": "build/CMakeCache.txt",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": [],
                "symbols": ["CMakeCache"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "build" / "cmake_cache.summary.md",
            "# cmake cache\nnoise from build output\n",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=3000,
        )

        candidates, _, _ = engine._artifact_candidates(
            project_id="SERVIDOR - ORIGINAL",
            workspace_id="mmo_workspace",
            intent_terms={"boost"},
        )

        sources = [item.source for item in candidates]
        assert "artifact:file:src/boost_guard.h" in sources
        assert not any("vcpkg_installed" in source for source in sources)
        assert not any("artifact:file:build/" in source for source in sources)


class StubKnowledgeCompiler:
    def search(self, query: str, limit: int = 8) -> list:
        return [
            SimpleNamespace(
                node_id="file:app/main.py",
                level=KnowledgeLevel.FILE,
                title="Main",
                source_path="app/main.py",
                summary="Handles app routing and endpoints.",
                dependencies=["fastapi"],
                patterns=["runtime"],
                confidence=0.9,
            ),
            SimpleNamespace(
                node_id="file:.brasa/workspaces/mmo_workspace/SERVIDOR - ORIGINAL/src/network.h",
                level=KnowledgeLevel.FILE,
                title="Network",
                source_path=".brasa/workspaces/mmo_workspace/SERVIDOR - ORIGINAL/src/network.h",
                summary="Registers packet and network handlers.",
                dependencies=["PacketRegistry"],
                patterns=["networking"],
                confidence=0.86,
            ),
        ]


def test_knowledge_candidates_are_scoped_to_workspace_project() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        repository = MemoryRepository(root / "memory.db")

        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            knowledge_compiler=StubKnowledgeCompiler(),
            max_chars=3000,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="como packets sao registrados?",
        )

        packet, retrieval = engine.assemble(envelope)
        assert packet.snippets

        sources = [item.source for item in packet.snippets]
        assert any(source.startswith("knowledge:file:file:.brasa/workspaces/mmo_workspace/SERVIDOR - ORIGINAL/") for source in sources)
        assert not any(source.startswith("knowledge:file:file:app/") for source in sources)

        relevant_systems = retrieval.assembled.get("relevant_systems", [])
        assert "app" not in [str(item).lower() for item in relevant_systems]


def test_mmo_architecture_priors_favor_src_and_revscriptsys_over_tools() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "src" / "scriptmanager.meta.json",
            {
                "path": "src/scriptmanager.cpp",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["BaseEvents::loadFromXml", "Scripts::loadScripts"],
                "symbols": ["ScriptingManager::loadScriptSystems"],
                "confidence": 0.92,
            },
        )
        write_text(
            summaries_root / "src" / "scriptmanager.summary.md",
            "# scriptmanager\nloads xml script systems and bootstrap libs\n",
        )

        write_json(
            metadata_root / "data" / "scripts" / "talkactions" / "reload.meta.json",
            {
                "path": "data/scripts/talkactions/reload.lua",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["TalkAction", "register"],
                "symbols": ["reload"],
                "confidence": 0.86,
            },
        )
        write_text(
            summaries_root / "data" / "scripts" / "talkactions" / "reload.summary.md",
            "# reload\nrevscriptsys talkaction registration\n",
        )

        write_json(
            metadata_root / "data" / "tools" / "spell_fixer.meta.json",
            {
                "path": "data/tools/spell_fixer.py",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["symbol:std", "os", "re"],
                "symbols": ["SpellFixer"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "tools" / "spell_fixer.summary.md",
            "# spell fixer\nmaintenance tool script\n",
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
            prompt="como o revscriptsys integra sem XML no startup?",
        )

        packet, retrieval = engine.assemble(envelope)
        assert packet.snippets

        top_source = packet.snippets[0].source
        assert top_source in {
            "artifact:file:src/scriptmanager.cpp",
            "artifact:file:data/scripts/talkactions/reload.lua",
        }

        dependencies = retrieval.assembled.get("dependencies", [])
        assert not any(str(item).startswith("symbol:") for item in dependencies)
        assert "os" not in [str(item).lower() for item in dependencies]


def test_action_xml_and_revscripts_models_are_prioritized_for_action_architecture_query() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "data" / "actions" / "actions.meta.json",
            {
                "path": "data/actions/actions.xml",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["itemid", "actionid", "uniqueid"],
                "symbols": ["action"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "actions" / "actions.summary.md",
            "# actions xml\nxml binds itemid actionid uniqueid to scripts\n",
        )

        write_json(
            metadata_root / "data" / "actions" / "scripts" / "tools" / "machete.meta.json",
            {
                "path": "data/actions/scripts/tools/machete.lua",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["onUse"],
                "symbols": ["onUse"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "actions" / "scripts" / "tools" / "machete.summary.md",
            "# machete action\nclassic xml action script with onUse callback\n",
        )

        write_json(
            metadata_root / "data" / "scripts" / "systems" / "pokemon" / "tm_teach.meta.json",
            {
                "path": "data/scripts/systems/pokemon/tm_teach.lua",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["Action()", ":id", ":register"],
                "symbols": ["Action", "register"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "scripts" / "systems" / "pokemon" / "tm_teach.summary.md",
            "# tm teach\nrevscripts Action() with id bind and register\n",
        )

        write_json(
            metadata_root / "src" / "actions.meta.json",
            {
                "path": "src/actions.cpp",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["registerEvent", "registerLuaEvent"],
                "symbols": ["Actions"],
                "confidence": 0.92,
            },
        )
        write_text(
            summaries_root / "src" / "actions.summary.md",
            "# actions cpp\ncore registration for xml and lua actions\n",
        )

        write_json(
            metadata_root / "src" / "luascript.meta.json",
            {
                "path": "src/luascript.cpp",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["luaCreateAction", "luaActionRegister"],
                "symbols": ["luaCreateAction", "luaActionRegister"],
                "confidence": 0.92,
            },
        )
        write_text(
            summaries_root / "src" / "luascript.summary.md",
            "# luascript cpp\nbridges Action() and register in lua runtime\n",
        )

        write_json(
            metadata_root / "data" / "tools" / "spell_fixer.meta.json",
            {
                "path": "data/tools/spell_fixer.py",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["argparse", "os"],
                "symbols": ["SpellFixer"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "tools" / "spell_fixer.summary.md",
            "# spell fixer\nmaintenance utility\n",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=5000,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="qual a diferenca entre action xml e action revscripts com Action() e register?",
        )

        packet, retrieval = engine.assemble(envelope)
        assert packet.snippets

        top_sources = [item.source for item in packet.snippets[:8]]
        assert "artifact:file:data/actions/actions.xml" in top_sources
        assert "artifact:file:data/scripts/systems/pokemon/tm_teach.lua" in top_sources
        assert any(source in top_sources for source in ["artifact:file:src/actions.cpp", "artifact:file:src/luascript.cpp"])
        assert not any(source.startswith("artifact:file:data/tools/") for source in top_sources[:3])

        systems = retrieval.assembled.get("relevant_systems", [])
        systems_lower = [str(item).lower() for item in systems]
        assert "data/actions" in systems_lower
        assert "data/scripts" in systems_lower


def test_classic_xml_and_runtime_models_are_prioritized_for_talkactions_query() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "data" / "talkactions" / "talkactions.meta.json",
            {
                "path": "data/talkactions/talkactions.xml",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["words", "script", "xml-script-binding"],
                "symbols": ["talkaction"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "talkactions" / "talkactions.summary.md",
            "# talkactions xml\nclassic xml binds words/scripts for chat callbacks\n",
        )

        write_json(
            metadata_root / "data" / "talkactions" / "scripts" / "admin" / "rank.meta.json",
            {
                "path": "data/talkactions/scripts/admin/rank.lua",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["onSay", "classic-script-callback"],
                "symbols": ["onSay"],
                "confidence": 0.88,
            },
        )
        write_text(
            summaries_root / "data" / "talkactions" / "scripts" / "admin" / "rank.summary.md",
            "# rank script\nclassic xml callback script with onSay\n",
        )

        write_json(
            metadata_root / "data" / "scripts" / "talkactions" / "rank.meta.json",
            {
                "path": "data/scripts/talkactions/rank.lua",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["TalkAction()", ":register", "onSay", "runtime-script-register"],
                "symbols": ["rankTalkAction", "onSay"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "scripts" / "talkactions" / "rank.summary.md",
            "# rank revscript\nruntime TalkAction registration without talkactions.xml\n",
        )

        write_json(
            metadata_root / "data" / "tools" / "chat_cleaner.meta.json",
            {
                "path": "data/tools/chat_cleaner.py",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["argparse", "os"],
                "symbols": ["ChatCleaner"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "tools" / "chat_cleaner.summary.md",
            "# chat cleaner\nmaintenance helper script\n",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=5000,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="qual a diferenca entre talkactions xml classico e revscripts com register?",
        )

        packet, retrieval = engine.assemble(envelope)
        assert packet.snippets

        top_sources = [item.source for item in packet.snippets[:8]]
        assert "artifact:file:data/talkactions/talkactions.xml" in top_sources
        assert "artifact:file:data/scripts/talkactions/rank.lua" in top_sources
        assert not any(source.startswith("artifact:file:data/tools/") for source in top_sources[:3])

        systems = retrieval.assembled.get("relevant_systems", [])
        systems_lower = [str(item).lower() for item in systems]
        assert "data/talkactions" in systems_lower
        assert "data/scripts" in systems_lower


def test_dotted_xml_filename_terms_match_classic_xml_candidates() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "data" / "actions" / "actions.meta.json",
            {
                "path": "data/actions/actions.xml",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["itemid", "actionid", "uniqueid", "script"],
                "symbols": ["action"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "actions" / "actions.summary.md",
            "# actions xml\nclassic xml binds itemid/actionid/uniqueid to scripts\n",
        )

        write_json(
            metadata_root / "data" / "scripts" / "actions" / "lever.meta.json",
            {
                "path": "data/scripts/actions/lever.lua",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["Action()", ":register"],
                "symbols": ["leverAction"],
                "confidence": 0.88,
            },
        )
        write_text(
            summaries_root / "data" / "scripts" / "actions" / "lever.summary.md",
            "# lever revscript\nruntime Action registration\n",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=4000,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="explica actions.xml versus data/scripts actions com register",
        )

        packet, _ = engine.assemble(envelope)
        top_sources = [item.source for item in packet.snippets[:8]]
        assert "artifact:file:data/actions/actions.xml" in top_sources


@pytest.mark.parametrize(
    ("xml_path", "runtime_path", "prompt"),
    [
        (
            "data/actions/actions.xml",
            "data/scripts/actions/lever.lua",
            "explique actions.xml versus data/scripts actions com register",
        ),
        (
            "data/movements/movements.xml",
            "data/scripts/movements/teleport_tiles.lua",
            "movements.xml fromid toid script versus MoveEvent() register em data/scripts",
        ),
        (
            "data/talkactions/talkactions.xml",
            "data/scripts/talkactions/rank.lua",
            "talkactions.xml classico versus data/scripts runtime com register",
        ),
    ],
)
def test_xml_focused_queries_always_select_matching_xml_file(
    xml_path: str,
    runtime_path: str,
    prompt: str,
) -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        xml_meta = metadata_root / Path(xml_path).parent / f"{Path(xml_path).stem}.meta.json"
        xml_summary = summaries_root / Path(xml_path).parent / f"{Path(xml_path).stem}.summary.md"
        write_json(
            xml_meta,
            {
                "path": xml_path,
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["script", "itemid", "actionid", "fromid", "toid"],
                "symbols": [Path(xml_path).stem],
                "confidence": 0.9,
            },
        )
        write_text(
            xml_summary,
            f"# {Path(xml_path).stem}\nclassic xml binding file for {xml_path}\n",
        )

        runtime_meta = metadata_root / Path(runtime_path).parent / f"{Path(runtime_path).stem}.meta.json"
        runtime_summary = summaries_root / Path(runtime_path).parent / f"{Path(runtime_path).stem}.summary.md"
        write_json(
            runtime_meta,
            {
                "path": runtime_path,
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": [":register", "onUse", "runtime-script-register"],
                "symbols": ["runtimeHandler"],
                "confidence": 0.95,
            },
        )
        write_text(
            runtime_summary,
            "# runtime script\nruntime registration handler with register\n" * 60,
        )

        # Distractor XML with strong signal: matching XML filename in prompt must still win.
        write_json(
            metadata_root / "data" / "items" / "items.meta.json",
            {
                "path": "data/items/items.xml",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["id", "type", "script"],
                "symbols": ["items"],
                "confidence": 0.99,
            },
        )
        write_text(
            summaries_root / "data" / "items" / "items.summary.md",
            "# items xml\nlarge generic xml file\n" * 80,
        )

        # Add additional high-signal runtime files to create compression pressure.
        for index in range(1, 10):
            noisy_path = f"data/scripts/noisy/noisy_{index}.lua"
            noisy_meta = metadata_root / Path(noisy_path).parent / f"noisy_{index}.meta.json"
            noisy_summary = summaries_root / Path(noisy_path).parent / f"noisy_{index}.summary.md"
            write_json(
                noisy_meta,
                {
                    "path": noisy_path,
                    "modified_at": "2026-06-03T12:00:00+00:00",
                    "dependencies": [":register", "onUse", "runtime-script-register"],
                    "symbols": [f"Noisy{index}"],
                    "confidence": 0.96,
                },
            )
            write_text(
                noisy_summary,
                "# noisy runtime\nruntime register flow\n" * 40,
            )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=900,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt=prompt,
        )

        packet, _ = engine.assemble(envelope)
        sources = [item.source for item in packet.snippets]
        assert f"artifact:file:{xml_path}" in sources


def test_item_loot_focused_queries_keep_items_xml_under_compression_pressure() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "data" / "items" / "items.meta.json",
            {
                "path": "data/items/items.xml",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["id", "type", "script"],
                "symbols": ["items"],
                "confidence": 0.95,
            },
        )
        write_text(
            summaries_root / "data" / "items" / "items.summary.md",
            "# items xml\nitem definitions for stones and loot-linked item ids\n",
        )

        write_json(
            metadata_root / "data" / "monster" / "kanto" / "arcaninie.meta.json",
            {
                "path": "data/monster/kanto/arcaninie.xml",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["loot", "heart stone", "fire stone"],
                "symbols": ["arcaninie"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "monster" / "kanto" / "arcaninie.summary.md",
            "# arcaninie\nloot table references stones and drop conditions\n",
        )

        # Add many high-signal runtime candidates to create budget pressure.
        for index in range(1, 14):
            noisy_path = f"data/scripts/noisy/drop_logic_{index}.lua"
            write_json(
                metadata_root / "data" / "scripts" / "noisy" / f"drop_logic_{index}.meta.json",
                {
                    "path": noisy_path,
                    "modified_at": "2026-06-03T12:00:00+00:00",
                    "dependencies": ["loot", "drop", "stone"],
                    "symbols": [f"DropLogic{index}"],
                    "confidence": 0.96,
                },
            )
            write_text(
                summaries_root / "data" / "scripts" / "noisy" / f"drop_logic_{index}.summary.md",
                "# drop runtime\n"
                "runtime drop and loot flow for stone rewards in monster battles\n" * 35,
            )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=950,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="o arcaninie deveria dropar fire stone no lugar de heart stone?",
        )

        packet, _ = engine.assemble(envelope)
        sources = [item.source for item in packet.snippets]

        assert "artifact:file:data/items/items.xml" in sources
        assert any(source.startswith("artifact:file:data/monster/") for source in sources)
