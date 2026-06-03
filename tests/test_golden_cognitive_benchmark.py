from __future__ import annotations

import json
from pathlib import Path

import pytest


def load_golden_config() -> dict:
    path = Path(__file__).parent / "golden" / "golden_cognitive_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


def gather_file_paths(project_path: Path) -> list[str]:
    return [
        item.relative_to(project_path).as_posix().lower()
        for item in project_path.rglob("*")
        if item.is_file()
    ]


def extension_set(file_paths: list[str]) -> set[str]:
    result: set[str] = set()
    for rel_path in file_paths:
        suffix = Path(rel_path).suffix.lower()
        if suffix:
            result.add(suffix)
    return result


def test_golden_cognitive_profiles_match_real_projects() -> None:
    config = load_golden_config()
    projects = config.get("projects", [])
    min_keyword_hit_ratio = float(config.get("min_keyword_hit_ratio", 1.0))

    missing_paths = [
        item.get("project_path", "")
        for item in projects
        if not Path(str(item.get("project_path", ""))).exists()
    ]
    if missing_paths:
        pytest.skip("Golden benchmark skipped because project paths are missing: " + ", ".join(missing_paths))

    for project in projects:
        workspace_id = str(project.get("workspace_id", "")).strip()
        project_path = Path(str(project.get("project_path", "")))

        file_paths = gather_file_paths(project_path)
        assert file_paths, f"Workspace {workspace_id} has no files to validate."

        ext_set = extension_set(file_paths)
        expected_extensions = [str(item).lower() for item in project.get("file_extensions", [])]
        missing_extensions = [ext for ext in expected_extensions if ext not in ext_set]

        assert not missing_extensions, (
            f"Workspace {workspace_id} is missing expected extensions: {missing_extensions}"
        )

        joined_paths = "\n".join(file_paths)
        keywords = [str(item).lower() for item in project.get("keywords", [])]

        keyword_hits = {
            keyword: joined_paths.count(keyword)
            for keyword in keywords
        }
        matched_keywords = [key for key, count in keyword_hits.items() if count > 0]
        hit_ratio = len(matched_keywords) / max(1, len(keywords))

        assert hit_ratio >= min_keyword_hit_ratio, (
            f"Workspace {workspace_id} keyword hit ratio {hit_ratio:.2f} below minimum "
            f"{min_keyword_hit_ratio:.2f}; missing={sorted([k for k, v in keyword_hits.items() if v == 0])}"
        )
