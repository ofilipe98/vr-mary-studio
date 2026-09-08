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


class AppSkillAdapter(ProviderSkillAdapter):
    """Adapter for Studio-managed skills (e.g. ERP analysis, VR-specific procedures)."""

    provider_name = "app"
    capabilities = SkillCapabilities(
        discovery=True,
        user_invocation=True,
        agent_invocation=True,
        create=True,
        edit=True,
        enable_disable=True,
    )

    def __init__(self, app_skills_dir: Path | None = None) -> None:
        self._app_skills_dir = app_skills_dir

    def discover_skills(self, workspace: Path, force_reload: bool = False) -> list[SkillDefinition]:
        results: list[SkillDefinition] = []

        # 1. Project app skills: <workspace>/skills or <workspace>/.vr/skills
        candidate_dirs = [
            (workspace / ".vr" / "skills", "vr"),
            (workspace / "skills", "project"),
        ]
        if self._app_skills_dir and self._app_skills_dir.is_dir():
            candidate_dirs.append((self._app_skills_dir, "app"))

        seen_paths: set[str] = set()

        for directory, scope in candidate_dirs:
            resolved_dir = directory.resolve(strict=False)
            if not resolved_dir.is_dir():
                continue
            try:
                for entry in sorted(resolved_dir.iterdir()):
                    if not entry.is_dir():
                        continue
                    skill_md = entry / "SKILL.md"
                    if not skill_md.is_file():
                        continue
                    norm_path = str(skill_md.resolve(strict=False))
                    if norm_path in seen_paths:
                        continue

                    metadata, instructions = parse_skill_markdown_file(skill_md)
                    name = str(metadata.get("name") or entry.name).strip()
                    display_name = str(metadata.get("display_name") or metadata.get("name") or entry.name).strip()
                    desc = str(metadata.get("description") or "").strip()
                    disable_model = bool(metadata.get("disable-model-invocation", False))
                    user_invocable = bool(metadata.get("user-invocable", True))

                    skill_id = make_skill_id("app", norm_path, name)
                    results.append(
                        SkillDefinition(
                            id=skill_id,
                            name=name,
                            display_name=display_name,
                            description=desc,
                            short_description=desc[:90] if desc else "",
                            provider="app",
                            provider_instance_id="app",
                            scope=scope,
                            path=norm_path,
                            enabled=True,
                            user_invocable=user_invocable,
                            agent_invocable=not disable_model,
                            invocation_mode="injected",
                            source="app_managed",
                            metadata={"instructions": instructions, **metadata},
                        )
                    )
                    seen_paths.add(norm_path)
            except OSError:
                continue

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
        if scope == "vr":
            root_dir = (workspace / ".vr" / "skills").resolve(strict=False)
        else:
            root_dir = (workspace / "skills").resolve(strict=False)

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

        skill_id = make_skill_id("app", str(target_file), clean_name)
        return SkillDefinition(
            id=skill_id,
            name=clean_name,
            display_name=clean_name,
            description=description.strip(),
            short_description=description.strip()[:90],
            provider="app",
            provider_instance_id="app",
            scope=scope,
            path=str(target_file),
            enabled=True,
            user_invocable=user_invocable,
            agent_invocable=agent_invocable,
            invocation_mode="injected",
            source="app_managed",
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
            (workspace / ".vr" / "skills").resolve(strict=False)
            if existing.scope == "vr"
            else (workspace / "skills").resolve(strict=False)
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
