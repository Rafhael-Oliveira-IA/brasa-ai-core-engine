from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.models import ProjectProfile, ScannedFile

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
}

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".brasa",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".lua": "lua",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".cs": "csharp",
    ".java": "java",
    ".kt": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".md": "markdown",
    ".json": "json",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".txt": "text",
}


class ProjectScanner:
    def __init__(
        self,
        *,
        include_extensions: set[str] | None = None,
        max_file_bytes: int = 300_000,
    ) -> None:
        self.include_extensions = include_extensions or set(DEFAULT_EXTENSIONS)
        self.max_file_bytes = max_file_bytes

    def scan(self, project_path: Path) -> tuple[ProjectProfile, list[ScannedFile]]:
        profile = self._detect_project_profile(project_path)
        files: list[ScannedFile] = []

        for file_path in sorted(project_path.rglob("*")):
            if not file_path.is_file():
                continue
            if self._is_excluded(project_path, file_path):
                continue
            if file_path.suffix.lower() not in self.include_extensions:
                continue

            stat = file_path.stat()
            max_allowed_size = self.max_file_bytes
            if file_path.suffix.lower() in {".xml", ".lua"}:
                max_allowed_size = max(max_allowed_size, 2_000_000)

            if stat.st_size > max_allowed_size:
                continue

            rel_path = file_path.relative_to(project_path).as_posix()
            folder = Path(rel_path).parent.as_posix()
            if folder == ".":
                folder = ""

            files.append(
                ScannedFile(
                    path=rel_path,
                    hash=self._sha256(file_path),
                    language=self._detect_language(file_path.suffix),
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    size=stat.st_size,
                    module=rel_path.split("/")[0] if "/" in rel_path else "root",
                    folder=folder,
                )
            )

        return profile, files

    def _detect_project_profile(self, project_path: Path) -> ProjectProfile:
        project_name = project_path.name
        engine = "generic"
        project_type = "mixed"

        if (project_path / "Assets").exists() and (project_path / "ProjectSettings").exists():
            engine = "unity"
            project_type = "game"
        elif any(project_path.glob("*.uproject")):
            engine = "unreal"
            project_type = "game"
        elif (project_path / "package.json").exists():
            engine = "node"
            project_type = "service"
        elif (project_path / "requirements.txt").exists() or (project_path / "pyproject.toml").exists():
            engine = "python"
            project_type = "service"

        return ProjectProfile(project_name=project_name, project_type=project_type, engine=engine)

    def _detect_language(self, suffix: str) -> str:
        return LANGUAGE_BY_EXTENSION.get(suffix.lower(), "text")

    def _sha256(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _is_excluded(self, project_root: Path, file_path: Path) -> bool:
        relative = file_path.relative_to(project_root)
        return any(part in EXCLUDED_DIRS for part in relative.parts)
