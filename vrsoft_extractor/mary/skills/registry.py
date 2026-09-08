from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .adapters.antigravity import AntigravitySkillAdapter
from .adapters.app import AppSkillAdapter
from .adapters.base import ProviderSkillAdapter
from .adapters.claude import ClaudeSkillAdapter
from .adapters.codex import CodexSkillAdapter
from .adapters.opencode import OpenCodeSkillAdapter
from .models import SkillDefinition

LOGGER = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(
        self,
        app_skills_dir: Path | None = None,
        codex_provider=None,
        provider_instances: dict[str, Any] | None = None,
    ) -> None:
        if provider_instances and not codex_provider:
            codex_provider = provider_instances.get("codex")

        self._app_skills_dir = Path(app_skills_dir).resolve(strict=False) if app_skills_dir else None
        self._adapters: dict[str, ProviderSkillAdapter] = {
            "claude": ClaudeSkillAdapter(),
            "codex": CodexSkillAdapter(codex_provider),
            "antigravity": AntigravitySkillAdapter(),
            "opencode": OpenCodeSkillAdapter(),
            "app": AppSkillAdapter(app_skills_dir),
        }
        self._cache: dict[tuple[str, str], tuple[float, list[SkillDefinition]]] = {}
        self._cache_ttl = 30.0  # seconds

    def register_adapter(self, provider_name: str, adapter: ProviderSkillAdapter) -> None:
        self._adapters[provider_name] = adapter

    def set_codex_provider(self, codex_provider) -> None:
        self._adapters["codex"] = CodexSkillAdapter(codex_provider)

    def _resolve_workspace(self, workspace: Path | str | None) -> Path:
        if workspace is not None:
            return Path(workspace).resolve(strict=False)
        if self._app_skills_dir:
            return self._app_skills_dir
        return Path.cwd().resolve(strict=False)

    def list_skills(
        self,
        provider_name: str = "",
        workspace: Path | str | None = None,
        force_reload: bool = False,
        vr_mode: str = "off",
    ) -> list[SkillDefinition]:
        ws_path = self._resolve_workspace(workspace)
        prov_key = provider_name.lower().strip() if provider_name else ""
        cache_key = (prov_key, str(ws_path))
        now = time.monotonic()

        if not force_reload and cache_key in self._cache:
            ts, items = self._cache[cache_key]
            if now - ts < self._cache_ttl:
                return self._filter_by_vr_mode(items, vr_mode)

        all_skills: list[SkillDefinition] = []
        seen_ids: set[str] = set()

        if prov_key:
            # 1. Primary provider skills
            provider_adapter = self._adapters.get(prov_key)
            if provider_adapter:
                try:
                    for s in provider_adapter.discover_skills(ws_path, force_reload=force_reload):
                        if s.id not in seen_ids:
                            seen_ids.add(s.id)
                            all_skills.append(s)
                except Exception as exc:
                    LOGGER.warning("Erro ao descobrir skills para provider '%s': %s", provider_name, exc)

            # 2. App-managed skills (always included if applicable)
            app_adapter = self._adapters.get("app")
            if app_adapter and prov_key != "app":
                try:
                    for s in app_adapter.discover_skills(ws_path, force_reload=force_reload):
                        if s.id not in seen_ids:
                            seen_ids.add(s.id)
                            all_skills.append(s)
                except Exception as exc:
                    LOGGER.warning("Erro ao descobrir skills da app: %s", exc)
        else:
            # Query all adapters
            for name, adapter in self._adapters.items():
                try:
                    for s in adapter.discover_skills(ws_path, force_reload=force_reload):
                        if s.id not in seen_ids:
                            seen_ids.add(s.id)
                            all_skills.append(s)
                except Exception as exc:
                    LOGGER.warning("Erro ao descobrir skills do adapter '%s': %s", name, exc)

        self._cache[cache_key] = (now, all_skills)
        return self._filter_by_vr_mode(all_skills, vr_mode)

    def _filter_by_vr_mode(self, skills: list[SkillDefinition], vr_mode: str) -> list[SkillDefinition]:
        # P0-7: General Harness cannot receive VR context just because a VR skill exists
        if vr_mode in ("off", "", None):
            return [s for s in skills if s.scope != "vr"]
        return skills

    def search_skills(
        self,
        query: str,
        provider_name: str = "",
        workspace: Path | str | None = None,
        vr_mode: str = "off",
    ) -> list[SkillDefinition]:
        clean_q = query.strip().lower()
        skills = self.list_skills(provider_name, workspace, vr_mode=vr_mode)
        if not clean_q:
            return skills

        exact_matches: list[SkillDefinition] = []
        prefix_matches: list[SkillDefinition] = []
        sub_name_matches: list[SkillDefinition] = []
        desc_matches: list[SkillDefinition] = []

        for s in skills:
            name_lower = s.name.lower()
            display_lower = s.display_name.lower()
            desc_lower = s.description.lower()

            if name_lower == clean_q or display_lower == clean_q:
                exact_matches.append(s)
            elif name_lower.startswith(clean_q) or display_lower.startswith(clean_q):
                prefix_matches.append(s)
            elif clean_q in name_lower or clean_q in display_lower:
                sub_name_matches.append(s)
            elif clean_q in desc_lower:
                desc_matches.append(s)

        return exact_matches + prefix_matches + sub_name_matches + desc_matches

    def search(
        self,
        query: str,
        provider: str = "",
        workspace: Path | str | None = None,
        vr_mode: str = "off",
    ) -> list[SkillDefinition]:
        """Convenience alias for search_skills."""
        return self.search_skills(query, provider_name=provider, workspace=workspace, vr_mode=vr_mode)

    def get_skill(
        self,
        skill_id: str,
        provider_name: str = "",
        workspace: Path | str | None = None,
    ) -> SkillDefinition | None:
        ws_path = self._resolve_workspace(workspace)
        for s in self.list_skills(provider_name, ws_path, force_reload=False, vr_mode="on"):
            if s.id == skill_id or s.name.lower() == skill_id.lower():
                return s
        return None

    def create_skill(
        self,
        provider_name: str,
        name: str,
        description: str,
        instructions: str,
        workspace: Path | str | None = None,
        scope: str = "project",
        user_invocable: bool = True,
        agent_invocable: bool = True,
    ) -> SkillDefinition:
        ws_path = self._resolve_workspace(workspace)
        adapter = self._adapters.get(provider_name.lower())
        if not adapter:
            adapter = self._adapters.get("app")
        if not adapter:
            raise ValueError(f"Provedor desconhecido: {provider_name}")

        result = adapter.create_skill(
            name=name,
            description=description,
            instructions=instructions,
            workspace=ws_path,
            scope=scope,
            user_invocable=user_invocable,
            agent_invocable=agent_invocable,
        )
        # Invalidate cache
        cache_key = (provider_name.lower(), str(ws_path))
        self._cache.pop(cache_key, None)
        self._cache.pop(("", str(ws_path)), None)
        return result

    def update_skill(
        self,
        skill_id: str,
        instructions: str | None = None,
        description: str | None = None,
        provider_name: str = "",
        workspace: Path | str | None = None,
        user_invocable: bool = True,
        agent_invocable: bool = True,
    ) -> SkillDefinition:
        ws_path = self._resolve_workspace(workspace)
        existing = self.get_skill(skill_id, provider_name, ws_path)
        if not existing:
            raise ValueError(f"Skill '{skill_id}' não encontrada.")

        prov_key = existing.provider.lower()
        adapter = self._adapters.get(prov_key) or self._adapters.get("app")
        if not adapter:
            raise ValueError(f"Provedor '{prov_key}' não suporta atualização de skills.")

        new_desc = description if description is not None else existing.description
        new_inst = instructions if instructions is not None else existing.instructions

        result = adapter.update_skill(
            skill_id=existing.id,
            description=new_desc,
            instructions=new_inst,
            workspace=ws_path,
            user_invocable=user_invocable,
            agent_invocable=agent_invocable,
        )
        cache_key = (prov_key, str(ws_path))
        self._cache.pop(cache_key, None)
        self._cache.pop(("", str(ws_path)), None)
        return result
