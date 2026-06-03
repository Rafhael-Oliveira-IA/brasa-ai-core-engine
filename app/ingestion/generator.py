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

        markers.update(self._path_model_markers(path=path, content_markers=markers))

        if "data/actions/actions.xml" in path:
            markers.add("classic-action-bind")

        if "data/actions/scripts/" in path:
            markers.add("classic-action-script")

        if "data/scripts/" in path and "Action()" in markers:
            markers.add("revscripts-action")

        return markers

    def _path_model_markers(self, *, path: str, content_markers: set[str]) -> set[str]:
        markers: set[str] = set()
        parts = [part for part in path.split("/") if part]

        if len(parts) >= 2 and parts[0] == "data":
            system = parts[1]

            if path.endswith(".xml"):
                markers.add("classic-xml-bind")
                markers.add(f"classic-{system}-bind")

            if "scripts" in parts[2:]:
                markers.add("classic-script-callback")
                markers.add(f"classic-{system}-script")

        if path.startswith("data/scripts/"):
            markers.add("runtime-script-file")
            if any(item in content_markers for item in {":register", "register()", "Action()", "TalkAction()", "MoveEvent()", "CreatureEvent()", "GlobalEvent()", "Spell()", "Weapon()"}):
                markers.add("runtime-script-register")

        if any(item.startswith("script:") for item in content_markers):
            markers.add("xml-script-binding")

        return markers

    def _xml_markers(self, content: str) -> set[str]:
        markers: set[str] = set()

        for tag in re.findall(r"<\s*([A-Za-z_][A-Za-z0-9_:-]*)\b", content, flags=re.IGNORECASE):
            lower = tag.lower()
            if lower in {
                "action",
                "talkaction",
                "movevent",
                "creaturescript",
                "globalevent",
                "event",
                "spell",
                "instant",
                "rune",
                "weapon",
            }:
                markers.add(lower)
                markers.add(f"xml-tag:{lower}")

        for attribute in re.findall(
            r"\b(itemid|actionid|uniqueid|fromid|toid|fromaid|toaid|fromuid|touid|script|event|type|name|words|id)\s*=",
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
        if re.search(r"\bTalkAction\s*\(", content):
            markers.add("TalkAction()")
        if re.search(r"\bMoveEvent\s*\(", content):
            markers.add("MoveEvent()")
        if re.search(r"\bCreatureEvent\s*\(", content):
            markers.add("CreatureEvent()")
        if re.search(r"\bGlobalEvent\s*\(", content):
            markers.add("GlobalEvent()")
        if re.search(r"\bSpell\s*\(", content):
            markers.add("Spell()")
        if re.search(r"\bWeapon\s*\(", content):
            markers.add("Weapon()")
        if re.search(r":register\s*\(", content):
            markers.add(":register")
        if re.search(r"\bregister\s*\(", content):
            markers.add("register()")
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

        for callback in re.findall(r"\b(on[A-Za-z0-9_]+)\b", content):
            if len(callback) > 3:
                markers.add(callback)

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
            r"^\s*(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:TalkAction|MoveEvent|CreatureEvent|GlobalEvent|Spell|Weapon)\s*\(",
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

        if path.startswith("data/") and path.endswith(".xml") and "script" in lower:
            system = self._data_system(path)
            return f"Defines classic XML bindings for {system} scripts and callback entrypoints."
        if path.startswith("data/") and not path.startswith("data/scripts/") and "scripts/" in path and "on" in lower and "function" in lower:
            system = self._data_system(path)
            return f"Implements callback logic for classic {system} XML-bound scripts."
        if path.startswith("data/scripts/") and (":register" in lower or "register(" in lower):
            return "Registers runtime script handlers directly, without central XML binding."
        if path.startswith("assets/") and path.endswith(".cs"):
            return "Implements Unity runtime/gameplay behavior under Assets."

        if "inventory" in lower:
            return "Handles inventory-related workflows and data boundaries."
        if "router" in lower or "endpoint" in lower:
            return "Exposes API flow and request orchestration responsibilities."
        if "repository" in lower or "sqlite" in lower:
            return "Provides persistence logic and storage abstractions."
        return f"Implements the main responsibilities of {title}."

    def _data_system(self, path: str) -> str:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "data":
            return parts[1]
        return "script"
