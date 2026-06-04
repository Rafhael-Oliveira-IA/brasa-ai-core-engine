from __future__ import annotations

from app.calibration.profiles import CalibrationProfileRegistry


def test_calibration_profile_registry_activates_workspace_and_prompt_profiles() -> None:
    registry = CalibrationProfileRegistry()

    profile = registry.aggregate(
        workspace_id="mmo_workspace",
        prompt="actions.xml register opcode routing",
    )

    assert "mmo_profile" in profile.name
    assert "xml_profile" in profile.name
    assert "networking_profile" in profile.name
    assert profile.xml_boost > 0.0
    assert profile.networking_boost > 0.0


def test_calibration_profile_registry_unity_shader_profile() -> None:
    registry = CalibrationProfileRegistry()

    profile = registry.aggregate(
        workspace_id="unity_workspace",
        prompt="shadergraph material hlsl runtime",
    )

    assert "unity_profile" in profile.name
    assert "shader_profile" in profile.name
    assert profile.shader_boost > 0.0
    assert profile.assets_boost > 0.0
