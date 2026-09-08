from __future__ import annotations

import abc
import os
import re
from pathlib import Path
from typing import Sequence

from ..models import SkillCapabilities, SkillDefinition

VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")
SENSITIVE_FILES = {
    "auth.json",
    "credentials",
    "credentials.json",
    ".env",
    "token.json",
    "acp_token.json",
    "config.json",
}


class SkillSecurityError(ValueError, RuntimeError):
    pass


def validate_skill_name(name: str) -> str:
    cleaned = name.strip()
    if not VALID_NAME_RE.match(cleaned):
        raise SkillSecurityError(
            f"Nome de skill inválido: '{name}'. Deve conter de 2 a 64 caracteres alfanuméricos, hífen ou sublinhado."
        )
    return cleaned


def assert_safe_skill_path(target_path: Path, allowed_root: Path | Sequence[Path]) -> Path:
    """Ensure target path is strictly within the allowed root(s) and not escaping."""
    roots: list[Path] = [allowed_root] if isinstance(allowed_root, Path) else list(allowed_root)
    resolved_roots = [r.resolve(strict=False) for r in roots]
    resolved_target = target_path.resolve(strict=False)

    is_within_any = False
    for root in resolved_roots:
        try:
            resolved_target.relative_to(root)
            is_within_any = True
            break
        except ValueError:
            continue

    if not is_within_any:
        raise SkillSecurityError(
            f"Tentativa de path traversal bloqueada: {resolved_target} está fora de {resolved_roots}"
        )

    for part in resolved_target.parts:
        if part.lower() in SENSITIVE_FILES or "token" in part.lower():
            raise SkillSecurityError(f"Acesso a arquivo sensível bloqueado: {part}")

    return resolved_target


def atomic_write_skill(target_file: Path, content: str) -> None:
    """Safely and atomically write a skill file."""
    parent = target_file.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp_file = parent / f".tmp_{target_file.name}_{os.getpid()}"
    try:
        temp_file.write_text(content, encoding="utf-8")
        temp_file.replace(target_file)
    except Exception as exc:
        if temp_file.is_file():
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise exc


class ProviderSkillAdapter(abc.ABC):
    provider_name: str
    capabilities: SkillCapabilities

    @abc.abstractmethod
    def discover_skills(self, workspace: Path, force_reload: bool = False) -> list[SkillDefinition]:
        """Discover skills available in the workspace and user home for this provider."""
        raise NotImplementedError

    def get_skill(self, skill_id: str, workspace: Path) -> SkillDefinition | None:
        """Find a skill by id in the given workspace."""
        for skill in self.discover_skills(workspace):
            if skill.id == skill_id:
                return skill
        return None

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
        """Create a new skill definition on disk. Default raises NotImplementedError."""
        raise NotImplementedError(f"Criação de skills não suportada para o provider {self.provider_name}")

    def update_skill(
        self,
        skill: SkillDefinition,
        instructions: str,
        description: str | None = None,
        user_invocable: bool | None = None,
        agent_invocable: bool | None = None,
    ) -> SkillDefinition:
        """Update an existing skill definition on disk. Default raises NotImplementedError."""
        raise NotImplementedError(f"Atualização de skills não suportada para o provider {self.provider_name}")
