from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import ContextPacket, ProviderResponse, RequestEnvelope
from app.memory.repository import MemoryRepository
from app.providers.base import BaseProvider, ProviderUnavailable
from app.retrieval import ContextRetrievalEngine
from app.workspace import scoped_project_id


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


class StubRetrievalAssistProvider(BaseProvider):
    name = "alibaba"

    async def generate(self, *, prompt: str, context: ContextPacket, model_name: str) -> ProviderResponse:
        payload = {
            "priority_sources": ["data/config/liveops/seasons.json"],
            "include_terms": ["season", "reset", "battle pass"],
            "intent": "classification",
        }
        return ProviderResponse(
            answer=json.dumps(payload, ensure_ascii=True),
            confidence=0.9,
            provider=self.name,
            model_name=model_name,
            prompt_tokens=120,
            completion_tokens=40,
            total_tokens=160,
            cost_usd=0.001,
        )


class FailingRetrievalAssistProvider(BaseProvider):
    name = "alibaba"

    async def generate(self, *, prompt: str, context: ContextPacket, model_name: str) -> ProviderResponse:
        raise ProviderUnavailable("cloud assist unavailable")


def test_cloud_retrieval_assist_boosts_priority_source_selection() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "data" / "config" / "liveops" / "seasons.meta.json",
            {
                "path": "data/config/liveops/seasons.json",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["season", "policy"],
                "symbols": ["seasonPolicy"],
                "confidence": 0.8,
            },
        )
        write_text(
            summaries_root / "data" / "config" / "liveops" / "seasons.summary.md",
            "# seasons config\nseason reset policy and battle pass schedule\n",
        )

        for index in range(1, 12):
            noisy_path = f"data/scripts/noisy/season_runtime_{index}.lua"
            write_json(
                metadata_root / "data" / "scripts" / "noisy" / f"season_runtime_{index}.meta.json",
                {
                    "path": noisy_path,
                    "modified_at": "2026-06-03T12:00:00+00:00",
                    "dependencies": ["season", "reset", "battle pass"],
                    "symbols": [f"SeasonRuntime{index}"],
                    "confidence": 0.95,
                },
            )
            write_text(
                summaries_root / "data" / "scripts" / "noisy" / f"season_runtime_{index}.summary.md",
                "# runtime season reset\n"
                "battle pass season reset runtime handling and scheduler pipeline\n" * 40,
            )

        repository = MemoryRepository(root / "memory.db")
        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="onde fica a policy de reset de season do battle pass?",
        )

        base_engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=420,
        )
        base_packet, _ = base_engine.assemble(envelope)
        base_sources = [item.source for item in base_packet.snippets]

        assist_engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=420,
            retrieval_assist_provider=StubRetrievalAssistProvider(),
            retrieval_assist_enabled=True,
            retrieval_assist_model_name="qwen-turbo-latest",
            retrieval_assist_min_candidates=1,
        )
        assist_packet, assist_retrieval = assist_engine.assemble(envelope)
        assist_sources = [item.source for item in assist_packet.snippets]

        assert "artifact:file:data/config/liveops/seasons.json" not in base_sources
        assert "artifact:file:data/config/liveops/seasons.json" in assist_sources

        cloud_assist = assist_retrieval.assembled.get("cloud_retrieval_assist", {})
        assert cloud_assist.get("status") == "ok"
        assert int(cloud_assist.get("applied_priority_boosts", 0)) >= 1


def test_cloud_retrieval_assist_failure_degrades_gracefully() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project_root = root / ".brasa" / "workspaces" / "mmo_workspace" / "SERVIDOR - ORIGINAL"
        metadata_root = project_root / "metadata" / "files"
        summaries_root = project_root / "summaries" / "files"

        write_json(
            metadata_root / "data" / "scripts" / "systems" / "economy" / "prices.meta.json",
            {
                "path": "data/scripts/systems/economy/prices.lua",
                "modified_at": "2026-06-03T12:00:00+00:00",
                "dependencies": ["economy", "price"],
                "symbols": ["Prices"],
                "confidence": 0.9,
            },
        )
        write_text(
            summaries_root / "data" / "scripts" / "systems" / "economy" / "prices.summary.md",
            "# economy prices\nhandles pricing behavior\n",
        )

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=1200,
            retrieval_assist_provider=FailingRetrievalAssistProvider(),
            retrieval_assist_enabled=True,
            retrieval_assist_model_name="qwen-turbo-latest",
            retrieval_assist_min_candidates=1,
        )

        envelope = RequestEnvelope(
            workspace_id="mmo_workspace",
            project_id=scoped_project_id(project_id="SERVIDOR - ORIGINAL", workspace_id="mmo_workspace"),
            user_id="u1",
            prompt="como funciona o pricing?",
        )

        packet, retrieval = engine.assemble(envelope)
        assert packet.snippets

        cloud_assist = retrieval.assembled.get("cloud_retrieval_assist", {})
        assert cloud_assist.get("status") in {"unavailable", "failed"}
