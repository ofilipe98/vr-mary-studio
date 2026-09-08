from __future__ import annotations

from pathlib import Path

from ..models import SkillCapabilities, SkillDefinition, make_skill_id
from ..parser import parse_skill_markdown_file, serialize_skill_markdown
from .base import (
    ProviderSkillAdapter,
    assert_safe_skill_path,
    atomic_write_skill,
    validate_skill_name,
)


class OpenCodeSkillAdapter(ProviderSkillAdapter):
    provider_name = "opencode"
    capabilities = SkillCapabilities(
        discovery=True,
        user_invocation=True,
        agent_invocation=False,
        create=True,
        edit=True,
        enable_disable=False,
    )

    def discover_skills(self, workspace: Path, force_reload: bool = False) -> list[SkillDefinition]:
        discovered: list[SkillDefinition] = []
        target_dir = (workspace / ".opencode" / "skills").resolve(strict=False)
        if not target_dir.is_dir():
            return []

        try:
            for entry in sorted(target_dir.iterdir()):
                if not entry.is_dir():
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    continue
                metadata, instructions = parse_skill_markdown_file(skill_md)
                name = str(metadata.get("name") or entry.name).strip()
                desc = str(metadata.get("description") or "").strip()
                skill_id = make_skill_id("opencode", str(skill_md), name)
                discovered.append(
                    SkillDefinition(
                        id=skill_id,
                        name=name,
                        display_name=str(metadata.get("display_name") or name),
                        description=desc,
                        short_description=desc[:90] if desc else "",
                        provider="opencode",
                        provider_instance_id="opencode",
                        scope="project",
                        path=str(skill_md),
                        enabled=True,
                        user_invocable=bool(metadata.get("user-invocable", True)),
                        agent_invocable=False,
                        invocation_mode="native",
                        source="provider_native",
                        instructions=instructions,
                        metadata=metadata,
                    )
                )
        except OSError:
            pass

        return discovered

    def create_skill(
        self,
        name: str,
        description: str,
        instructions: str,
        workspace: Path,
        scope: str = "project",
        user_invocable: bool = True,
        agent_invocable: bool = False,
    ) -> SkillDefinition:
        clean_name = validate_skill_name(name)
        skills_root = workspace / ".opencode" / "skills"
        target_file = skills_root / clean_name / "SKILL.md"
        assert_safe_skill_path(target_file, workspace)

        meta = {
            "name": clean_name,
            "description": description.strip(),
            "user-invocable": user_invocable,
            "agent-invocable": agent_invocable,
        }
        content = serialize_skill_markdown(meta, instructions)
        atomic_write_skill(target_file, content)

        skill_id = make_skill_id("opencode", str(target_file), clean_name)
        return SkillDefinition(
            id=skill_id,
            name=clean_name,
            display_name=clean_name,
            description=description.strip(),
            short_description=description.strip()[:90],
            provider="opencode",
            provider_instance_id="opencode",
            scope="project",
            path=str(target_file),
            enabled=True,
            user_invocable=user_invocable,
            agent_invocable=agent_invocable,
            invocation_mode="native",
            source="provider_native",
            instructions=instructions,
            metadata=meta,
        )

    def update_skill(
        self,
        skill: SkillDefinition,
        instructions: str,
        description: str | None = None,
        user_invocable: bool | None = None,
        agent_invocable: bool | None = None,
    ) -> SkillDefinition:
        target_file = Path(skill.path)
        meta, _ = parse_skill_markdown_file(target_file)
        if description is not None:
            meta["description"] = description.strip()
        if user_invocable is not None:
            meta["user-invocable"] = user_invocable
        if agent_invocable is not None:
            meta["agent-invocable"] = agent_invocable

        content = serialize_skill_markdown(meta, instructions)
        atomic_write_skill(target_file, content)

        skill.instructions = instructions
        if description is not None:
            skill.description = description.strip()
            skill.short_description = skill.description[:90]
        skill.metadata = meta
        return skill
