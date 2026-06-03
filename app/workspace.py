from __future__ import annotations

from pathlib import Path


DEFAULT_WORKSPACE_ID = "brasa_ai_workspace"


def normalize_workspace_id(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return DEFAULT_WORKSPACE_ID

    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw)
    return safe or DEFAULT_WORKSPACE_ID


def scoped_project_id(*, project_id: str, workspace_id: str | None) -> str:
    workspace = normalize_workspace_id(workspace_id)
    plain_project = (project_id or "").strip()
    if not plain_project:
        return f"{workspace}::default"
    if "::" in plain_project:
        return plain_project
    return f"{workspace}::{plain_project}"


def split_scoped_project_id(
    value: str,
    *,
    fallback_workspace_id: str | None = None,
) -> tuple[str, str]:
    text = (value or "").strip()
    if "::" in text:
        workspace, project = text.split("::", maxsplit=1)
        return normalize_workspace_id(workspace), project or "default"

    return normalize_workspace_id(fallback_workspace_id), text or "default"


def project_root_candidates(
    *,
    artifacts_base_root: Path,
    project_id: str,
    workspace_id: str | None,
) -> list[Path]:
    workspace = normalize_workspace_id(workspace_id)
    candidates = [
        artifacts_base_root / "workspaces" / workspace / project_id,
        artifacts_base_root / "projects" / project_id,
        artifacts_base_root / project_id,
    ]

    unique: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        key = item.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique


def resolve_project_root(
    *,
    artifacts_base_root: Path,
    project_id: str,
    workspace_id: str | None,
) -> Path:
    candidates = project_root_candidates(
        artifacts_base_root=artifacts_base_root,
        project_id=project_id,
        workspace_id=workspace_id,
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]
