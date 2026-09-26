from __future__ import annotations

from functools import lru_cache
from importlib import resources

from .skills.models import SkillDefinition
from .skills.parser import parse_frontmatter_text


_BUILTIN_EXPERT_PROFILES = frozenset({"adaptive"})


def normalize_expert_profile(value: object) -> str:
    profile = str(value or "").strip().casefold()
    return profile if profile in _BUILTIN_EXPERT_PROFILES else ""


@lru_cache(maxsize=None)
def _load_builtin_expert_profile(key: str) -> SkillDefinition:
    profile = normalize_expert_profile(key)
    if profile != "adaptive":
        raise ValueError(f"Perfil especialista desconhecido: {key}")

    raw = (
        resources.files("vrsoft_extractor.mary")
        .joinpath("data", "expert_profile_adaptive.md")
        .read_text(encoding="utf-8")
    )
    metadata, instructions = parse_frontmatter_text(raw)
    description = str(metadata.get("description") or "").strip()
    return SkillDefinition(
        id="builtin-expert-profile-adaptive",
        name="adaptive",
        display_name="Adaptativa",
        description=description,
        provider="app",
        provider_instance_id="app",
        scope="vr",
        path="vrsoft_extractor/mary/data/expert_profile_adaptive.md",
        enabled=True,
        user_invocable=False,
        agent_invocable=True,
        invocation_mode="injected",
        source="app_managed",
        instructions=instructions,
        metadata={**metadata, "builtin_profile": True},
    )


def get_expert_profile(value: object) -> SkillDefinition | None:
    profile = normalize_expert_profile(value)
    return _load_builtin_expert_profile(profile) if profile else None


def expert_profile_instructions(value: object) -> str:
    profile = get_expert_profile(value)
    return profile.instructions if profile else ""
