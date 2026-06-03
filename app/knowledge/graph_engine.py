from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path


class KnowledgeGraphEngine:
    def __init__(self, *, project_artifacts_root: Path) -> None:
        self.project_artifacts_root = project_artifacts_root

    def expand(
        self,
        *,
        project_id: str,
        seed_terms: set[str],
        max_depth: int = 2,
        max_nodes: int = 80,
    ) -> dict[str, object]:
        payload = self._load_graph(project_id)
        dependencies = self._normalized_dependency_map(payload)
        edges = self._normalized_edges(payload)

        adjacency: dict[str, set[str]] = defaultdict(set)
        reverse_adjacency: dict[str, set[str]] = defaultdict(set)

        for source, targets in dependencies.items():
            for target in targets:
                adjacency[source].add(target)
                reverse_adjacency[target].add(source)

        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            adjacency[source].add(target)
            reverse_adjacency[target].add(source)

        seeds = self._seed_nodes(dependencies=dependencies, edges=edges, seed_terms=seed_terms)
        if not seeds:
            seeds = set(list(dependencies.keys())[:3])

        visited: set[str] = set(seeds)
        queue: deque[tuple[str, int]] = deque((node, 0) for node in sorted(seeds))

        while queue and len(visited) < max_nodes:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue

            neighbors = sorted(adjacency.get(node, set()) | reverse_adjacency.get(node, set()))
            for neighbor in neighbors:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
                if len(visited) >= max_nodes:
                    break

        relevant_systems = self._relevant_systems(visited)
        dependency_nodes = sorted(node for node in visited if self._looks_like_dependency(node))

        relation_counts: dict[str, int] = defaultdict(int)
        for edge in edges:
            if edge["source"] in visited or edge["target"] in visited:
                relation_counts[edge["relation"]] += 1

        notes: list[str] = []
        if relation_counts:
            parts = [f"{name}:{count}" for name, count in sorted(relation_counts.items())]
            notes.append("graph_relations=" + ", ".join(parts))
        if relevant_systems:
            notes.append(f"relevant_systems={', '.join(relevant_systems[:12])}")

        return {
            "seed_nodes": sorted(seeds),
            "expanded_nodes": sorted(visited),
            "dependencies": dependency_nodes,
            "relevant_systems": relevant_systems,
            "architecture_notes": notes,
        }

    def _load_graph(self, project_id: str) -> dict:
        graph_path = self.project_artifacts_root / project_id / "graphs" / "dependencies.json"
        if not graph_path.exists():
            return {}

        try:
            return json.loads(graph_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _normalized_dependency_map(self, payload: dict) -> dict[str, list[str]]:
        raw = payload.get("dependencies", {})
        if not isinstance(raw, dict):
            return {}

        result: dict[str, list[str]] = {}
        for source, values in raw.items():
            if isinstance(values, list):
                result[str(source)] = [str(item) for item in values if str(item).strip()]

        return result

    def _normalized_edges(self, payload: dict) -> list[dict[str, str]]:
        raw_edges = payload.get("edges", [])
        if not isinstance(raw_edges, list):
            return []

        edges: list[dict[str, str]] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                continue

            source = str(item.get("source") or "").strip()
            target = str(item.get("target") or "").strip()
            relation = str(item.get("relation") or "related_to").strip()
            if source and target:
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "relation": relation,
                    }
                )

        return edges

    def _seed_nodes(
        self,
        *,
        dependencies: dict[str, list[str]],
        edges: list[dict[str, str]],
        seed_terms: set[str],
    ) -> set[str]:
        if not seed_terms:
            return set()

        seeds: set[str] = set()

        for source, targets in dependencies.items():
            if self._contains_any(source, seed_terms):
                seeds.add(source)

            for target in targets:
                if self._contains_any(target, seed_terms):
                    seeds.add(target)
                    seeds.add(source)

        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            if self._contains_any(source, seed_terms) or self._contains_any(target, seed_terms):
                seeds.add(source)
                seeds.add(target)

        return seeds

    def _contains_any(self, value: str, terms: set[str]) -> bool:
        lower = value.lower()
        return any(term in lower for term in terms)

    def _relevant_systems(self, visited: set[str]) -> list[str]:
        systems: set[str] = set()

        for node in visited:
            if node.startswith("module:"):
                systems.add(node.split(":", maxsplit=1)[1])
                continue

            if "/" in node:
                systems.add(node.split("/", maxsplit=1)[0])

        return sorted(item for item in systems if item)

    def _looks_like_dependency(self, value: str) -> bool:
        if value.startswith("module:"):
            return False
        if "/" in value:
            return False
        return True
