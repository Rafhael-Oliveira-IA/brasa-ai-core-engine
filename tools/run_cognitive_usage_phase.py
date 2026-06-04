from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts import RequestEnvelope
from app.memory.repository import MemoryRepository
from app.retrieval import ContextRetrievalEngine
from app.workspace import scoped_project_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_xml_focused(prompt: str) -> bool:
    lower = prompt.lower()
    return ".xml" in lower or " xml" in lower or lower.startswith("xml")


def run(query_file: Path, output_dir: Path) -> tuple[Path, Path]:
    payload = json.loads(query_file.read_text(encoding="utf-8"))
    queries = payload.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError("query file must contain a list in queries")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    trace_jsonl = output_dir / f"cognitive-usage-{stamp}.jsonl"
    summary_json = output_dir / f"cognitive-usage-{stamp}.summary.json"

    memory_repository = MemoryRepository(ROOT / "data" / "memory.db")
    retrieval_engine = ContextRetrievalEngine(
        memory_repository=memory_repository,
        project_artifacts_root=ROOT / ".brasa",
    )

    records: list[dict] = []
    for index, item in enumerate(queries, start=1):
        if not isinstance(item, dict):
            continue

        workspace_id = str(item.get("workspace_id", "brasa_ai_workspace"))
        project_id = str(item.get("project_id", ""))
        user_id = str(item.get("user_id", "cognitive-usage"))
        domain = str(item.get("domain", "general"))
        prompt = str(item.get("prompt", "")).strip()
        if not project_id or not prompt:
            continue

        envelope = RequestEnvelope(
            workspace_id=workspace_id,
            project_id=scoped_project_id(project_id=project_id, workspace_id=workspace_id),
            user_id=user_id,
            prompt=prompt,
        )
        status_code = 200

        record: dict[str, object] = {
            "index": index,
            "created_at": _utc_now_iso(),
            "workspace_id": workspace_id,
            "project_id": project_id,
            "domain": domain,
            "prompt": prompt,
            "status_code": status_code,
        }

        try:
            packet, retrieval = retrieval_engine.assemble(envelope)
            snippets = packet.snippets
            sources = [item.source for item in snippets]
            assembled = retrieval.assembled
            compression = assembled.get("compression", {})

            record.update(
                {
                    "top_sources": sources[:12],
                    "selected_count": len(sources),
                    "relevant_systems": assembled.get("relevant_systems", []),
                    "dependencies": assembled.get("dependencies", [])[:40],
                    "compression": compression,
                    "risks": assembled.get("risks", []),
                    "xml_focus": _is_xml_focused(prompt),
                    "xml_selected": any(source.lower().endswith(".xml") for source in sources),
                }
            )
        except Exception as exc:  # pragma: no cover
            status_code = 500
            record["status_code"] = status_code
            record["error"] = str(exc)

        records.append(record)

    with trace_jsonl.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=True) + "\n")

    total = len(records)
    successful = sum(1 for item in records if int(item.get("status_code", 0)) == 200)
    xml_focused = [item for item in records if bool(item.get("xml_focus", False))]
    xml_focus_count = len(xml_focused)
    xml_focus_with_xml = sum(1 for item in xml_focused if bool(item.get("xml_selected", False)))

    summary = {
        "generated_at": _utc_now_iso(),
        "query_file": query_file.as_posix(),
        "output_trace": trace_jsonl.as_posix(),
        "total_queries": total,
        "successful_queries": successful,
        "failed_queries": max(0, total - successful),
        "xml_focused_queries": xml_focus_count,
        "xml_focused_with_xml_selected": xml_focus_with_xml,
        "domains": sorted({str(item.get("domain", "general")) for item in records}),
    }

    summary_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
    return trace_jsonl, summary_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily cognitive usage queries and save dataset traces.")
    parser.add_argument(
        "--query-file",
        type=Path,
        default=Path("tools") / "cognitive_usage_daily_queries.json",
        help="Path to query JSON file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data") / "evaluations" / "cognitive_usage",
        help="Directory where JSONL and summary outputs are written",
    )
    args = parser.parse_args()

    trace_jsonl, summary_json = run(query_file=args.query_file, output_dir=args.output_dir)
    print(f"cognitive usage trace: {trace_jsonl.as_posix()}")
    print(f"cognitive usage summary: {summary_json.as_posix()}")


if __name__ == "__main__":
    main()
