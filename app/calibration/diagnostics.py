from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.calibration.taxonomy import RetrievalFailureType
from app.feedback.repository import CognitiveFeedbackRepository


class CognitiveDiagnosticsEngine:
    def __init__(
        self,
        *,
        trace_file: Path,
        output_dir: Path,
        usage_dataset_dir: Path,
        feedback_repository: CognitiveFeedbackRepository | None = None,
    ) -> None:
        self.trace_file = trace_file
        self.output_dir = output_dir
        self.usage_dataset_dir = usage_dataset_dir
        self.feedback_repository = feedback_repository
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, object]:
        failure_counts: dict[str, int] = {item.value: 0 for item in RetrievalFailureType}
        notes: list[str] = []

        usage_records = self._latest_usage_records()
        for record in usage_records:
            self._accumulate_usage_failures(record=record, counts=failure_counts)

        feedback_summary = None
        if self.feedback_repository is not None:
            feedback_summary = self.feedback_repository.summarize(project_id=project_id, user_id=user_id, limit=1000)
            self._accumulate_feedback_failures(summary=feedback_summary, counts=failure_counts)

        recommendations = self._recommendations(failure_counts)
        if not recommendations:
            recommendations = ["No major retrieval failure cluster detected in this cycle."]

        if feedback_summary is not None and int(feedback_summary.get("total", 0)) > 0:
            notes.append(f"feedback_entries={feedback_summary.get('total', 0)}")

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "user_id": user_id,
            "failure_counts": failure_counts,
            "recommendations": recommendations,
            "notes": notes,
        }

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_file = self.output_dir / f"diagnostics-{stamp}.json"
        output_file.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        report["report_file"] = output_file.as_posix()

        return report

    def _latest_usage_records(self) -> list[dict]:
        if not self.usage_dataset_dir.exists():
            return []

        candidates = sorted(self.usage_dataset_dir.glob("cognitive-usage-*.jsonl"))
        if not candidates:
            return []

        target = candidates[-1]
        records: list[dict] = []
        for line in target.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)

        return records

    def _accumulate_usage_failures(self, *, record: dict, counts: dict[str, int]) -> None:
        selected_count = int(record.get("selected_count", 0))
        dropped = int(self._nested_number(record, "compression", "dropped_count"))
        xml_focus = bool(record.get("xml_focus", False))
        xml_selected = bool(record.get("xml_selected", False))

        relevant_systems = record.get("relevant_systems", [])
        if not isinstance(relevant_systems, list):
            relevant_systems = []

        dependencies = record.get("dependencies", [])
        if not isinstance(dependencies, list):
            dependencies = []

        risks = record.get("risks", [])
        if not isinstance(risks, list):
            risks = []

        if xml_focus and not xml_selected:
            counts[RetrievalFailureType.XML_MISSING.value] += 1

        if selected_count == 0:
            counts[RetrievalFailureType.SEMANTIC_MISDIRECTION.value] += 1
            counts[RetrievalFailureType.GRAPH_UNDEREXPANSION.value] += 1

        if dropped >= 1800 and selected_count <= 8:
            counts[RetrievalFailureType.COMPRESSION_LOSS.value] += 1

        if any("stale" in str(item).lower() for item in risks):
            counts[RetrievalFailureType.STALE_SUMMARY.value] += 1

        if len(relevant_systems) >= 12:
            counts[RetrievalFailureType.GRAPH_OVEREXPANSION.value] += 1

        if len(relevant_systems) <= 1 and selected_count >= 5:
            counts[RetrievalFailureType.WRONG_MODULE.value] += 1

        noisy_dep_hits = sum(1 for item in dependencies if str(item).lower().startswith("classic-"))
        if noisy_dep_hits >= 25:
            counts[RetrievalFailureType.DEPENDENCY_NOISE.value] += 1

        top_sources = record.get("top_sources", [])
        if isinstance(top_sources, list):
            talkaction_bias = sum(1 for item in top_sources[:6] if "talkactions" in str(item).lower())
            if talkaction_bias >= 4 and xml_focus:
                counts[RetrievalFailureType.RANKING_COLLISION.value] += 1

    def _accumulate_feedback_failures(self, *, summary: dict, counts: dict[str, int]) -> None:
        issue_counts = summary.get("issue_counts", {}) if isinstance(summary, dict) else {}
        if not isinstance(issue_counts, dict):
            return

        counts[RetrievalFailureType.XML_MISSING.value] += int(issue_counts.get("xml_missing", 0))
        counts[RetrievalFailureType.COMPRESSION_LOSS.value] += int(issue_counts.get("compression_bad", 0))
        counts[RetrievalFailureType.WRONG_MODULE.value] += int(issue_counts.get("retrieval_incorrect", 0))
        counts[RetrievalFailureType.SEMANTIC_MISDIRECTION.value] += int(issue_counts.get("hallucination", 0))
        counts[RetrievalFailureType.GRAPH_UNDEREXPANSION.value] += int(issue_counts.get("architectural_loss", 0))

    def _recommendations(self, counts: dict[str, int]) -> list[str]:
        recommendations: list[str] = []

        if counts[RetrievalFailureType.XML_MISSING.value] > 0:
            recommendations.append(
                "Increase XML profile boost and enforce exact XML filename preservation in selected context."
            )
        if counts[RetrievalFailureType.RANKING_COLLISION.value] > 0:
            recommendations.append(
                "Reduce cross-module script collisions by adding profile-aware penalties for unrelated modules."
            )
        if counts[RetrievalFailureType.COMPRESSION_LOSS.value] > 0:
            recommendations.append(
                "Reserve budget for architectural anchor files and raise clipping quota for top-ranked items."
            )
        if counts[RetrievalFailureType.DEPENDENCY_NOISE.value] > 0:
            recommendations.append(
                "Filter repetitive classic-* dependency markers from retrieval dependency summaries."
            )
        if counts[RetrievalFailureType.GRAPH_UNDEREXPANSION.value] > 0:
            recommendations.append(
                "Boost graph expansion depth for architecture-style queries with low selected context count."
            )

        return recommendations

    def _nested_number(self, value: dict, *path: str) -> int:
        current: object = value
        for part in path:
            if not isinstance(current, dict):
                return 0
            current = current.get(part)
        try:
            return int(current)
        except Exception:
            return 0
