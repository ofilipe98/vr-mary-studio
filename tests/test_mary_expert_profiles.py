from __future__ import annotations

from importlib import resources

import pytest

from vrsoft_extractor.mary.expert_profiles import (
    _load_builtin_expert_profile,
    expert_profile_instructions,
    get_expert_profile,
    normalize_expert_profile,
)
from vrsoft_extractor.mary.skills.parser import parse_frontmatter_text
from vrsoft_extractor.mary.skills.registry import SkillRegistry


def test_normalize_expert_profile_accepts_only_adaptive() -> None:
    assert normalize_expert_profile(" adaptive ") == "adaptive"
    assert normalize_expert_profile("ADAPTIVE") == "adaptive"
    assert normalize_expert_profile("training") == ""
    assert normalize_expert_profile(None) == ""
    assert get_expert_profile("") is None
    assert get_expert_profile("unknown") is None
    assert expert_profile_instructions("unknown") == ""


def test_adaptive_is_builtin_vr_skill_injected_by_the_app() -> None:
    profile = get_expert_profile("adaptive")

    assert profile is not None
    assert profile.id == "builtin-expert-profile-adaptive"
    assert profile.name == "adaptive"
    assert profile.display_name == "Adaptativa"
    assert profile.provider == "app"
    assert profile.provider_instance_id == "app"
    assert profile.scope == "vr"
    assert profile.path == "vrsoft_extractor/mary/data/expert_profile_adaptive.md"
    assert profile.enabled is True
    assert profile.user_invocable is False
    assert profile.agent_invocable is True
    assert profile.invocation_mode == "injected"
    assert profile.source == "app_managed"
    assert profile.metadata["builtin_profile"] is True
    assert profile.metadata["name"] == "adaptive"
    assert profile.metadata["display_name"] == "Adaptativa"
    assert profile.metadata["user-invocable"] is False
    assert profile.metadata["agent-invocable"] is True
    assert profile.metadata["invocation-mode"] == "injected"
    assert profile.instructions.strip()
    assert "ferramentas VR" in profile.instructions
    assert "raciocínio privado" in profile.instructions
    assert expert_profile_instructions("adaptive") == profile.instructions


def test_adaptive_loads_packaged_markdown_frontmatter() -> None:
    raw = (
        resources.files("vrsoft_extractor.mary")
        .joinpath("data", "expert_profile_adaptive.md")
        .read_text(encoding="utf-8")
    )
    metadata, instructions = parse_frontmatter_text(raw)
    profile = get_expert_profile("adaptive")

    assert set(metadata) == {
        "name",
        "display_name",
        "description",
        "user-invocable",
        "agent-invocable",
        "invocation-mode",
    }
    assert metadata["name"] == "adaptive"
    assert metadata["display_name"] == "Adaptativa"
    assert metadata["user-invocable"] is False
    assert metadata["agent-invocable"] is True
    assert metadata["invocation-mode"] == "injected"
    assert profile is not None
    assert profile.instructions == instructions


def test_adaptive_packaged_load_is_cached() -> None:
    _load_builtin_expert_profile.cache_clear()

    first = get_expert_profile("adaptive")
    second = get_expert_profile(" ADAPTIVE ")

    assert first is second
    assert _load_builtin_expert_profile.cache_info().hits == 1


def test_adaptive_is_not_discovered_as_a_common_user_skill(tmp_path) -> None:
    registry = SkillRegistry(app_skills_dir=tmp_path / "app-skills")

    discovered = registry.list_skills("app", workspace=tmp_path, vr_mode="ultra")

    assert all(item.id != "builtin-expert-profile-adaptive" for item in discovered)


def test_unknown_builtin_profile_cannot_be_loaded() -> None:
    with pytest.raises(ValueError, match="desconhecido"):
        _load_builtin_expert_profile("training")
