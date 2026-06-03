from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from app.contracts import ContextPacket, ContextSnippet, RequestEnvelope, RetrievalResult
from app.knowledge.graph_engine import KnowledgeGraphEngine
from app.memory.repository import MemoryRepository


@dataclass
class RetrievalCandidate:
    source: str
    content: str
    relevance_score: float
    freshness_score: float
    confidence_score: float
    importance_score: float
    dependencies: list[str]
    candidate_type: str
    modified_at: datetime | None = None

    @property
    def final_score(self) -> float:
        weighted = (
            self.relevance_score * 0.50
            + self.freshness_score * 0.15
            + self.confidence_score * 0.20
            + self.importance_score * 0.15
        )
        return max(0.0, min(1.0, round(weighted, 4)))

    @property
    def is_hot(self) -> bool:
        return self.freshness_score >= 0.75


class ContextRetrievalEngine:
    def __init__(
        self,
        *,
        memory_repository: MemoryRepository,
        project_artifacts_root: Path,
        max_chars: int = 3500,
        knowledge_compiler: object | None = None,
    ) -> None:
        self.memory_repository = memory_repository
        self.project_artifacts_root = project_artifacts_root
        self.max_chars = max_chars
        self.knowledge_compiler = knowledge_compiler
        self.graph_engine = KnowledgeGraphEngine(project_artifacts_root=self.project_artifacts_root)

    def assemble(self, envelope: RequestEnvelope) -> tuple[ContextPacket, RetrievalResult]:
        started = perf_counter()
        intent_terms = self._intent_terms(envelope.prompt)
        user_intent = self._detect_user_intent(envelope.prompt)

        memories = self.memory_repository.search(
            project_id=envelope.project_id,
            user_id=envelope.user_id,
            query=envelope.prompt,
            limit=10,
        )

        candidates: list[RetrievalCandidate] = []
        candidates.extend(self._memory_candidates(memories, intent_terms))
        candidates.extend(self._knowledge_candidates(envelope.prompt, intent_terms))

        artifact_candidates, direct_dependencies, recent_changes = self._artifact_candidates(
            project_id=envelope.project_id,
            intent_terms=intent_terms,
        )
        candidates.extend(artifact_candidates)

        graph_expansion = self.graph_engine.expand(
            project_id=envelope.project_id,
            seed_terms=intent_terms,
            max_depth=2,
            max_nodes=80,
        )

        deduplicated = self._deduplicate(candidates)
        selected, dropped = self._compress(deduplicated)

        hot_context = [item.source for item in selected if item.is_hot]
        cold_knowledge = [item.source for item in selected if not item.is_hot]

        snippets = [
            ContextSnippet(
                source=item.source,
                content=item.content,
                score=item.final_score,
                scores={
                    "relevance_score": item.relevance_score,
                    "freshness_score": item.freshness_score,
                    "confidence_score": item.confidence_score,
                    "importance_score": item.importance_score,
                },
            )
            for item in selected
        ]

        packet = ContextPacket(
            snippets=snippets,
            provenance=[snippet.source for snippet in snippets],
        )

        context_packet = [
            {
                "source": item.source,
                "type": item.candidate_type,
                "score": item.final_score,
                "scores": {
                    "relevance_score": item.relevance_score,
                    "freshness_score": item.freshness_score,
                    "confidence_score": item.confidence_score,
                    "importance_score": item.importance_score,
                },
                "hot": item.is_hot,
                "dependencies": item.dependencies,
            }
            for item in selected
        ]

        dependencies = set(direct_dependencies)
        dependencies.update(str(item) for item in graph_expansion.get("dependencies", []))
        dependencies.update(dep for item in selected for dep in item.dependencies)

        relevant_systems = set(str(item) for item in graph_expansion.get("relevant_systems", []))
        relevant_systems.update(self._derive_systems_from_sources(selected))

        architecture_notes = [str(item) for item in graph_expansion.get("architecture_notes", [])]
        architecture_notes.append(f"hot_context={len(hot_context)}")
        architecture_notes.append(f"cold_knowledge={len(cold_knowledge)}")

        risks = self._build_risk_analysis(selected=selected, dropped=dropped)
        compression_payload = {
            "selected_count": len(selected),
            "dropped_count": len(dropped),
            "max_chars": self.max_chars,
            "used_chars": sum(len(item.content) for item in selected),
        }

        assembled = {
            "query": envelope.prompt,
            "user_intent": user_intent,
            "relevant_systems": sorted(item for item in relevant_systems if item),
            "dependencies": sorted(item for item in dependencies if item),
            "architecture_notes": architecture_notes,
            "recent_changes": recent_changes[:25],
            "risks": risks,
            "context_packet": context_packet,
            "hot_context": hot_context,
            "cold_knowledge": cold_knowledge,
            "compression": compression_payload,
            # Backward compatible aliases for existing callers/tests.
            "contexts": context_packet,
            "memories": [entry.id for entry in memories],
            "risk_analysis": risks,
        }

        took_ms = int((perf_counter() - started) * 1000)
        retrieval = RetrievalResult(
            query=envelope.prompt,
            entries=memories,
            took_ms=took_ms,
            assembled=assembled,
        )

        return packet, retrieval

    def _memory_candidates(self, memories: list, terms: set[str]) -> list[RetrievalCandidate]:
        candidates: list[RetrievalCandidate] = []
        for memory in memories:
            content = memory.content.strip()
            relevance = self._text_relevance(content, terms)
            freshness = self._freshness_score(memory.updated_at)
            confidence = max(0.0, min(1.0, float(memory.confidence)))
            importance = 0.65 if memory.scope.value == "project" else 0.55

            candidates.append(
                RetrievalCandidate(
                    source=f"memory:{memory.scope.value}:{memory.id}",
                    content=content,
                    relevance_score=relevance,
                    freshness_score=freshness,
                    confidence_score=confidence,
                    importance_score=importance,
                    dependencies=[],
                    candidate_type="memory",
                )
            )

        return candidates

    def _knowledge_candidates(self, prompt: str, terms: set[str]) -> list[RetrievalCandidate]:
        if self.knowledge_compiler is None:
            return []

        candidates: list[RetrievalCandidate] = []
        try:
            nodes = self.knowledge_compiler.search(prompt, limit=8)
        except Exception:
            return []

        for node in nodes:
            summary = (node.summary or "").strip()
            if not summary:
                continue

            metadata_text = " ".join(
                [
                    node.title,
                    node.source_path,
                    " ".join(node.dependencies),
                    " ".join(node.patterns),
                ]
            )
            relevance = max(self._text_relevance(summary, terms), self._text_relevance(metadata_text, terms))
            confidence = max(0.0, min(1.0, float(node.confidence)))
            importance = 0.60 + min(0.30, len(node.dependencies) * 0.03)

            candidates.append(
                RetrievalCandidate(
                    source=f"knowledge:{node.level.value}:{node.node_id}",
                    content=summary,
                    relevance_score=relevance,
                    freshness_score=0.70,
                    confidence_score=confidence,
                    importance_score=min(1.0, importance),
                    dependencies=list(node.dependencies),
                    candidate_type="knowledge",
                )
            )

        return candidates

    def _artifact_candidates(
        self,
        *,
        project_id: str,
        intent_terms: set[str],
    ) -> tuple[list[RetrievalCandidate], set[str], list[str]]:
        metadata_root = self.project_artifacts_root / project_id / "metadata" / "files"
        summary_root = self.project_artifacts_root / project_id / "summaries" / "files"

        if not metadata_root.exists():
            return [], set(), []

        candidates: list[RetrievalCandidate] = []
        expanded_dependencies: set[str] = set()
        recent_changes: list[str] = []

        for metadata_path in metadata_root.rglob("*.meta.json"):
            metadata = self._load_json(metadata_path)
            if not metadata:
                continue

            file_path = str(metadata.get("path") or "").strip()
            if not file_path:
                continue

            summary_path = self._summary_path_for_metadata(
                metadata_root=metadata_root,
                summary_root=summary_root,
                metadata_path=metadata_path,
            )
            content = self._safe_read(summary_path)
            if not content:
                content = f"# {Path(file_path).stem}\n"

            symbols = [str(item) for item in metadata.get("symbols", [])]
            direct_deps = [str(item) for item in metadata.get("dependencies", [])]
            query_space = " ".join([file_path, content, " ".join(symbols), " ".join(direct_deps)])

            relevance = self._text_relevance(query_space, intent_terms)
            if relevance <= 0.05:
                continue

            modified_at = self._parse_dt(str(metadata.get("modified_at", "")))
            freshness = self._freshness_score(modified_at)
            confidence = float(metadata.get("confidence", 0.78))
            confidence = max(0.3, min(1.0, confidence))
            importance = 0.50 + min(0.45, len(direct_deps) * 0.04)

            expanded_dependencies.update(direct_deps)
            if freshness >= 0.85:
                recent_changes.append(file_path)

            candidates.append(
                RetrievalCandidate(
                    source=f"artifact:file:{file_path}",
                    content=content.strip(),
                    relevance_score=relevance,
                    freshness_score=freshness,
                    confidence_score=confidence,
                    importance_score=min(1.0, importance),
                    dependencies=direct_deps,
                    candidate_type="artifact",
                    modified_at=modified_at,
                )
            )

        return candidates, expanded_dependencies, sorted(set(recent_changes))

    def _deduplicate(self, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        dedup: dict[str, RetrievalCandidate] = {}
        for candidate in candidates:
            normalized = " ".join(candidate.content.lower().split())
            key = f"{candidate.candidate_type}:{normalized[:420]}"
            previous = dedup.get(key)
            if previous is None or candidate.final_score > previous.final_score:
                dedup[key] = candidate

        return sorted(
            dedup.values(),
            key=lambda item: (item.is_hot, item.final_score, len(item.dependencies)),
            reverse=True,
        )

    def _compress(self, candidates: list[RetrievalCandidate]) -> tuple[list[RetrievalCandidate], list[RetrievalCandidate]]:
        selected: list[RetrievalCandidate] = []
        dropped: list[RetrievalCandidate] = []
        running = 0

        for candidate in candidates:
            size = len(candidate.content)
            if running + size > self.max_chars:
                dropped.append(candidate)
                continue
            selected.append(candidate)
            running += size

        return selected, dropped

    def _build_risk_analysis(
        self,
        *,
        selected: list[RetrievalCandidate],
        dropped: list[RetrievalCandidate],
    ) -> list[str]:
        risks: list[str] = []

        if not selected:
            risks.append("No relevant context selected; fallback to model-only reasoning may reduce quality.")

        stale_like = [item for item in selected if item.freshness_score < 0.40]
        if stale_like:
            risks.append(f"{len(stale_like)} selected contexts may be stale (low freshness score).")

        if dropped:
            risks.append(f"Token budget dropped {len(dropped)} context candidates.")

        low_confidence = [item for item in selected if item.confidence_score < 0.50]
        if low_confidence:
            risks.append(f"{len(low_confidence)} selected contexts have low confidence score.")

        return risks

    def _detect_user_intent(self, prompt: str) -> str:
        lower = prompt.lower()
        if any(token in lower for token in ("refator", "refactor", "rewrite", "clean up")):
            return "refactor"
        if any(token in lower for token in ("bug", "erro", "error", "fix", "hotfix")):
            return "debug"
        if any(token in lower for token in ("arquitet", "architecture", "design", "trade-off")):
            return "architecture"
        if any(token in lower for token in ("teste", "test", "coverage", "regression")):
            return "testing"
        return "general-query"

    def _intent_terms(self, prompt: str) -> set[str]:
        raw_terms = [item.strip().lower() for item in prompt.split()]
        cleaned = {"".join(ch for ch in term if ch.isalnum() or ch in {"_", "-"}) for term in raw_terms}
        return {term for term in cleaned if len(term) >= 2}

    def _text_relevance(self, value: str, terms: set[str]) -> float:
        if not terms:
            return 0.0

        haystack = value.lower()
        hits = 0
        for term in terms:
            if term and term in haystack:
                hits += 1

        return max(0.0, min(1.0, hits / max(1, len(terms))))

    def _derive_systems_from_sources(self, selected: list[RetrievalCandidate]) -> set[str]:
        systems: set[str] = set()
        for item in selected:
            source = item.source
            if source.startswith("artifact:file:"):
                relative = source.removeprefix("artifact:file:")
                if "/" in relative:
                    systems.add(relative.split("/", maxsplit=1)[0])
            elif source.startswith("knowledge:module:"):
                tail = source.split(":")[-1]
                systems.add(tail.replace("module:", ""))

        return systems

    def _freshness_score(self, instant: datetime | None) -> float:
        if instant is None:
            return 0.55

        now = datetime.now(timezone.utc)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)

        age_days = max(0.0, (now - instant).total_seconds() / 86400)
        if age_days <= 1:
            return 1.0
        if age_days <= 7:
            return 0.85
        if age_days <= 30:
            return 0.70
        if age_days <= 90:
            return 0.55
        return 0.40

    def _parse_dt(self, value: str) -> datetime | None:
        text = (value or "").strip()
        if not text:
            return None

        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _summary_path_for_metadata(self, *, metadata_root: Path, summary_root: Path, metadata_path: Path) -> Path:
        relative = metadata_path.relative_to(metadata_root)
        name = relative.name

        if name.endswith(".meta.json"):
            summary_name = name[: -len(".meta.json")] + ".summary.md"
        else:
            summary_name = relative.stem + ".summary.md"

        return summary_root / relative.parent / summary_name

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            return {}

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _safe_read(self, path: Path) -> str:
        if not path.exists():
            return ""

        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1", errors="ignore")
