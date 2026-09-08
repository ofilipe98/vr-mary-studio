from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..models import SkillCapabilities, SkillDefinition, make_skill_id
from ..parser import parse_skill_markdown_file, serialize_skill_markdown
from .base import (
    ProviderSkillAdapter,
    assert_safe_skill_path,
    atomic_write_skill,
    validate_skill_name,
)


def _claude_config_dir() -> Path:
    raw = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if raw:
        return Path(raw).resolve(strict=False)
    return (Path.home() / ".claude").resolve(strict=False)


class ClaudeSkillAdapter(ProviderSkillAdapter):
    provider_name = "claude"
    capabilities = SkillCapabilities(
        discovery=True,
        user_invocation=True,
        agent_invocation=True,
        create=True,
        edit=True,
        enable_disable=False,
    )

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or _claude_config_dir()

    def _scan_skills_directory(self, skills_dir: Path, scope: str) -> list[SkillDefinition]:
        if not skills_dir.is_dir():
            return []
        discovered: list[SkillDefinition] = []
        try:
            entries = sorted(skills_dir.iterdir())
        except OSError:
            return []

        for entry in entries:
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue

            metadata, instructions = parse_skill_markdown_file(skill_md)
            skill_name = str(metadata.get("name") or entry.name).strip()
            display_name = str(metadata.get("display_name") or metadata.get("name") or entry.name).strip()
            description = str(metadata.get("description") or "").strip()

            disable_model = bool(metadata.get("disable-model-invocation", False))
            user_invocable = bool(metadata.get("user-invocable", True))
            agent_invocable = not disable_model

            skill_id = make_skill_id("claude", str(skill_md), skill_name)

            discovered.append(
                SkillDefinition(
                    id=skill_id,
                    name=skill_name,
                    display_name=display_name,
                    description=description,
                    short_description=description[:90] if description else "",
                    provider="claude",
                    provider_instance_id="claude",
                    scope=scope,
                    path=str(skill_md),
                    enabled=True,
                    user_invocable=user_invocable,
                    agent_invocable=agent_invocable,
                    invocation_mode="native",
                    source="provider_native",
                    metadata={"instructions": instructions, **metadata},
                )
            )
        return discovered

    def discover_skills(self, workspace: Path, force_reload: bool = False) -> list[SkillDefinition]:
        results: list[SkillDefinition] = []

        # 1. Project skills: <workspace>/.claude/skills
        project_skills_dir = (workspace / ".claude" / "skills").resolve(strict=False)
        results.extend(self._scan_skills_directory(project_skills_dir, scope="project"))

        # 2. Global skills: <CLAUDE_CONFIG_DIR>/skills
        global_skills_dir = (self._config_dir / "skills").resolve(strict=False)
        results.extend(self._scan_skills_directory(global_skills_dir, scope="global"))

        return results

    def create_skill(
        self,
        name: str,
        description: str,
        instructions: str,
        workspace: Path,
        scope: str = "project",
        user_invocable: bool = True,
        agent_invocable: bool = True,
    ) -> SkillDefinition:
        clean_name = validate_skill_name(name)

        if scope == "global":
            root_dir = (self._config_dir / "skills").resolve(strict=False)
        else:
            root_dir = (workspace / ".claude" / "skills").resolve(strict=False)

        target_dir = root_dir / clean_name
        target_file = target_dir / "SKILL.md"

        # Security check: path traversal & root containment
        assert_safe_skill_path(target_file, root_dir)

        metadata: dict[str, Any] = {
            "name": clean_name,
            "description": description.strip(),
        }
        if not agent_invocable:
            metadata["disable-model-invocation"] = True
        if not user_invocable:
            metadata["user-invocable"] = False

        content = serialize_skill_markdown(metadata, instructions)
        atomic_write_skill(target_file, content)

        skill_id = make_skill_id("claude", str(target_file), clean_name)
        return SkillDefinition(
            id=skill_id,
            name=clean_name,
            display_name=clean_name,
            description=description.strip(),
            short_description=description.strip()[:90],
            provider="claude",
            provider_instance_id="claude",
            scope=scope,
            path=str(target_file),
            enabled=True,
            user_invocable=user_invocable,
            agent_invocable=agent_invocable,
            invocation_mode="native",
            source="provider_native",
            metadata={"instructions": instructions, **metadata},
        )

    def update_skill(
        self,
        skill_id: str,
        description: str,
        instructions: str,
        workspace: Path,
        user_invocable: bool = True,
        agent_invocable: bool = True,
    ) -> SkillDefinition:
        existing = self.get_skill(skill_id, workspace)
        if not existing:
            raise FileNotFoundError(f"Skill com id '{skill_id}' não encontrada")

        file_path = Path(existing.path)
        allowed_root = (
            (self._config_dir / "skills").resolve(strict=False)
            if existing.scope == "global"
            else (workspace / ".claude" / "skills").resolve(strict=False)
        )
        assert_safe_skill_path(file_path, allowed_root)

        metadata = dict(existing.metadata)
        metadata["description"] = description.strip()
        metadata.pop("instructions", None)

        if not agent_invocable:
            metadata["disable-model-invocation"] = True
        else:
            metadata.pop("disable-model-invocation", None)

        if not user_invocable:
            metadata["user-invocable"] = False
        else:
            metadata.pop("user-invocable", None)

        content = serialize_skill_markdown(metadata, instructions)
        atomic_write_skill(file_path, content)

        existing.description = description.strip()
        existing.short_description = description.strip()[:90]
        existing.user_invocable = user_invocable
        existing.agent_invocable = agent_invocable
        existing.metadata["instructions"] = instructions
        return existing
