from __future__ import annotations

import re
from pathlib import Path

from app.ingestion.models import ScannedFile


class DependencyTracker:
    def extract(self, content: str, *, scanned_file: ScannedFile | None = None) -> list[str]:
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

        if scanned_file is not None:
            dependencies.update(self._domain_markers(content=content, scanned_file=scanned_file))

        return sorted(dependencies)[:40]

    def _domain_markers(self, *, content: str, scanned_file: ScannedFile) -> set[str]:
        markers: set[str] = set()
        path = scanned_file.path.replace("\\", "/").lower()
        language = scanned_file.language.lower()

        if language == "xml" or path.endswith(".xml"):
            markers.update(self._xml_markers(content))

        if language == "lua" or path.endswith(".lua"):
            markers.update(self._lua_markers(content))

        if "data/actions/actions.xml" in path:
            markers.add("classic-action-bind")

        if "data/actions/scripts/" in path:
            markers.add("classic-action-script")

        if "data/scripts/" in path and "Action()" in markers:
            markers.add("revscripts-action")

        return markers

    def _xml_markers(self, content: str) -> set[str]:
        markers: set[str] = set()

        if re.search(r"<\s*action\b", content, flags=re.IGNORECASE):
            markers.add("action")

        for attribute in re.findall(
            r"\b(itemid|actionid|uniqueid|fromid|toid|fromaid|toaid|fromuid|touid|script)\s*=",
            content,
            flags=re.IGNORECASE,
        ):
            markers.add(attribute.lower())

        for script_path in re.findall(r"\bscript\s*=\s*['\"]([^'\"]+)['\"]", content, flags=re.IGNORECASE):
            normalized = script_path.strip()
            if normalized:
                markers.add(f"script:{normalized}")

        return markers

    def _lua_markers(self, content: str) -> set[str]:
        markers: set[str] = set()

        if re.search(r"\bAction\s*\(\s*\)", content):
            markers.add("Action()")
        if re.search(r":register\s*\(", content):
            markers.add(":register")
        if re.search(r":id\s*\(", content):
            markers.add(":id")
        if re.search(r":aid\s*\(", content):
            markers.add(":aid")
        if re.search(r":uid\s*\(", content):
            markers.add(":uid")
        if re.search(r":allowFarUse\s*\(", content):
            markers.add(":allowFarUse")
        if re.search(r"\bonUse\b", content):
            markers.add("onUse")

        return markers


class KnowledgeGenerator:
    def __init__(self) -> None:
        self.dependency_tracker = DependencyTracker()

    def summarize_file(self, scanned_file: ScannedFile, content: str) -> tuple[str, dict[str, object]]:
        symbols = self._extract_symbols(content)
        dependencies = self.dependency_tracker.extract(content, scanned_file=scanned_file)

        title = Path(scanned_file.path).stem or Path(scanned_file.path).name
        purpose = self._infer_purpose(scanned_file, content, title)

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
            r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Action\s*\(\s*\)",
        ]

        symbols: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, content, flags=re.MULTILINE):
                if match not in symbols:
                    symbols.append(match)

        return symbols[:20]

    def _infer_purpose(self, scanned_file: ScannedFile, content: str, title: str) -> str:
        lower = content.lower()
        path = scanned_file.path.replace("\\", "/").lower()

        if path.endswith("data/actions/actions.xml"):
            return "Registers classic Action XML binds (itemid/actionid/uniqueid/ranges) to Lua scripts."
        if "data/actions/scripts/" in path and "onuse" in lower:
            return "Implements classic Action callback logic invoked by data/actions/actions.xml bindings."
        if "data/scripts/" in path and "action()" in lower and ":register" in lower:
            return "Registers a Revscripts Action via Action() with :id/:aid/:uid and :register()."

        if "inventory" in lower:
            return "Handles inventory-related workflows and data boundaries."
        if "router" in lower or "endpoint" in lower:
            return "Exposes API flow and request orchestration responsibilities."
        if "repository" in lower or "sqlite" in lower:
            return "Provides persistence logic and storage abstractions."
        return f"Implements the main responsibilities of {title}."
