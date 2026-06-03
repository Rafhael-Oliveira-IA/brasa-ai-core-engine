from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.contracts import RequestEnvelope
from app.memory.repository import MemoryRepository
from app.retrieval import ContextRetrievalEngine
from app.workspace import scoped_project_id


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def build_workspace_artifacts(root: Path, *, workspace_id: str, project_id: str) -> None:
    project_root = root / ".brasa" / "workspaces" / workspace_id / project_id
    metadata_root = project_root / "metadata" / "files"
    summaries_root = project_root / "summaries" / "files"

    now_iso = datetime.now(timezone.utc).isoformat()

    files = {
        "Inventory/InventoryManager.cs": {
            "dependencies": ["ItemDatabase", "InventoryEvents", "EconomyService"],
            "symbols": ["InventoryManager", "AddItem", "RemoveItem"],
            "summary": (
                "# InventoryManager\n"
                "Maintains inventory operations, validates item limits, and coordinates with item database.\n"
                "It emits inventory events for item_added and item_removed flows.\n"
            ),
        },
        "Inventory/InventoryEvents.cs": {
            "dependencies": ["EventBus"],
            "symbols": ["InventoryEvents", "PublishItemAdded", "PublishItemRemoved"],
            "summary": (
                "# InventoryEvents\n"
                "Publishes item_added and item_removed notifications to EventBus.\n"
                "Used by inventory to fan out event processing.\n"
            ),
        },
        "Networking/PacketRegistry.cs": {
            "dependencies": ["PacketDeserializer", "SocketGateway"],
            "symbols": ["PacketRegistry", "RegisterInbound", "RegisterOutbound"],
            "summary": (
                "# PacketRegistry\n"
                "Registers packet handlers and packet schemas for inbound and outbound traffic.\n"
                "Connects network socket gateway with gameplay packet dispatch.\n"
            ),
        },
        "Networking/PacketRouter.cs": {
            "dependencies": ["PacketRegistry", "SessionGateway"],
            "symbols": ["PacketRouter", "RoutePacket"],
            "summary": (
                "# PacketRouter\n"
                "Routes packets from registry to gameplay and inventory processors.\n"
                "Responsible for packet router flow and session routing.\n"
            ),
        },
        "Gameplay/PlayerStateSync.cs": {
            "dependencies": ["PacketRouter", "TickScheduler", "InventoryManager"],
            "symbols": ["PlayerStateSync", "SyncSnapshot"],
            "summary": (
                "# PlayerStateSync\n"
                "Synchronizes player state snapshot updates with tick scheduler.\n"
                "Uses packet router and inventory manager to keep state coherent.\n"
            ),
        },
        "Gameplay/RaceConditionGuard.cs": {
            "dependencies": ["LockManager", "TickScheduler"],
            "symbols": ["RaceConditionGuard", "GuardCriticalSection"],
            "summary": (
                "# RaceConditionGuard\n"
                "Prevents race condition during concurrent gameplay updates.\n"
                "Applies lock policies around shared state and tick transitions.\n"
            ),
        },
        "Persistence/PlayerStateRepository.cs": {
            "dependencies": ["SqliteStore", "SnapshotSerializer"],
            "symbols": ["PlayerStateRepository", "SaveState", "LoadState"],
            "summary": (
                "# PlayerStateRepository\n"
                "Persists player state snapshots and inventory projections.\n"
                "Coordinates repository reads and writes with sqlite store.\n"
            ),
        },
        "Persistence/SnapshotSerializer.cs": {
            "dependencies": [],
            "symbols": ["SnapshotSerializer", "SerializeSnapshot"],
            "summary": (
                "# SnapshotSerializer\n"
                "Serializes snapshot payloads for player and inventory data.\n"
                "Provides stable serialization contracts for persistence.\n"
            ),
        },
        "Economy/EconomyService.cs": {
            "dependencies": ["InventoryManager", "LedgerRepository"],
            "symbols": ["EconomyService", "CalculatePrice", "ApplyTransaction"],
            "summary": (
                "# EconomyService\n"
                "Computes economy pricing and resolves inventory-dependent costs.\n"
                "Interacts with ledger repository for transaction records.\n"
            ),
        },
        "Economy/LedgerRepository.cs": {
            "dependencies": ["SqliteStore"],
            "symbols": ["LedgerRepository", "AppendTransaction"],
            "summary": (
                "# LedgerRepository\n"
                "Stores economy ledger transactions and persistent balances.\n"
                "Writes transaction logs to sqlite store for persistence.\n"
            ),
        },
    }

    dependencies_graph: dict[str, list[str]] = {}

    for file_path, payload in files.items():
        rel = Path(file_path)
        stem = rel.stem

        metadata = {
            "path": file_path,
            "hash": f"hash-{stem}",
            "language": "csharp",
            "modified_at": now_iso,
            "size": 512,
            "module": rel.parts[0],
            "folder": rel.parts[0],
            "dependencies": payload["dependencies"],
            "symbols": payload["symbols"],
            "confidence": 0.86,
        }

        write_json(metadata_root / rel.parent / f"{stem}.meta.json", metadata)
        write_text(summaries_root / rel.parent / f"{stem}.summary.md", payload["summary"])

        dependencies_graph[file_path] = list(payload["dependencies"])

    write_json(
        project_root / "graphs" / "dependencies.json",
        {
            "generated_at": now_iso,
            "dependencies": dependencies_graph,
        },
    )


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "golden" / "golden_cognitive_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_golden_cognitive_benchmark_retrieval_quality() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        workspace_id = "mmo_workspace"
        project_id = "MMO"

        build_workspace_artifacts(root, workspace_id=workspace_id, project_id=project_id)

        repository = MemoryRepository(root / "memory.db")
        engine = ContextRetrievalEngine(
            memory_repository=repository,
            project_artifacts_root=root / ".brasa",
            max_chars=5000,
        )

        scoped_project = scoped_project_id(project_id=project_id, workspace_id=workspace_id)
        cases = load_cases()

        total_precision = 0.0
        total_recall = 0.0
        total_dependency_recall = 0.0
        system_hit_count = 0
        concept_hit_count = 0

        for case in cases:
            envelope = RequestEnvelope(
                workspace_id=workspace_id,
                project_id=scoped_project,
                user_id="u1",
                prompt=str(case["query"]),
            )

            packet, retrieval = engine.assemble(envelope)
            assembled = retrieval.assembled

            context_packet = assembled.get("context_packet", [])
            retrieved_files = {
                str(item.get("source", "")).removeprefix("artifact:file:")
                for item in context_packet
                if str(item.get("source", "")).startswith("artifact:file:")
            }
            retrieved_systems = {str(item) for item in assembled.get("relevant_systems", [])}
            retrieved_dependencies = {str(item) for item in assembled.get("dependencies", [])}

            joined_context = "\n".join(snippet.content.lower() for snippet in packet.snippets)

            expected_files = {str(item) for item in case.get("expected_files", [])}
            expected_systems = {str(item) for item in case.get("expected_systems", [])}
            expected_dependencies = {str(item) for item in case.get("expected_dependencies", [])}
            expected_concepts = [str(item).lower() for item in case.get("expected_concepts", [])]

            file_hits = len(expected_files & retrieved_files)
            system_hits = len(expected_systems & retrieved_systems)
            dependency_hits = len(expected_dependencies & retrieved_dependencies)
            concept_hits = sum(1 for concept in expected_concepts if concept and concept in joined_context)

            precision = file_hits / max(1, len(retrieved_files))
            recall = file_hits / max(1, len(expected_files))
            dependency_recall = (
                dependency_hits / max(1, len(expected_dependencies))
                if expected_dependencies
                else 1.0
            )

            total_precision += precision
            total_recall += recall
            total_dependency_recall += dependency_recall

            if system_hits > 0 or file_hits > 0:
                system_hit_count += 1
            if concept_hits > 0:
                concept_hit_count += 1

            assert system_hits > 0 or file_hits > 0, f"Golden case failed for retrieval targeting: {case['id']}"

        sample_size = len(cases)
        avg_precision = total_precision / sample_size
        avg_recall = total_recall / sample_size
        avg_dependency_recall = total_dependency_recall / sample_size
        system_hit_rate = system_hit_count / sample_size
        concept_hit_rate = concept_hit_count / sample_size

        assert avg_recall >= 0.75
        assert avg_precision >= 0.25
        assert avg_dependency_recall >= 0.70
        assert system_hit_rate >= 0.85
        assert concept_hit_rate >= 0.80
