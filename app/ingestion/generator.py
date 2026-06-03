from __future__ import annotations

import re
from pathlib import Path

from app.ingestion.models import ScannedFile


class DependencyTracker:
    def extract(self, content: str) -> list[str]:
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


class KnowledgeGenerator:
    def __init__(self) -> None:
        self.dependency_tracker = DependencyTracker()

    def summarize_file(self, scanned_file: ScannedFile, content: str) -> tuple[str, dict[str, object]]:
        symbols = self._extract_symbols(content)
        dependencies = self.dependency_tracker.extract(content)

        title = Path(scanned_file.path).stem or Path(scanned_file.path).name
        purpose = self._infer_purpose(content, title)

        lines = [
            f"# {title}",
            "",
            "Purpose:",
            f"{purpose}",
            "",
            "Dependencies:",
        ]

        if dependencies:
            lines.extend(f"- {item}" for item in dependencies)
        else:
            lines.append("- none")

        lines.append("")
        lines.append("Core Symbols:")
        if symbols:
            lines.extend(f"- {symbol}" for symbol in symbols[:10])
        else:
            lines.append("- none")

        summary = "\n".join(lines).strip() + "\n"

        metadata = {
            "path": scanned_file.path,
            "hash": scanned_file.hash,
            "language": scanned_file.language,
            "modified_at": scanned_file.modified_at.isoformat(),
            "size": scanned_file.size,
            "module": scanned_file.module,
            "folder": scanned_file.folder,
            "dependencies": dependencies,
            "symbols": symbols,
        }

        return summary, metadata

    def _extract_symbols(self, content: str) -> list[str]:
        patterns = [
            r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*async\s+def\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface|record)\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)",
        ]

        symbols: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, content, flags=re.MULTILINE):
                if match not in symbols:
                    symbols.append(match)

        return symbols[:20]

    def _infer_purpose(self, content: str, title: str) -> str:
        lower = content.lower()
        if "inventory" in lower:
            return "Handles inventory-related workflows and data boundaries."
        if "router" in lower or "endpoint" in lower:
            return "Exposes API flow and request orchestration responsibilities."
        if "repository" in lower or "sqlite" in lower:
            return "Provides persistence logic and storage abstractions."
        return f"Implements the main responsibilities of {title}."
