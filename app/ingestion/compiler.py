from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.ingestion.models import ScannedFile


class HierarchicalCompiler:
    def compile_folder_summaries(
        self,
        *,
        files: list[ScannedFile],
        metadata_by_path: dict[str, dict[str, object]],
    ) -> dict[str, str]:
        grouped: dict[str, list[ScannedFile]] = defaultdict(list)
        for file_item in files:
            grouped[file_item.folder].append(file_item)

        summaries: dict[str, str] = {}
        for folder, folder_files in grouped.items():
            title = folder or "root"
            lines = [
                f"# {title}",
                "",
                "## Files",
            ]

            for item in sorted(folder_files, key=lambda entry: entry.path):
                lines.append(f"- {item.path}")

            dependencies: set[str] = set()
            for item in folder_files:
                metadata = metadata_by_path.get(item.path, {})
                for dep in metadata.get("dependencies", []):
                    dependencies.add(str(dep))

            lines.append("")
            lines.append("## Dependencies")
            if dependencies:
                for dependency in sorted(dependencies)[:20]:
                    lines.append(f"- {dependency}")
            else:
                lines.append("- none")

            summaries[folder] = "\n".join(lines).strip() + "\n"

        return summaries

    def compile_project_summary(
        self,
        *,
        project_name: str,
        project_type: str,
        engine: str,
        files: list[ScannedFile],
        metadata_by_path: dict[str, dict[str, object]],
    ) -> str:
        modules = sorted({entry.module for entry in files})
        dependencies: set[str] = set()

        for metadata in metadata_by_path.values():
            for dependency in metadata.get("dependencies", []):
                dependencies.add(str(dependency))

        lines = [
            f"# {project_name} Project Context",
            "",
            "## Project Profile",
            f"- type: {project_type}",
            f"- engine: {engine}",
            f"- files: {len(files)}",
            f"- modules: {len(modules)}",
            "",
            "## Modules",
        ]

        if modules:
            lines.extend(f"- {module}" for module in modules)
        else:
            lines.append("- root")

        lines.append("")
        lines.append("## Top Dependencies")
        if dependencies:
            lines.extend(f"- {item}" for item in sorted(dependencies)[:30])
        else:
            lines.append("- none")

        lines.append("")
        lines.append("## Pipeline")
        lines.append("SCAN -> PARSE -> SUMMARIZE -> COMPILE -> INDEX -> STORE")

        return "\n".join(lines).strip() + "\n"

    def dependency_graph(
        self,
        *,
        files: list[ScannedFile],
        metadata_by_path: dict[str, dict[str, object]],
    ) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        for item in files:
            metadata = metadata_by_path.get(item.path, {})
            deps = [str(dep) for dep in metadata.get("dependencies", [])]
            graph[item.path] = deps
        return graph

    def relationship_graph(
        self,
        *,
        files: list[ScannedFile],
        metadata_by_path: dict[str, dict[str, object]],
    ) -> dict[str, list[dict[str, str]]]:
        nodes: dict[str, dict[str, str]] = {}
        edges: list[dict[str, str]] = []

        for item in files:
            file_node_id = f"file:{item.path}"
            module_node_id = f"module:{item.module}"

            nodes[file_node_id] = {
                "id": file_node_id,
                "kind": "file",
                "label": item.path,
            }
            nodes[module_node_id] = {
                "id": module_node_id,
                "kind": "module",
                "label": item.module,
            }

            edges.append(
                {
                    "source": file_node_id,
                    "target": module_node_id,
                    "relation": "related_to",
                }
            )

            metadata = metadata_by_path.get(item.path, {})
            dependencies = [str(dep) for dep in metadata.get("dependencies", []) if str(dep).strip()]

            for dependency in dependencies:
                dep_node_id = f"symbol:{dependency}"
                nodes[dep_node_id] = {
                    "id": dep_node_id,
                    "kind": "symbol",
                    "label": dependency,
                }

                relation = "uses"
                dep_lower = dependency.lower()
                if "event" in dep_lower or "emit" in dep_lower:
                    relation = "emits"

                edges.append(
                    {
                        "source": file_node_id,
                        "target": dep_node_id,
                        "relation": relation,
                    }
                )

        return {
            "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
            "edges": sorted(edges, key=lambda item: (item["source"], item["relation"], item["target"])),
        }
