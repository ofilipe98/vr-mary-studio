from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def make_skill_id(provider_instance_id: str, normalized_path: str, skill_name: str) -> str:
    """Generate a stable, unique identifier for a skill."""
    norm_path = str(Path(normalized_path).resolve(strict=False)).replace("\\", "/").lower()
    raw = f"{provider_instance_id}:{norm_path}:{skill_name.strip().lower()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in skill_name.lower()).strip("-")
    return f"skill-{clean_name}-{digest}"


@dataclass
class SkillCapabilities:
    discovery: bool = True
    user_invocation: bool = True
    agent_invocation: bool = True
    create: bool = False
    edit: bool = False
    enable_disable: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "discovery": self.discovery,
            "userInvocation": self.user_invocation,
            "agentInvocation": self.agent_invocation,
            "create": self.create,
            "edit": self.edit,
            "enableDisable": self.enable_disable,
        }


@dataclass
class SkillDefinition:
    id: str
    name: str
    display_name: str = ""
    description: str = ""
    short_description: str = ""
    provider: str = ""  # codex, claude, antigravity, opencode, app
    provider_instance_id: str = ""
    scope: str = "project"  # project, personal, global, provider, vr
    path: str = ""
    enabled: bool = True
    user_invocable: bool = True
    agent_invocable: bool = True
    invocation_mode: str = "native"  # native, prompt, injected
    source: str = "provider_native"  # provider_native, app_managed
    instructions: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name
        if not self.short_description and self.description:
            self.short_description = self.description[:90]

    def can_use_in_harness(self, harness_mode: str) -> bool:
        if harness_mode == "general" and self.scope == "vr":
            return False
        return True

    @classmethod
    def from_skill_md(
        cls,
        skill_path: str | Path,
        raw_content: str,
        provider: str = "",
        scope: str = "project",
        provider_instance_id: str = "",
    ) -> SkillDefinition:
        from .parser import parse_frontmatter_text
        meta, instructions = parse_frontmatter_text(raw_content)
        name = str(meta.get("name") or Path(skill_path).parent.name).strip()
        desc = str(meta.get("description", "")).strip()
        skill_id = make_skill_id(provider_instance_id or provider, str(skill_path), name)
        return cls(
            id=skill_id,
            name=name,
            display_name=str(meta.get("display_name") or name),
            description=desc,
            short_description=desc[:90] if desc else "",
            provider=provider,
            provider_instance_id=provider_instance_id or provider,
            scope=scope,
            path=str(skill_path),
            enabled=True,
            user_invocable=bool(meta.get("user-invocable", True)),
            agent_invocable=bool(meta.get("agent-invocable", True)),
            invocation_mode=str(meta.get("invocation-mode", "native")),
            source="provider_native",
            instructions=instructions,
            metadata=meta,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "displayName": self.display_name or self.name,
            "description": self.description,
            "shortDescription": self.short_description or (self.description[:90] if self.description else ""),
            "provider": self.provider,
            "providerInstanceId": self.provider_instance_id,
            "scope": self.scope,
            "path": self.path,
            "enabled": self.enabled,
            "userInvocable": self.user_invocable,
            "agentInvocable": self.agent_invocable,
            "invocationMode": self.invocation_mode,
            "source": self.source,
            "instructions": self.instructions,
            "metadata": dict(self.metadata),
        }


@dataclass
class MessageSkillReference:
    skill_id: str
    name_snapshot: str
    provider_instance_id: str
    scope: str
    path_reference: str

    def to_dict(self) -> dict[str, str]:
        return {
            "skillId": self.skill_id,
            "nameSnapshot": self.name_snapshot,
            "providerInstanceId": self.provider_instance_id,
            "scope": self.scope,
            "pathReference": self.path_reference,
        }
