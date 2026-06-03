from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from app.contracts import ContextPacket, ContextSnippet, RequestEnvelope, RetrievalResult
from app.knowledge.graph_engine import KnowledgeGraphEngine
from app.memory.repository import MemoryRepository
from app.workspace import resolve_project_root, split_scoped_project_id


NOISE_PATH_SEGMENTS = (
    "/.git/",
    "/build/",
    "/cmake/",
    "/vc17/",
    "/triplets/",
    "/vcpkg_installed/",
    "/node_modules/",
    "/metadata/files/vcpkg_installed/",
    "/metadata/files/build/",
    "/metadata/files/cmake/",
)

MMO_XML_DIRS = (
    "/data/actions/",
    "/data/talkactions/",
    "/data/creaturescripts/",
    "/data/movements/",
    "/data/spells/",
    "/data/globalevents/",
    "/data/events/",
)

MMO_CORE_SRC_HINTS = (
    "/src/otserv",
    "/src/scriptmanager",
    "/src/baseevents",
    "/src/script",
    "/src/luascript",
    "/src/actions",
    "/src/talkaction",
    "/src/creatureevent",
    "/src/movement",
    "/src/spells",
    "/src/globalevent",
    "/src/events",
)

GENERIC_CODE_DIR_HINTS = (
    "/src/",
    "/app/",
    "/assets/",
    "/scripts/",
    "/plugins/",
    "/packages/",
    "/data/",
)

LOW_SIGNAL_DIR_HINTS = (
    "/docs/",
    "/doc/",
    "/examples/",
    "/example/",
    "/samples/",
    "/sample/",
    "/benchmarks/",
    "/benchmark/",
    "/tests/",
    "/test/",
)

DOMAIN_CODE_EXTENSIONS = {
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
    ".cc",
    ".cxx",
    ".proto",
    ".gd",
    ".shader",
    ".asmdef",
    ".uxml",
}

TOOLING_TERMS = {
    "tool",
    "tools",
    "analyzer",
    "analysis",
    "script fixer",
    "migration",
    "migrations",
    "sync",
    "profile",
}

ARCHITECTURE_TERMS = {
    "revscriptsys",
    "xml",
    "register",
    "registro",
    "opcode",
    "reload",
    "startup",
    "loadscripts",
    "loadfromxml",
    "mainloader",
    "script systems",
    "callback",
    "hook",
    "runtime",
    "unity",
    "assets",
}

CLASSIC_SCRIPT_TERMS = {
    "xml",
    "classic",
    "legacy",
    "bind",
    "binding",
    "callback",
    "script",
    "actions.xml",
    "talkactions.xml",
    "movements.xml",
    "spells.xml",
    "creaturescripts.xml",
    "globalevents.xml",
}

RUNTIME_SCRIPT_TERMS = {
    "revscripts",
    "revscriptsys",
    "register",
    ":register",
    "onuse",
    "onsay",
    "onthink",
    "onlogin",
    "onlogout",
    "onstepin",
    "onstepout",
    "oncastspell",
    "data/scripts",
    "assets/scripts",
}

ACTION_XML_TERMS = {
    "actions.xml",
    "action xml",
    "data/actions",
    "data/actions/actions.xml",
    "data/actions/scripts",
    "itemid",
    "actionid",
    "uniqueid",
    "fromid",
    "toid",
    "fromaid",
    "toaid",
    "fromuid",
    "touid",
    "reload_type_actions",
}

ACTION_REVSCRIPTS_TERMS = {
    "revscripts",
    "revscriptsys",
    "action()",
    ":register",
    ":register()",
    ":id(",
    ":aid(",
    ":uid(",
    "action:id",
    "action:aid",
    "action:uid",
    "data/scripts",
    "allowfaruse",
}

ACTION_BIND_TERMS = {
    "onuse",
    "bind",
    "registro",
    "register",
    "duplicidade",
    "duplicado",
    "colisao",
    "conflito",
    "ordem de resolucao",
    "ordem de resolução",
    "unique id",
    "action id",
    "item id",
    "loadscriptsystems",
    "scriptingmanager::loadscriptsystems",
    "g_actions->loadfromxml",
}

DEPENDENCY_NOISE_PREFIXES = (
    "symbol:",
    "app.",
    "urllib.",
    "xml.etree",
    "gdb.",
)

