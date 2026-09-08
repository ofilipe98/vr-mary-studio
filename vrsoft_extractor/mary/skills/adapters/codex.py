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


class CodexSkillAdapter(ProviderSkillAdapter):
    provider_name = "codex"
    capabilities = SkillCapabilities(
        discovery=True,
        user_invocation=True,
        agent_invocation=True,
        create=True,
        edit=True,
        enable_disable=False,
    )

    def __init__(self, codex_provider: Any = None) -> None:
        self.codex_provider = codex_provider

    def _get_discovery_paths(self, workspace: Path) -> list[tuple[Path, str]]:
        paths: list[tuple[Path, str]] = []
        # Project level (.agents/skills and .codex/skills)
        proj_agents = (workspace / ".agents" / "skills").resolve(strict=False)
        if proj_agents.is_dir():
            paths.append((proj_agents, "project"))

        proj_codex = (workspace / ".codex" / "skills").resolve(strict=False)
        if proj_codex.is_dir():
            paths.append((proj_codex, "project"))

        # User level (~/.agents/skills and ~/.codex/skills)
        user_home = Path.home()
        user_agents = (user_home / ".agents" / "skills").resolve(strict=False)
        if user_agents.is_dir():
            paths.append((user_agents, "personal"))

        user_codex = (user_home / ".codex" / "skills").resolve(strict=False)
        if user_codex.is_dir():
            paths.append((user_codex, "personal"))

        # AppData / Config level on Windows
        appdata = os.environ.get("APPDATA")
        if appdata:
            win_codex = (Path(appdata) / "codex" / "skills").resolve(strict=False)
            if win_codex.is_dir():
                paths.append((win_codex, "global"))

        return paths

    def discover_skills(self, workspace: Path, force_reload: bool = False) -> list[SkillDefinition]:
        discovered: list[SkillDefinition] = []
        seen_paths: set[str] = set()

        for dir_path, scope in self._get_discovery_paths(workspace):
            try:
                for entry in sorted(dir_path.iterdir()):
                    if not entry.is_dir():
                        continue
                    skill_md = entry / "SKILL.md"
                    if not skill_md.is_file():
                        continue
                    norm_p = str(skill_md.resolve(strict=False))
                    if norm_p in seen_paths:
                        continue
                    metadata, instructions = parse_skill_markdown_file(skill_md)
                    name = str(metadata.get("name") or entry.name).strip()
                    display_name = str(metadata.get("display_name") or metadata.get("name") or entry.name).strip()
                    desc = str(metadata.get("description") or "").strip()
                    disable_model = bool(metadata.get("disable-model-invocation", False))
                    user_invocable = bool(metadata.get("user-invocable", True))

                    skill_id = make_skill_id("codex", norm_p, name)
                    discovered.append(
                        SkillDefinition(
                            id=skill_id,
                            name=name,
                            display_name=display_name,
                            description=desc,
                            short_description=desc[:90] if desc else "",
                            provider="codex",
                            provider_instance_id="codex",
                            scope=scope,
                            path=norm_p,
                            enabled=True,
                            user_invocable=user_invocable,
                            agent_invocable=not disable_model,
                            invocation_mode="native",
                            source="provider_native",
                            instructions=instructions,
                            metadata={"instructions": instructions, **metadata},
                        )
                    )
                    seen_paths.add(norm_p)
            except OSError:
                continue

        return discovered

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

        if scope == "personal":
            base_dir = Path.home() / ".agents" / "skills"
            allowed_root = Path.home()
        else:
            base_dir = workspace / ".agents" / "skills"
            allowed_root = workspace

        target_file = base_dir / clean_name / "SKILL.md"
        assert_safe_skill_path(target_file, allowed_root)

        metadata = {
            "name": clean_name,
            "description": description.strip(),
        }
        if not agent_invocable:
            metadata["disable-model-invocation"] = True
        if not user_invocable:
            metadata["user-invocable"] = False

        content = serialize_skill_markdown(metadata, instructions)
        atomic_write_skill(target_file, content)

        norm_p = str(target_file.resolve(strict=False))
        skill_id = make_skill_id("codex", norm_p, clean_name)
        return SkillDefinition(
            id=skill_id,
            name=clean_name,
            display_name=clean_name,
            description=description.strip(),
            short_description=description.strip()[:90],
            provider="codex",
            provider_instance_id="codex",
            scope=scope,
            path=norm_p,
            enabled=True,
            user_invocable=user_invocable,
            agent_invocable=agent_invocable,
            invocation_mode="native",
            source="provider_native",
            instructions=instructions,
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
        allowed_root = (workspace / ".agents" / "skills").resolve(strict=False)
        if not file_path.is_relative_to(allowed_root):
            alt_root = (workspace / ".codex" / "skills").resolve(strict=False)
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
        existing.instructions = instructions
        existing.metadata["instructions"] = instructions
        return existing
