from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.knowledge.models import (
    KnowledgeLevel,
    KnowledgeNode,
    KnowledgeNodeView,
    KnowledgeSyncReport,
    KnowledgeTreeResponse,
)


DEFAULT_EXTENSIONS = {
    ".py",
    ".lua",
    ".md",
    ".txt",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".cs",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".shader",
    ".asmdef",
    ".uxml",
}

EXCLUDED_DIRS = {
    ".git",
    ".brasa",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
}

LEVEL_ORDER = {
    KnowledgeLevel.FILE: 0,
    KnowledgeLevel.FOLDER: 1,
    KnowledgeLevel.MODULE: 2,
    KnowledgeLevel.PROJECT: 3,
    KnowledgeLevel.GLOBAL: 4,
}


@dataclass
class MutableNode:
    node_id: str
    level: KnowledgeLevel
    title: str
    source_path: str
    source_hash: str = ""
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    dependencies: set[str] = field(default_factory=set)
    patterns: set[str] = field(default_factory=set)
    related_systems: set[str] = field(default_factory=set)
    file_versions: list[dict[str, str]] = field(default_factory=list)
    confidence: float = 0.6
    risk_level: str = "low"
    summary: str = ""
    stale: bool = False
    generation: int = 1
    metadata: dict[str, object] = field(default_factory=dict)
    readme_path: str = ""
    metadata_path: str = ""