DEPENDENCY_NOISE_EXACT = {
    "app",
    "argparse",
    "dataclasses",
    "os",
    "re",
    "json",
    "math",
    "datetime",
    "typing",
    "collections",
    "pathlib",
    "requests",
    "httpx",
    "std",
    "threading",
    "time",
    "traceback",
    "copy",
    "csv",
    "io",
    "struct",
    "deadline_timer",
    "glob",
    "io_service",
    "key",
    "pil",
}

DEPENDENCY_FILE_PREFIXES = (
    "src/",
    "app/",
    "data/",
    "assets/",
    "scripts/",
    "plugins/",
    "packages/",
    "tools/",
)


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
    semantic_score: float = 0.0

    @property
    def blended_relevance_score(self) -> float:
        if self.semantic_score > 0.0:
            blended = self.relevance_score * 0.45 + self.semantic_score * 0.55
            return max(0.0, min(1.0, round(blended, 4)))
        return self.relevance_score

    @property
    def final_score(self) -> float:
        weighted = (
            self.blended_relevance_score * 0.50
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
        embedding_client: object | None = None,
    ) -> None:
        self.memory_repository = memory_repository
        self.project_artifacts_root = project_artifacts_root
        self.max_chars = max_chars
        self.knowledge_compiler = knowledge_compiler
        self.embedding_client = embedding_client
        self.graph_engine = KnowledgeGraphEngine(project_artifacts_root=self.project_artifacts_root)

    def assemble(self, envelope: RequestEnvelope) -> tuple[ContextPacket, RetrievalResult]:
        started = perf_counter()
        intent_terms = self._intent_terms(envelope.prompt)
        user_intent = self._detect_user_intent(envelope.prompt)
        workspace_id, plain_project_id = split_scoped_project_id(
            envelope.project_id,
            fallback_workspace_id=envelope.workspace_id,
        )

        memories = self.memory_repository.search(
            project_id=envelope.project_id,
            user_id=envelope.user_id,
            query=envelope.prompt,
            limit=10,
        )

        candidates: list[RetrievalCandidate] = []
        candidates.extend(self._memory_candidates(memories, intent_terms))
        candidates.extend(
            self._knowledge_candidates(
                envelope.prompt,
                intent_terms,
                workspace_id=workspace_id,
                project_id=plain_project_id,
            )
        )

        artifact_candidates, direct_dependencies, recent_changes = self._artifact_candidates(
            project_id=plain_project_id,
            workspace_id=workspace_id,
            intent_terms=intent_terms,
            prompt=envelope.prompt,
        )
        candidates.extend(artifact_candidates)

        semantic_info = self._apply_semantic_scores(
            prompt=envelope.prompt,
            candidates=candidates,
        )

        graph_expansion = self.graph_engine.expand(
            project_id=plain_project_id,
            workspace_id=workspace_id,
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
                    "semantic_score": item.semantic_score,
                    "blended_relevance_score": item.blended_relevance_score,
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
                    "semantic_score": item.semantic_score,
                    "blended_relevance_score": item.blended_relevance_score,
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
        sanitized_dependencies = self._sanitize_dependencies(dependencies)

        relevant_systems = set(str(item) for item in graph_expansion.get("relevant_systems", []))
        relevant_systems.update(self._derive_systems_from_sources(selected))
        sanitized_systems = self._sanitize_relevant_systems(relevant_systems)

        architecture_notes = [str(item) for item in graph_expansion.get("architecture_notes", [])]
        architecture_notes.append(f"hot_context={len(hot_context)}")
        architecture_notes.append(f"cold_knowledge={len(cold_knowledge)}")
        if semantic_info.get("enabled"):
            architecture_notes.append(
                f"semantic_retrieval={semantic_info.get('status')}:{semantic_info.get('ranked_candidates', 0)}"
            )

        risks = self._build_risk_analysis(selected=selected, dropped=dropped)
        compression_payload = {
            "selected_count": len(selected),
            "dropped_count": len(dropped),
            "max_chars": self.max_chars,
            "used_chars": sum(len(item.content) for item in selected),
        }

        assembled = {
            "query": envelope.prompt,
            "workspace_id": workspace_id,
            "project_id": plain_project_id,
            "user_intent": user_intent,
            "relevant_systems": sanitized_systems,
            "dependencies": sanitized_dependencies,
            "architecture_notes": architecture_notes,
            "recent_changes": recent_changes[:25],
            "risks": risks,
            "context_packet": context_packet,
            "hot_context": hot_context,
            "cold_knowledge": cold_knowledge,
            "compression": compression_payload,
            "semantic_retrieval": semantic_info,
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

    def _apply_semantic_scores(
        self,
        *,
        prompt: str,
        candidates: list[RetrievalCandidate],
    ) -> dict[str, object]:
        if self.embedding_client is None or not candidates:
            return {
                "enabled": False,
                "status": "disabled",
                "ranked_candidates": 0,
            }

        semantic_candidates = sorted(
            candidates,
            key=lambda item: (item.relevance_score, item.importance_score, item.freshness_score),
            reverse=True,
        )[:40]

        texts = [prompt]
        texts.extend(self._embedding_text_for_candidate(item) for item in semantic_candidates)

        try:
            vectors = self.embedding_client.embed_texts(texts)
        except Exception as exc:
            return {
                "enabled": True,
                "status": "unavailable",
                "ranked_candidates": 0,
                "reason": str(exc),
            }

        if len(vectors) != len(texts):
            return {
                "enabled": True,
                "status": "degraded",
                "ranked_candidates": 0,
                "reason": "vector_count_mismatch",
            }

        query_vector = vectors[0]
        ranked = 0

        for candidate, vector in zip(semantic_candidates, vectors[1:], strict=False):
            semantic_score = self._cosine_similarity(query_vector, vector)
            if semantic_score > 0.0:
                candidate.semantic_score = semantic_score
                ranked += 1

        return {
            "enabled": True,
            "status": "ok",
            "ranked_candidates": ranked,
            "considered_candidates": len(semantic_candidates),
            "total_candidates": len(candidates),
        }

    def _knowledge_candidates(
        self,
        prompt: str,
        terms: set[str],
        *,
        workspace_id: str,
        project_id: str,
    ) -> list[RetrievalCandidate]:
        if self.knowledge_compiler is None:
            return []

        candidates: list[RetrievalCandidate] = []
        try:
            nodes = self.knowledge_compiler.search(prompt, limit=8)
        except Exception:
            return []

        workspace_prefix = f".brasa/workspaces/{workspace_id}/{project_id}/".lower()

        for node in nodes:
            summary = (node.summary or "").strip()
            if not summary:
                continue

            source_path = str(node.source_path or "").replace("\\", "/")
            if not source_path:
                continue

            if self._is_noise_path(source_path, include_app_internal=True):
                continue

            # For workspace-scoped domain runs, prefer knowledge generated from that
            # exact workspace project and suppress unrelated repository internals.
            if workspace_id != "brasa_ai_workspace":
                if not source_path.lower().startswith(workspace_prefix):
                    continue

            metadata_text = " ".join(
                [
                    node.title,
                    source_path,
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
        workspace_id: str | None,
        intent_terms: set[str],
        prompt: str | None = None,
    ) -> tuple[list[RetrievalCandidate], set[str], list[str]]:
        project_root = resolve_project_root(
            artifacts_base_root=self.project_artifacts_root,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        metadata_root = project_root / "metadata" / "files"
        summary_root = project_root / "summaries" / "files"

        if not metadata_root.exists():
            return [], set(), []

        prompt_lower = (prompt or "").strip().lower()

        candidates: list[RetrievalCandidate] = []
        fallback_candidates: list[RetrievalCandidate] = []
        expanded_dependencies: set[str] = set()
        recent_changes: list[str] = []

        for metadata_path in metadata_root.rglob("*.meta.json"):
            metadata = self._load_json(metadata_path)
            if not metadata:
                continue

            file_path = str(metadata.get("path") or "").strip()
            if not file_path:
                continue

            if self._is_noise_path(file_path, include_app_internal=False):
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
            modified_at = self._parse_dt(str(metadata.get("modified_at", "")))
            freshness = self._freshness_score(modified_at)
            confidence = float(metadata.get("confidence", 0.78))
            confidence = max(0.3, min(1.0, confidence))
            importance = 0.50 + min(0.45, len(direct_deps) * 0.04)
            importance += self._domain_path_bonus(file_path=file_path, prompt_lower=prompt_lower)
            importance = max(0.05, min(1.0, importance))

            candidate = RetrievalCandidate(
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

            if relevance <= 0.05:
                if self._is_domain_source_path(file_path):
                    fallback_candidates.append(candidate)
                continue

            expanded_dependencies.update(direct_deps)
            if freshness >= 0.85:
                recent_changes.append(file_path)

            candidates.append(candidate)

        if not candidates and fallback_candidates:
            fallback_candidates.sort(
                key=lambda item: (item.importance_score, item.freshness_score, len(item.dependencies)),
                reverse=True,
            )
            selected_fallback = fallback_candidates[:24]
            candidates.extend(selected_fallback)
            expanded_dependencies.update(dep for item in selected_fallback for dep in item.dependencies)
            recent_changes.extend(item.source.removeprefix("artifact:file:") for item in selected_fallback if item.is_hot)

        return candidates, expanded_dependencies, sorted(set(recent_changes))

    def _is_noise_path(self, value: str, *, include_app_internal: bool) -> bool:
        normalized = "/" + str(value).replace("\\", "/").strip("/").lower() + "/"

        if include_app_internal and normalized.startswith("/app/"):
            return True

        return any(segment in normalized for segment in NOISE_PATH_SEGMENTS)

    def _is_domain_source_path(self, value: str) -> bool:
        normalized = "/" + str(value).replace("\\", "/").strip("/").lower() + "/"
        extension = self._path_extension(normalized)

        if "/data/tools/" in normalized or normalized.startswith("/tools/"):
            return False
        if any(segment in normalized for segment in LOW_SIGNAL_DIR_HINTS):
            return False

        if any(segment in normalized for segment in GENERIC_CODE_DIR_HINTS):
            if extension:
                return extension in DOMAIN_CODE_EXTENSIONS
            return normalized.startswith("/src/") or normalized.startswith("/assets/")

        return extension in DOMAIN_CODE_EXTENSIONS

    def _domain_path_bonus(self, *, file_path: str, prompt_lower: str) -> float:
        normalized = "/" + str(file_path).replace("\\", "/").strip("/").lower() + "/"
        extension = self._path_extension(normalized)
        bonus = 0.0

        classic_focus = self._contains_any(prompt_lower, CLASSIC_SCRIPT_TERMS)
        runtime_focus = self._contains_any(prompt_lower, RUNTIME_SCRIPT_TERMS)
        action_focus = self._contains_any(prompt_lower, ACTION_XML_TERMS | ACTION_REVSCRIPTS_TERMS | ACTION_BIND_TERMS)
        revscripts_focus = self._contains_any(prompt_lower, ACTION_REVSCRIPTS_TERMS)
        xml_focus = "xml" in prompt_lower or self._contains_any(prompt_lower, ACTION_XML_TERMS | CLASSIC_SCRIPT_TERMS)
        architecture_focus = any(term in prompt_lower for term in ARCHITECTURE_TERMS) or classic_focus or runtime_focus

        if "/src/" in normalized:
            bonus += 0.16
        if "/app/" in normalized:
            bonus += 0.12
        if "/assets/" in normalized:
            bonus += 0.15
        if "/scripts/" in normalized:
            bonus += 0.10
        if "/data/scripts/" in normalized:
            bonus += 0.20
        if any(segment in normalized for segment in MMO_XML_DIRS):
            bonus += 0.14
        if extension in {".cs", ".cpp", ".h", ".hpp", ".lua", ".ts", ".tsx", ".js", ".py"}:
            bonus += 0.05

        if any(segment in normalized for segment in LOW_SIGNAL_DIR_HINTS):
            if not any(term in prompt_lower for term in TOOLING_TERMS):
                bonus -= 0.12

        if "/data/tools/" in normalized or normalized.startswith("/tools/"):
            if not any(term in prompt_lower for term in TOOLING_TERMS):
                bonus -= 0.22

        if architecture_focus:
            if any(hint in normalized for hint in MMO_CORE_SRC_HINTS):
                bonus += 0.24
            if "/scripts/" in normalized or "/assets/" in normalized:
                bonus += 0.12
            if any(segment in normalized for segment in MMO_XML_DIRS):
                bonus += 0.08

        if classic_focus:
            if extension == ".xml":
                bonus += 0.12
            if any(segment in normalized for segment in MMO_XML_DIRS):
                bonus += 0.10

        if runtime_focus:
            if "/scripts/" in normalized and extension in {".lua", ".cs", ".ts", ".tsx", ".js", ".py"}:
                bonus += 0.12

        if action_focus:
            if "/data/actions/actions.xml/" in normalized:
                bonus += 0.34
            if "/data/actions/scripts/" in normalized:
                bonus += 0.24
            if "/data/scripts/" in normalized:
                bonus += 0.20
            if "/src/actions" in normalized:
                bonus += 0.28
            if "/src/luascript" in normalized:
                bonus += 0.26
            if "/src/baseevents" in normalized:
                bonus += 0.20
            if "/src/scriptmanager" in normalized:
                bonus += 0.20
            if "/src/script" in normalized:
                bonus += 0.16

        if xml_focus and normalized.endswith(".xml/"):
            bonus += 0.08

        if revscripts_focus and "/data/scripts/" in normalized:
            bonus += 0.12

        if "npc" in prompt_lower and ("/data/scripts/" in normalized or "/src/npc" in normalized):
            bonus += 0.08
        if "spell" in prompt_lower and ("/data/spells/" in normalized or "/src/spells" in normalized):
            bonus += 0.08
        if "quest" in prompt_lower and "/src/quests" in normalized:
            bonus += 0.10

        return bonus

    def _contains_any(self, value: str, terms: set[str]) -> bool:
        lower = value.lower()
        return any(term in lower for term in terms)

    def _path_extension(self, normalized_with_slashes: str) -> str:
        normalized = normalized_with_slashes.strip("/")
        if not normalized:
            return ""
        return Path(normalized).suffix.lower()

    def _sanitize_dependencies(self, dependencies: set[str]) -> list[str]:
        curated: list[str] = []

        for item in sorted(str(value).strip() for value in dependencies if str(value).strip()):
            lower = item.lower()
            if lower.startswith(DEPENDENCY_NOISE_PREFIXES):
                continue
            if lower in DEPENDENCY_NOISE_EXACT:
                continue
            if lower.startswith("file:"):
                normalized_file = lower.removeprefix("file:").replace("\\", "/")
                if not any(normalized_file.startswith(prefix) for prefix in DEPENDENCY_FILE_PREFIXES):
                    continue
            if lower.startswith("__"):
                continue
            if "." in lower and not lower.startswith("file:"):
                continue
            if len(item) < 3:
                continue
            curated.append(item)

        return curated[:180]

    def _sanitize_relevant_systems(self, systems: set[str]) -> list[str]:
        result: set[str] = set()

        for raw in systems:
            value = str(raw).strip()
            if not value:
                continue

            normalized = value.replace("\\", "/").strip()
            if normalized.startswith("file:"):
                normalized = normalized.split(":", maxsplit=1)[1]

            head = normalized.split("/", maxsplit=1)[0].lower()
            if head == "data":
                parts = normalized.split("/")
                if len(parts) >= 2 and parts[1]:
                    second = parts[1].lower()
                    if second not in {
                        "tools",
                        "build",
                        "cmake",
                        "metadata",
                        "tmp",
                        "temp",
                        "cache",
                    }:
                        result.add(f"data/{second}")
                continue

            if head in {"tools", "build", "cmake", "vcpkg_installed", "metadata"}:
                continue

            if normalized.lower().startswith(".brasa/workspaces/"):
                parts = normalized.split("/")
                if len(parts) >= 5:
                    head = parts[4]
                    if head:
                        result.add(head)
                continue

            result.add(normalized)

        return sorted(item for item in result if item)[:40]

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

    def _embedding_text_for_candidate(self, candidate: RetrievalCandidate) -> str:
        dependency_text = ", ".join(candidate.dependencies[:20])
        content = candidate.content[:900].replace("\n", " ").strip()
        return f"source={candidate.source};deps={dependency_text};content={content}"

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0

        dot = 0.0
        left_norm = 0.0
        right_norm = 0.0
        for left_item, right_item in zip(left, right, strict=False):
            dot += left_item * right_item
            left_norm += left_item * left_item
            right_norm += right_item * right_item

        if left_norm <= 0.0 or right_norm <= 0.0:
            return 0.0

        cosine = dot / (math.sqrt(left_norm) * math.sqrt(right_norm))
        normalized = (cosine + 1.0) / 2.0
        return max(0.0, min(1.0, round(normalized, 4)))

    def _derive_systems_from_sources(self, selected: list[RetrievalCandidate]) -> set[str]:
        systems: set[str] = set()
        for item in selected:
            source = item.source
            if source.startswith("artifact:file:"):
                relative = source.removeprefix("artifact:file:")
                if "/" in relative:
                    parts = relative.split("/")
                    head = parts[0]
                    if head == "data" and len(parts) > 1:
                        systems.add(f"data/{parts[1]}")
                    else:
                        systems.add(head)
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
