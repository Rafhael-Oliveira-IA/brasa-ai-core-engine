from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.compiler import HierarchicalCompiler
from app.ingestion.generator import KnowledgeGenerator
from app.ingestion.models import IngestionState, ProjectIngestionReport
from app.ingestion.scanner import ProjectScanner


class ContextInvalidationEngine:
    def detect_changes(
        self,
        *,
        current_hashes: dict[str, str],
        previous_hashes: dict[str, str],
    ) -> tuple[set[str], set[str]]:
        changed = {
            path
            for path, hash_value in current_hashes.items()
            if previous_hashes.get(path) != hash_value
        }
        removed = {path for path in previous_hashes if path not in current_hashes}
        return changed, removed


class ProjectIngestionPipeline:
    def __init__(
        self,
        *,
        output_projects_root: Path,
        max_file_bytes: int = 300_000,
    ) -> None:
        self.output_projects_root = output_projects_root
        self.scanner = ProjectScanner(max_file_bytes=max_file_bytes)
        self.generator = KnowledgeGenerator()
        self.compiler = HierarchicalCompiler()
        self.invalidator = ContextInvalidationEngine()

    def run(self, *, project_path: Path, force: bool = False) -> ProjectIngestionReport:
        project_path = project_path.resolve()
        if not project_path.exists() or not project_path.is_dir():
            raise ValueError(f"project_path not found or not a folder: {project_path}")

        profile, scanned_files = self.scanner.scan(project_path)
        output_root = self.output_projects_root / profile.project_name
        folders = self._ensure_output_tree(output_root)

        previous_state = self._load_state(folders["metadata"] / "state.json")
        previous_files = previous_state.files
        previous_hashes = {path: str(payload.get("hash", "")) for path, payload in previous_files.items()}
        current_hashes = {item.path: item.hash for item in scanned_files}

        changed_paths, removed_paths = self.invalidator.detect_changes(
            current_hashes=current_hashes,
            previous_hashes=previous_hashes,
        )
        if force:
            changed_paths = set(current_hashes.keys())

        files_to_generate = [item for item in scanned_files if item.path in changed_paths]
        metadata_by_path: dict[str, dict[str, object]] = {
            path: dict(payload)
            for path, payload in previous_files.items()
            if path not in removed_paths
        }

        generated_file_summaries = 0
        for file_item in files_to_generate:
            summary_path = self._summary_path(folders["summaries"], file_item.path)
            metadata_path = self._metadata_path(folders["metadata"], file_item.path)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)

            content = self._safe_read(project_path / file_item.path)
            summary, file_metadata = self.generator.summarize_file(file_item, content)

            summary_path.write_text(summary, encoding="utf-8")
            metadata_path.write_text(json.dumps(file_metadata, ensure_ascii=True, indent=2), encoding="utf-8")

            file_metadata["summary_path"] = summary_path.as_posix()
            file_metadata["metadata_path"] = metadata_path.as_posix()
            metadata_by_path[file_item.path] = file_metadata
            generated_file_summaries += 1

        for removed_path in removed_paths:
            self._delete_if_exists(self._summary_path(folders["summaries"], removed_path))
            self._delete_if_exists(self._metadata_path(folders["metadata"], removed_path))
            metadata_by_path.pop(removed_path, None)

        impacted_folders = self._impacted_folders(changed_paths | removed_paths)
        if force or not previous_files:
            impacted_folders = {item.folder for item in scanned_files}

        folder_summaries = self.compiler.compile_folder_summaries(
            files=scanned_files,
            metadata_by_path=metadata_by_path,
        )

        generated_folder_summaries = 0
        for folder in sorted(impacted_folders):
            content = folder_summaries.get(folder)
            if content is None:
                self._delete_if_exists(self._folder_readme_path(folders["summaries"], folder))
                continue

            folder_readme = self._folder_readme_path(folders["summaries"], folder)
            folder_readme.parent.mkdir(parents=True, exist_ok=True)
            folder_readme.write_text(content, encoding="utf-8")
            generated_folder_summaries += 1

        project_summary_content = self.compiler.compile_project_summary(
            project_name=profile.project_name,
            project_type=profile.project_type,
            engine=profile.engine,
            files=scanned_files,
            metadata_by_path=metadata_by_path,
        )
        project_summary_path = folders["summaries"] / "PROJECT_CONTEXT.md"
        project_summary_path.write_text(project_summary_content, encoding="utf-8")

        context_snapshot_path = folders["contexts"] / "ACTIVE_CONTEXT.md"
        context_snapshot_path.write_text(project_summary_content, encoding="utf-8")

        dependency_map = self.compiler.dependency_graph(
            files=scanned_files,
            metadata_by_path=metadata_by_path,
        )
        relationship_graph = self.compiler.relationship_graph(
            files=scanned_files,
            metadata_by_path=metadata_by_path,
        )
        graph_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dependencies": dependency_map,
            "nodes": relationship_graph["nodes"],
            "edges": relationship_graph["edges"],
        }
        (folders["graphs"] / "dependencies.json").write_text(
            json.dumps(graph_payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

        raw_payload = {
            "project_path": project_path.as_posix(),
            "scanned_files": [entry.model_dump(mode="json") for entry in scanned_files],
        }
        (folders["raw"] / "files_index.json").write_text(
            json.dumps(raw_payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

        memory_seed_path = folders["memories"] / "MEMORY_SEED.json"
        memory_seed_path.write_text(
            json.dumps(
                {
                    "project": profile.project_name,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "notes": [
                        "Initial ingestion seed created.",
                        "Use this memory bucket for validated long-term insights.",
                    ],
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )

        current_state = IngestionState(
            updated_at=datetime.now(timezone.utc),
            files={
                item.path: {
                    "hash": item.hash,
                    "summary_path": str(metadata_by_path.get(item.path, {}).get("summary_path", "")),
                    "metadata_path": str(metadata_by_path.get(item.path, {}).get("metadata_path", "")),
                    "dependencies": metadata_by_path.get(item.path, {}).get("dependencies", []),
                    "folder": item.folder,
                }
                for item in scanned_files
            },
        )
        (folders["metadata"] / "state.json").write_text(
            json.dumps(current_state.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

        return ProjectIngestionReport(
            project_name=profile.project_name,
            project_path=project_path.as_posix(),
            output_path=output_root.as_posix(),
            scanned_files=len(scanned_files),
            changed_files=len(changed_paths),
            removed_files=len(removed_paths),
            generated_file_summaries=generated_file_summaries,
            generated_folder_summaries=generated_folder_summaries,
            generated_project_summary=True,
            project_type=profile.project_type,
            engine=profile.engine,
            notes=[
                "Ingestion pipeline completed.",
                "Artifacts generated under .brasa/projects/<project>/.",
            ],
        )

    def _ensure_output_tree(self, output_root: Path) -> dict[str, Path]:
        folders = {
            "raw": output_root / "raw",
            "summaries": output_root / "summaries",
            "memories": output_root / "memories",
            "graphs": output_root / "graphs",
            "contexts": output_root / "contexts",
            "metadata": output_root / "metadata",
        }
        for folder in folders.values():
            folder.mkdir(parents=True, exist_ok=True)
        return folders

    def _summary_path(self, summaries_root: Path, relative_path: str) -> Path:
        rel = Path(relative_path)
        filename = f"{rel.stem}.summary.md"
        return summaries_root / "files" / rel.parent / filename

    def _metadata_path(self, metadata_root: Path, relative_path: str) -> Path:
        rel = Path(relative_path)
        filename = f"{rel.stem}.meta.json"
        return metadata_root / "files" / rel.parent / filename

    def _folder_readme_path(self, summaries_root: Path, folder: str) -> Path:
        if folder:
            return summaries_root / "folders" / folder / "README.md"
        return summaries_root / "folders" / "root" / "README.md"

    def _impacted_folders(self, changed_paths: set[str]) -> set[str]:
        folders: set[str] = set()
        for path in changed_paths:
            parent = Path(path).parent.as_posix()
            folders.add("" if parent == "." else parent)
        return folders

    def _safe_read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1", errors="ignore")

    def _load_state(self, state_path: Path) -> IngestionState:
        if not state_path.exists():
            return IngestionState()

        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            return IngestionState.model_validate(payload)
        except Exception:
            return IngestionState()

    def _delete_if_exists(self, path: Path) -> None:
        if path.exists() and path.is_file():
            path.unlink()