class KnowledgeCompiler:
    def __init__(
        self,
        *,
        project_root: Path,
        output_dir: Path,
        state_file: Path,
        include_extensions: set[str] | None = None,
        max_file_bytes: int = 300_000,
    ) -> None:
        self.project_root = project_root
        self.output_dir = output_dir
        self.state_file = state_file
        self.include_extensions = include_extensions or set(DEFAULT_EXTENSIONS)
        self.max_file_bytes = max_file_bytes

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def sync(self, *, force: bool = False, include_extensions: list[str] | None = None) -> KnowledgeSyncReport:
        started_at = datetime.now(timezone.utc)

        previous_state = self._load_state()
        nodes, scanned_files = self._build_graph(include_extensions=include_extensions)

        changed_nodes, stale_nodes = self._mark_stale(nodes=nodes, previous_state=previous_state, force=force)
        regenerated_nodes = self._regenerate_stale_nodes(nodes=nodes)
        removed_nodes = self._cleanup_removed_nodes(previous_state=previous_state, current_nodes=nodes)

        self._persist_state(nodes, previous_state=previous_state)

        finished_at = datetime.now(timezone.utc)
        notes = [
            f"Scanned {scanned_files} source files.",
            f"Marked {stale_nodes} stale nodes.",
        ]
        if removed_nodes:
            notes.append(f"Removed {removed_nodes} obsolete node artifacts.")

        return KnowledgeSyncReport(
            started_at=started_at,
            finished_at=finished_at,
            scanned_files=scanned_files,
            changed_nodes=changed_nodes,
            regenerated_nodes=regenerated_nodes,
            removed_nodes=removed_nodes,
            stale_nodes=stale_nodes,
            notes=notes,
        )

    def tree(self) -> KnowledgeTreeResponse:
        state = self._load_state()
        node_records = state.get("nodes", {})

        nodes: list[KnowledgeNodeView] = []
        stale_nodes = 0

        for payload in node_records.values():
            try:
                node = KnowledgeNode.model_validate(payload)
            except Exception:
                continue

            if node.stale:
                stale_nodes += 1

            nodes.append(
                KnowledgeNodeView(
                    node_id=node.node_id,
                    level=node.level,
                    title=node.title,
                    source_path=node.source_path,
                    stale=node.stale,
                    confidence=node.confidence,
                    generation=node.generation,
                    dependencies=node.dependencies,
                    patterns=node.patterns,
                    children=node.children,
                    readme_path=node.readme_path,
                    metadata_path=node.metadata_path,
                )
            )

        nodes.sort(key=lambda item: (LEVEL_ORDER[item.level], item.source_path, item.node_id))
        return KnowledgeTreeResponse(nodes=nodes, stale_nodes=stale_nodes)

    def stale_count(self) -> int:
        return self.estimate_drift()

    def estimate_drift(self) -> int:
        previous_state = self._load_state()
        previous_nodes = previous_state.get("nodes", {})
        current_nodes, _ = self._build_graph(include_extensions=None)

        drift = 0
        for node_id, node in current_nodes.items():
            previous = previous_nodes.get(node_id)
            if not previous:
                drift += 1
                continue
            if previous.get("source_hash") != node.source_hash:
                drift += 1

        for node_id in previous_nodes.keys():
            if node_id not in current_nodes:
                drift += 1

        return drift

    def search(self, query: str, limit: int = 5) -> list[KnowledgeNode]:
        terms = [token for token in query.lower().split() if len(token) >= 2]
        if not terms:
            return []

        state = self._load_state()
        matches: list[tuple[float, KnowledgeNode]] = []

        for payload in state.get("nodes", {}).values():
            try:
                node = KnowledgeNode.model_validate(payload)
            except Exception:
                continue

            haystack = " ".join(
                [
                    node.title.lower(),
                    node.source_path.lower(),
                    node.summary.lower(),
                    " ".join(node.dependencies).lower(),
                    " ".join(node.patterns).lower(),
                ]
            )

            score = 0.0
            for term in terms:
                if term in haystack:
                    score += 1.0
            if score <= 0:
                continue

            score = score / len(terms)
            score = score * (0.6 + 0.4 * node.confidence)
            matches.append((score, node))

        matches.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in matches[: max(1, min(limit, 20))]]

    def _build_graph(self, *, include_extensions: list[str] | None) -> tuple[dict[str, MutableNode], int]:
        extension_filter = self._normalize_extensions(include_extensions)
        nodes: dict[str, MutableNode] = {}

        project_name = self.project_root.name
        project_node_id = f"project:{project_name}"
        global_node_id = "global:default"

        nodes[project_node_id] = MutableNode(
            node_id=project_node_id,
            level=KnowledgeLevel.PROJECT,
            title=f"{project_name} Knowledge",
            source_path="/",
            parent_id=global_node_id,
        )
        nodes[global_node_id] = MutableNode(
            node_id=global_node_id,
            level=KnowledgeLevel.GLOBAL,
            title="Global Project Memory",
            source_path="global",
            parent_id=None,
            children=[project_node_id],
        )

        module_roots: set[str] = set()
        scanned_files = 0

        for file_path in sorted(self.project_root.rglob("*")):
            if not file_path.is_file():
                continue
            if self._is_excluded(file_path):
                continue
            if file_path.stat().st_size > self.max_file_bytes:
                continue
            if extension_filter and file_path.suffix.lower() not in extension_filter:
                continue

            scanned_files += 1
            rel_path = file_path.relative_to(self.project_root)
            rel_posix = rel_path.as_posix()

            module_name = rel_path.parts[0] if len(rel_path.parts) > 1 else "root"
            module_roots.add(module_name)
            module_node = self._ensure_module_node(nodes, module_name, project_node_id)

            parent_folder_id = self._ensure_folder_nodes(nodes, rel_path.parent, module_node.node_id)

            content = self._safe_read(file_path)
            file_hash = self._sha256(content)
            parsed = self._parse_file(content=content, rel_path=rel_posix)

            file_node_id = f"file:{rel_posix}"
            file_node = MutableNode(
                node_id=file_node_id,
                level=KnowledgeLevel.FILE,
                title=rel_path.name,
                source_path=rel_posix,
                source_hash=file_hash,
                parent_id=parent_folder_id,
                dependencies=set(parsed["dependencies"]),
                patterns=set(parsed["patterns"]),
                related_systems={module_name},
                file_versions=[{"path": rel_posix, "hash": file_hash}],
                confidence=parsed["confidence"],
                risk_level=parsed["risk_level"],
                summary=parsed["summary"],
                metadata={
                    "symbols": parsed["symbols"],
                    "imports": parsed["dependencies"],
                    "line_count": parsed["line_count"],
                },
            )
            nodes[file_node_id] = file_node

            if parent_folder_id:
                parent_folder = nodes[parent_folder_id]
                if file_node_id not in parent_folder.children:
                    parent_folder.children.append(file_node_id)
            else:
                if file_node_id not in module_node.children:
                    module_node.children.append(file_node_id)

        for module_name in sorted(module_roots):
            module_node_id = f"module:{module_name}"
            if module_node_id not in nodes[project_node_id].children:
                nodes[project_node_id].children.append(module_node_id)

        self._compute_non_file_nodes(nodes)
        return nodes, scanned_files

    def _compute_non_file_nodes(self, nodes: dict[str, MutableNode]) -> None:
        folder_nodes = [node for node in nodes.values() if node.level == KnowledgeLevel.FOLDER]
        folder_nodes.sort(key=lambda item: item.source_path.count("/"), reverse=True)

        for node in folder_nodes:
            self._aggregate_from_children(node=node, nodes=nodes)

        for level in (KnowledgeLevel.MODULE, KnowledgeLevel.PROJECT, KnowledgeLevel.GLOBAL):
            level_nodes = [node for node in nodes.values() if node.level == level]
            for node in level_nodes:
                self._aggregate_from_children(node=node, nodes=nodes)

    def _aggregate_from_children(self, *, node: MutableNode, nodes: dict[str, MutableNode]) -> None:
        child_nodes = [nodes[child_id] for child_id in sorted(node.children) if child_id in nodes]

        dependencies: set[str] = set()
        patterns: set[str] = set()
        related_systems: set[str] = set()
        file_versions: list[dict[str, str]] = []
        confidence_acc = 0.0

        for child in child_nodes:
            dependencies.update(child.dependencies)
            patterns.update(child.patterns)
            related_systems.update(child.related_systems)
            file_versions.extend(child.file_versions)
            confidence_acc += child.confidence

        child_hash_parts = [f"{child.node_id}:{child.source_hash}" for child in child_nodes]
        node.source_hash = self._sha256("|".join(child_hash_parts)) if child_hash_parts else self._sha256(node.node_id)
        node.dependencies = dependencies
        node.patterns = patterns
        node.related_systems = related_systems
        node.file_versions = self._compress_file_versions(file_versions)

        if child_nodes:
            node.confidence = round(min(0.98, max(0.40, confidence_acc / len(child_nodes))), 2)
        else:
            node.confidence = 0.40

        node.risk_level = self._risk_from_versions(node.file_versions)
        node.summary = self._compose_aggregated_summary(node=node, child_nodes=child_nodes)
        node.metadata = {
            "child_count": len(child_nodes),
            "file_count": len(node.file_versions),
        }

    def _mark_stale(
        self,
        *,
        nodes: dict[str, MutableNode],
        previous_state: dict,
        force: bool,
    ) -> tuple[int, int]:
        previous_nodes = previous_state.get("nodes", {})

        changed_nodes = 0
        stale_nodes = 0
        now = datetime.now(timezone.utc)

        for node in nodes.values():
            previous = previous_nodes.get(node.node_id)
            changed = force or (not previous) or (previous.get("source_hash") != node.source_hash)

            node.stale = bool(changed)
            if changed:
                changed_nodes += 1
                stale_nodes += 1
                node.generation = int((previous or {}).get("generation") or 0) + 1
            else:
                node.generation = int((previous or {}).get("generation") or 1)

            node.metadata["last_scan"] = now.isoformat()
            node.metadata["source_hash"] = node.source_hash

        return changed_nodes, stale_nodes

    def _regenerate_stale_nodes(self, *, nodes: dict[str, MutableNode]) -> int:
        stale_nodes = [node for node in nodes.values() if node.stale]
        stale_nodes.sort(key=lambda item: (LEVEL_ORDER[item.level], item.source_path, item.node_id))

        for node in stale_nodes:
            readme_path, metadata_path = self._artifact_paths(node)
            readme_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)

            summary_payload = self._node_to_summary_payload(node)

            readme_content = self._render_readme(node=node, metadata=summary_payload)
            readme_path.write_text(readme_content, encoding="utf-8")

            metadata_path.write_text(
                json.dumps(summary_payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

            node.readme_path = readme_path.relative_to(self.project_root).as_posix()
            node.metadata_path = metadata_path.relative_to(self.project_root).as_posix()
            node.stale = False

        return len(stale_nodes)

    def _cleanup_removed_nodes(self, *, previous_state: dict, current_nodes: dict[str, MutableNode]) -> int:
        previous_nodes = previous_state.get("nodes", {})
        removed = 0

        for node_id, payload in previous_nodes.items():
            if node_id in current_nodes:
                continue

            readme_path = payload.get("readme_path")
            metadata_path = payload.get("metadata_path")

            for relative_path in (readme_path, metadata_path):
                if not relative_path:
                    continue
                target = self.project_root / relative_path
                if target.exists():
                    target.unlink()
                    removed += 1

        return removed

    def _persist_state(self, nodes: dict[str, MutableNode], previous_state: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        serialized_nodes: dict[str, dict] = {}
        previous_nodes = previous_state.get("nodes", {})

        for node in nodes.values():
            if not node.readme_path or not node.metadata_path:
                previous = previous_nodes.get(node.node_id, {})
                node.readme_path = previous.get("readme_path", node.readme_path)
                node.metadata_path = previous.get("metadata_path", node.metadata_path)

            serialized_nodes[node.node_id] = KnowledgeNode(
                node_id=node.node_id,
                level=node.level,
                title=node.title,
                source_path=node.source_path,
                source_hash=node.source_hash,
                last_scan=datetime.now(timezone.utc),
                file_versions=node.file_versions,
                confidence=node.confidence,
                stale=node.stale,
                generation=node.generation,
                dependencies=sorted(node.dependencies),
                patterns=sorted(node.patterns),
                related_systems=sorted(node.related_systems),
                risk_level=node.risk_level,
                children=sorted(node.children),
                parent_id=node.parent_id,
                summary=node.summary,
                metadata=node.metadata,
                readme_path=node.readme_path,
                metadata_path=node.metadata_path,
            ).model_dump(mode="json")

        payload = {
            "version": 1,
            "updated_at": now,
            "nodes": serialized_nodes,
        }
        self.state_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _load_state(self) -> dict:
        if not self.state_file.exists():
            return {"version": 1, "nodes": {}}

        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"version": 1, "nodes": {}}

    def _artifact_paths(self, node: MutableNode) -> tuple[Path, Path]:
        if node.level == KnowledgeLevel.FILE:
            base = self.output_dir / "files" / node.source_path
            return base.with_suffix(base.suffix + ".README.md"), base.with_suffix(base.suffix + ".metadata.json")

        if node.level == KnowledgeLevel.FOLDER:
            folder_key = node.source_path or "_root"
            base = self.output_dir / "folders" / folder_key
            return base / "README.md", base / "metadata.json"

        if node.level == KnowledgeLevel.MODULE:
            base = self.output_dir / "modules" / node.source_path
            return base / "README.md", base / "metadata.json"

        if node.level == KnowledgeLevel.PROJECT:
            base = self.output_dir / "project"
            return base / "PROJECT_KNOWLEDGE.md", base / "PROJECT_KNOWLEDGE.json"

        base = self.output_dir / "global"
        return base / "GLOBAL_MEMORY.md", base / "GLOBAL_MEMORY.json"

    def _node_to_summary_payload(self, node: MutableNode) -> dict:
        return {
            "node_id": node.node_id,
            "level": node.level.value,
            "title": node.title,
            "source_path": node.source_path,
            "source_hash": node.source_hash,
            "last_scan": datetime.now(timezone.utc).isoformat(),
            "file_versions": node.file_versions,
            "confidence": round(node.confidence, 2),
            "stale": False,
            "generation": node.generation,
            "dependencies": sorted(node.dependencies),
            "patterns": sorted(node.patterns),
            "related_systems": sorted(node.related_systems),
            "risk_level": node.risk_level,
            "children": sorted(node.children),
            "parent_id": node.parent_id,
            "summary": node.summary,
        }

    def _render_readme(self, *, node: MutableNode, metadata: dict) -> str:
        summary = node.summary.strip() or "No summary available."
        dependencies = metadata.get("dependencies", [])
        patterns = metadata.get("patterns", [])

        lines = [
            f"# {node.title}",
            "",
            f"Level: {node.level.value}",
            f"Source: {node.source_path}",
            f"Confidence: {metadata.get('confidence', 0.0):.2f}",
            f"Generation: {metadata.get('generation', 1)}",
            "",
            "## Summary",
            summary,
            "",
            "## Dependencies",
        ]

        if dependencies:
            lines.extend(f"- {item}" for item in dependencies)
        else:
            lines.append("- none")

        lines.append("")
        lines.append("## Patterns")
        if patterns:
            lines.extend(f"- {item}" for item in patterns)
        else:
            lines.append("- none")

        lines.append("")
        lines.append("## Structured Metadata")
        lines.append("```json")
        lines.append(json.dumps(metadata, ensure_ascii=True, indent=2))
        lines.append("```")

        return "\n".join(lines) + "\n"

    def _parse_file(self, *, content: str, rel_path: str) -> dict[str, object]:
        lines = content.splitlines()
        line_count = len(lines)

        symbols = self._extract_symbols(content)
        imports = self._extract_dependencies(content)
        patterns = self._detect_patterns(content)
        confidence = self._estimate_file_confidence(symbols=symbols, imports=imports, line_count=line_count)
        risk_level = self._risk_from_content(content=content, line_count=line_count)

        summary_lines = [
            "Responsibilities:",
            "- preserve source intent and API boundaries",
            "- expose coherent behavior for this unit",
        ]

        if symbols:
            summary_lines.append("Core Symbols:")
            for symbol in symbols[:6]:
                summary_lines.append(f"- {symbol}")

        if imports:
            summary_lines.append("Dependencies:")
            for dependency in imports[:8]:
                summary_lines.append(f"- {dependency}")

        if patterns:
            summary_lines.append("Detected Patterns:")
            for pattern in sorted(patterns):
                summary_lines.append(f"- {pattern}")

        summary = "\n".join(summary_lines)

        return {
            "summary": summary,
            "dependencies": imports,
            "patterns": sorted(patterns),
            "symbols": symbols,
            "confidence": confidence,
            "risk_level": risk_level,
            "line_count": line_count,
        }

    def _extract_symbols(self, content: str) -> list[str]:
        patterns = [
            r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*async\s+def\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface|record)\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:[A-Za-z_][A-Za-z0-9_<>,\[\]]*\s+)+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)",
        ]

        found: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, content, flags=re.MULTILINE):
                if match not in found:
                    found.append(match)

        return found[:20]

    def _extract_dependencies(self, content: str) -> list[str]:
        regexes = [
            r"^\s*import\s+([A-Za-z0-9_\.\{\}\*\s,]+)\s+from\s+['\"]([^'\"]+)['\"]",
            r"^\s*import\s+([A-Za-z0-9_\.]+)",
            r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import",
            r"^\s*using\s+([A-Za-z0-9_\.]+)",
            r"require\(['\"]([^'\"]+)['\"]\)",
        ]

        dependencies: set[str] = set()

        for regex in regexes:
            for match in re.findall(regex, content, flags=re.MULTILINE):
                if isinstance(match, tuple):
                    dependency = match[-1]
                else:
                    dependency = match
                dependency = dependency.strip()
                if dependency:
                    dependencies.add(dependency)

        return sorted(dependencies)[:30]

    def _detect_patterns(self, content: str) -> set[str]:
        lower = content.lower()
        patterns: set[str] = set()

        checks = {
            "event-driven": ["event", "emit", "subscribe", "listener"],
            "singleton": ["singleton", "instance", "getinstance"],
            "async": ["async", "await", "task", "future"],
            "dependency-injection": ["inject", "container", "provider"],
            "repository": ["repository", "dao", "storage"],
            "api-layer": ["fastapi", "router", "endpoint", "controller"],
        }

        for label, keys in checks.items():
            if any(key in lower for key in keys):
                patterns.add(label)

        return patterns

    def _estimate_file_confidence(self, *, symbols: list[str], imports: list[str], line_count: int) -> float:
        score = 0.50
        score += min(0.20, len(symbols) * 0.02)
        score += min(0.12, len(imports) * 0.02)

        if line_count > 20:
            score += 0.06
        if line_count > 120:
            score += 0.04

        return round(min(0.96, max(0.35, score)), 2)

    def _risk_from_content(self, *, content: str, line_count: int) -> str:
        lower = content.lower()
        score = 0

        if line_count > 500:
            score += 2
        elif line_count > 220:
            score += 1

        for token in ("todo", "hack", "temporary", "deprecated", "fixme"):
            if token in lower:
                score += 1

        if score >= 3:
            return "high"
        if score >= 1:
            return "medium"
        return "low"

    def _risk_from_versions(self, versions: list[dict[str, str]]) -> str:
        count = len(versions)
        if count >= 25:
            return "high"
        if count >= 8:
            return "medium"
        return "low"

    def _compose_aggregated_summary(self, *, node: MutableNode, child_nodes: list[MutableNode]) -> str:
        top_children = [child.title for child in child_nodes[:8]]
        summary_lines = [
            f"Aggregated {node.level.value} knowledge.",
            f"Child nodes: {len(child_nodes)}",
        ]

        if top_children:
            summary_lines.append("Core Components:")
            for child_title in top_children:
                summary_lines.append(f"- {child_title}")

        if node.dependencies:
            summary_lines.append("Dependencies:")
            for dependency in sorted(node.dependencies)[:10]:
                summary_lines.append(f"- {dependency}")

        if node.patterns:
            summary_lines.append("Architecture Patterns:")
            for pattern in sorted(node.patterns):
                summary_lines.append(f"- {pattern}")

        return "\n".join(summary_lines)

    def _ensure_module_node(self, nodes: dict[str, MutableNode], module_name: str, project_node_id: str) -> MutableNode:
        module_node_id = f"module:{module_name}"
        module_node = nodes.get(module_node_id)

        if module_node is None:
            module_node = MutableNode(
                node_id=module_node_id,
                level=KnowledgeLevel.MODULE,
                title=f"Module {module_name}",
                source_path=module_name,
                parent_id=project_node_id,
            )
            nodes[module_node_id] = module_node

        return module_node

    def _ensure_folder_nodes(self, nodes: dict[str, MutableNode], folder_path: Path, fallback_parent_module_id: str) -> str | None:
        if str(folder_path) in {"", "."}:
            return None

        parts = folder_path.parts
        created_ids: list[str] = []

        for index in range(1, len(parts) + 1):
            current = Path(*parts[:index]).as_posix()
            node_id = f"folder:{current}"
            if node_id not in nodes:
                parent_id = None
                if index == 1:
                    parent_id = f"module:{parts[0]}"
                else:
                    parent_id = f"folder:{Path(*parts[: index - 1]).as_posix()}"

                nodes[node_id] = MutableNode(
                    node_id=node_id,
                    level=KnowledgeLevel.FOLDER,
                    title=f"Folder {current}",
                    source_path=current,
                    parent_id=parent_id,
                )

            created_ids.append(node_id)

        for index, node_id in enumerate(created_ids):
            node = nodes[node_id]
            if index == 0:
                if node_id not in nodes[fallback_parent_module_id].children:
                    nodes[fallback_parent_module_id].children.append(node_id)
            else:
                parent_id = created_ids[index - 1]
                if node_id not in nodes[parent_id].children:
                    nodes[parent_id].children.append(node_id)

        return created_ids[-1]

    def _compress_file_versions(self, versions: list[dict[str, str]]) -> list[dict[str, str]]:
        deduplicated: dict[str, str] = {}
        for item in versions:
            path = item.get("path") or ""
            hash_value = item.get("hash") or ""
            if path and hash_value:
                deduplicated[path] = hash_value

        reduced = [{"path": path, "hash": deduplicated[path]} for path in sorted(deduplicated.keys())]
        return reduced[:300]

    def _normalize_extensions(self, include_extensions: list[str] | None) -> set[str]:
        if not include_extensions:
            return set(self.include_extensions)

        normalized: set[str] = set()
        for value in include_extensions:
            cleaned = value.strip().lower()
            if not cleaned:
                continue
            if not cleaned.startswith("."):
                cleaned = f".{cleaned}"
            normalized.add(cleaned)

        return normalized or set(self.include_extensions)

    def _safe_read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1", errors="ignore")

    def _sha256(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()

    def _is_excluded(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.project_root)
        except ValueError:
            return True

        try:
            path.relative_to(self.output_dir)
            return True
        except ValueError:
            pass

        for part in relative.parts:
            if part in EXCLUDED_DIRS:
                return True

        return False
