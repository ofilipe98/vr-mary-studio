from __future__ import annotations

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


class AntigravitySkillAdapter(ProviderSkillAdapter):
    provider_name = "antigravity"
    capabilities = SkillCapabilities(
        discovery=True,
        user_invocation=True,
        agent_invocation=True,
        create=True,
        edit=True,
        enable_disable=False,
    )

    def _scan_skills_dir(self, directory: Path, scope: str) -> list[SkillDefinition]:
        if not directory.is_dir():
            return []
        items: list[SkillDefinition] = []
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return []

        for entry in entries:
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue

            metadata, instructions = parse_skill_markdown_file(skill_md)
            name = str(metadata.get("name") or entry.name).strip()
            display_name = str(metadata.get("display_name") or metadata.get("name") or entry.name).strip()
            desc = str(metadata.get("description") or "").strip()
            disable_model = bool(metadata.get("disable-model-invocation", False))
            user_invocable = bool(metadata.get("user-invocable", True))

            skill_id = make_skill_id("antigravity", str(skill_md), name)
            items.append(
                SkillDefinition(
                    id=skill_id,
                    name=name,
                    display_name=display_name,
                    description=desc,
                    short_description=desc[:90] if desc else "",
                    provider="antigravity",
                    provider_instance_id="antigravity",
                    scope=scope,
                    path=str(skill_md),
                    enabled=True,
                    user_invocable=user_invocable,
                    agent_invocable=not disable_model,
                    invocation_mode="native",
                    source="provider_native",
                    metadata={"instructions": instructions, **metadata},
                )
            )
        return items

    def discover_skills(self, workspace: Path, force_reload: bool = False) -> list[SkillDefinition]:
        results: list[SkillDefinition] = []
        seen_paths: set[str] = set()

        # 1. Workspace directories
        for folder_name in [".gemini/skills", ".agents/skills", ".agent/skills"]:
            target_dir = (workspace / folder_name).resolve(strict=False)
            for skill in self._scan_skills_dir(target_dir, scope="project"):
                if skill.path not in seen_paths:
                    seen_paths.add(skill.path)
                    results.append(skill)

        # 2. Global user directories
        user_home = Path.home()
        for folder_name in [".gemini/skills", ".agents/skills"]:
            target_dir = (user_home / folder_name).resolve(strict=False)
            for skill in self._scan_skills_dir(target_dir, scope="global"):
                if skill.path not in seen_paths:
                    seen_paths.add(skill.path)
                    results.append(skill)

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
        root_dir = (workspace / ".gemini" / "skills").resolve(strict=False)
        target_file = root_dir / clean_name / "SKILL.md"

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

        skill_id = make_skill_id("antigravity", str(target_file), clean_name)
        return SkillDefinition(
            id=skill_id,
            name=clean_name,
            display_name=clean_name,
            description=description.strip(),
            short_description=description.strip()[:90],
            provider="antigravity",
            provider_instance_id="antigravity",
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
        allowed_root = (workspace / ".gemini" / "skills").resolve(strict=False)
        if not file_path.is_relative_to(allowed_root):
            alt_root = (workspace / ".agents" / "skills").resolve(strict=False)
            if file_path.is_relative_to(alt_root):
                allowed_root = alt_root

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
