from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationProfile:
    name: str
    xml_boost: float = 0.0
    scripts_boost: float = 0.0
    assets_boost: float = 0.0
    src_boost: float = 0.0
    shader_boost: float = 0.0
    networking_boost: float = 0.0


class CalibrationProfileRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, CalibrationProfile] = {
            "mmo_profile": CalibrationProfile(
                name="mmo_profile",
                xml_boost=0.20,
                scripts_boost=0.18,
                src_boost=0.14,
                networking_boost=0.12,
            ),
            "unity_profile": CalibrationProfile(
                name="unity_profile",
                xml_boost=0.08,
                scripts_boost=0.10,
                assets_boost=0.22,
                shader_boost=0.18,
            ),
            "networking_profile": CalibrationProfile(
                name="networking_profile",
                src_boost=0.20,
                networking_boost=0.24,
            ),
            "lua_profile": CalibrationProfile(
                name="lua_profile",
                scripts_boost=0.20,
            ),
            "shader_profile": CalibrationProfile(
                name="shader_profile",
                shader_boost=0.30,
                assets_boost=0.14,
            ),
            "xml_profile": CalibrationProfile(
                name="xml_profile",
                xml_boost=0.36,
            ),
        }

    def active_profiles(self, *, workspace_id: str | None, prompt: str) -> list[CalibrationProfile]:
        prompt_lower = (prompt or "").lower()
        workspace = (workspace_id or "").lower()

        active: list[CalibrationProfile] = []
        if "unity" in workspace:
            active.append(self._profiles["unity_profile"])
        elif "mmo" in workspace:
            active.append(self._profiles["mmo_profile"])

        if any(token in prompt_lower for token in ("opcode", "packet", "protocol", "network", "socket")):
            active.append(self._profiles["networking_profile"])

        if any(token in prompt_lower for token in ("lua", "revscripts", "register", "onuse", "onsay")):
            active.append(self._profiles["lua_profile"])

        if any(token in prompt_lower for token in ("shader", "shadergraph", "material", "hlsl", "vfx")):
            active.append(self._profiles["shader_profile"])

        if ".xml" in prompt_lower or " xml" in prompt_lower or prompt_lower.startswith("xml"):
            active.append(self._profiles["xml_profile"])

        return active

    def aggregate(self, *, workspace_id: str | None, prompt: str) -> CalibrationProfile:
        profiles = self.active_profiles(workspace_id=workspace_id, prompt=prompt)
        if not profiles:
            return CalibrationProfile(name="default")

        return CalibrationProfile(
            name="+".join(item.name for item in profiles),
            xml_boost=sum(item.xml_boost for item in profiles),
            scripts_boost=sum(item.scripts_boost for item in profiles),
            assets_boost=sum(item.assets_boost for item in profiles),
            src_boost=sum(item.src_boost for item in profiles),
            shader_boost=sum(item.shader_boost for item in profiles),
            networking_boost=sum(item.networking_boost for item in profiles),
        )
