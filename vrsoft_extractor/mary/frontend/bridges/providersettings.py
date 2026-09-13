from __future__ import annotations
import hashlib
import json
import queue
import threading
from typing import Any
from ...erp_releases import ErpReleaseCatalog, ErpReleaseError
from ...models import ModelRef

from .presentation import (PROVIDER_LABELS, EFFORT_LABELS, ERP_JAR_SOURCE_VR_EXEC, ERP_JAR_SOURCE_WORKSPACE, ERP_JAR_SOURCE_CUSTOM, ERP_JAR_SCOPE_FULL_RELEASE, ERP_JAR_SCOPE_SINGLE, CODE_PROCESSING_HEAP_OPTIONS, CODE_PROCESSING_TIMEOUT_OPTIONS, CODE_PROCESSING_CPU_CORE_OPTIONS, CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS, CODE_PROCESSING_WINDOW_OPTIONS, DEFAULT_CODE_PROCESSING_HEAP_MB, DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS, DEFAULT_CODE_PROCESSING_CPU_CORES, DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER, DEFAULT_CODE_PROCESSING_WINDOW, CODE_PROCESSING_HARDWARE_PROFILE_VERSION)

class ProviderSettingsDomain:
    """Domain operations using the facade as the sole state and transaction owner."""
    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        return getattr(self._owner, name)

    def __setattr__(self, name, value):
        setattr(self._owner, name, value)

    def _provider_context_window(self) -> int:
        item = self._current_model_item()
        candidates = (
            item.get("contextWindow"),
            item.get("context_window"),
            item.get("contextWindowTokens"),
            item.get("inputTokenLimit"),
        )
        for value in candidates:
            try:
                parsed = int(value or 0)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return 0


    def _enabled_provider_names(self) -> list[str]:
        enabled: list[str] = []
        for provider in ("codex", "claude", "opencode", "antigravity"):
            raw = self._preferences.value(f"providers/{provider}/enabled", True)
            if isinstance(raw, bool):
                active = raw
            else:
                active = str(raw).strip().casefold() not in {"", "0", "false", "no", "off"}
            if active:
                enabled.append(provider)
        return enabled or ["codex"]


    def _current_model_item(self) -> dict[str, Any]:
        return next(
            (
                item
                for item in self._model_items
                if item.get("provider") == self._provider
                and str(item.get("value") or "") == self._model
            ),
            {},
        )


    def _supported_efforts_for_current_model(self) -> list[str]:
        if self._provider == "antigravity":
            return []
        metadata = self._current_model_item()
        raw_efforts = metadata.get("efforts") or []
        efforts: list[str] = []
        for item in raw_efforts:
            if isinstance(item, str):
                value = item
            elif isinstance(item, dict):
                value = (
                    item.get("reasoningEffort")
                    or item.get("effort")
                    or item.get("value")
                    or item.get("id")
                    or ""
                )
            else:
                value = ""
            normalized = str(value).strip().casefold()
            if normalized == "ultra":
                normalized = "max"
            if normalized in EFFORT_LABELS and normalized not in efforts:
                efforts.append(normalized)
        if efforts:
            return ["auto", *efforts]
        return (
            ["auto", "low", "medium", "high", "xhigh", "max"]
            if self._provider == "claude"
            else ["auto", "minimal", "low", "medium", "high", "xhigh", "max"]
        )


    def _model_effort_preferences(self) -> dict[str, str]:
        raw = self._preferences.value("chat/model_efforts", "{}")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return {
            str(key): str(value).strip().casefold()
            for key, value in values.items()
            if str(key).strip() and str(value).strip()
        }


    def _model_effort_key(self) -> str:
        return f"{self._provider}:{self._model}"


    def _remember_model_effort(self, effort: str) -> None:
        value = str(effort or "").strip().casefold()
        if not value or not self._model:
            return
        if value == "ultra":
            value = "max"
        preferences = self._model_effort_preferences()
        preferences[self._model_effort_key()] = value
        self._preferences.setValue(
            "chat/model_efforts",
            json.dumps(preferences, ensure_ascii=False, sort_keys=True),
        )


    def _restore_effort_for_current_model(self) -> None:
        supported = [item["value"] for item in self.effortItems]
        if not supported:
            self._effort = ""
            return
        saved = self._model_effort_preferences().get(self._model_effort_key(), "")
        preferred = saved or self._effort or self._settings.default_effort
        if preferred == "ultra":
            preferred = "max"
        if preferred not in supported:
            concrete = [value for value in supported if value != "auto"]
            preferred = (
                "medium" if "medium" in concrete else (concrete or supported)[0]
            )
        self._effort = preferred


    def _load_cached_model_catalog(self) -> list[dict[str, Any]]:
        raw = self._preferences.value("chat/model_catalog_cache", "")
        if not raw:
            return []
        try:
            parsed = json.loads(str(raw)) if isinstance(raw, str) else list(raw or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list) or not parsed:
            return []
        enabled = set(self._enabled_provider_names())
        valid_items: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            prov = str(item.get("provider") or "")
            if prov in enabled and not item.get("inactive"):
                clean_item = dict(item)
                clean_item["favorite"] = (
                    str(clean_item.get("key") or "") in self._favorite_model_keys
                )
                valid_items.append(clean_item)
        return valid_items


    def _save_cached_model_catalog(self, items: list[dict[str, Any]]) -> None:
        clean = [
            {k: v for k, v in item.items() if k != "favorite"}
            for item in items
            if isinstance(item, dict) and not item.get("inactive")
        ]
        if clean:
            try:
                self._preferences.setValue(
                    "chat/model_catalog_cache",
                    json.dumps(clean, ensure_ascii=False),
                )
                self._preferences.sync()
            except Exception:
                pass


    def _reset_model_items(self) -> None:
        enabled = self._enabled_provider_names()
        provider = self._provider if self._provider in enabled else enabled[0]
        self._provider = provider

        cached = self._load_cached_model_catalog()
        if cached:
            current_key = f"{provider}:{self._model or '__default__'}"
            if not any(str(item.get("key") or "") == current_key for item in cached):
                label = self._model or PROVIDER_LABELS.get(provider, provider.title())
                provider_label = PROVIDER_LABELS.get(provider, provider.title())
                cached.insert(0, {
                    "label": label,
                    "displayName": label,
                    "value": self._model,
                    "provider": provider,
                    "providerLabel": provider_label,
                    "description": "Última seleção disponível",
                    "key": current_key,
                    "favorite": current_key in self._favorite_model_keys,
                })
            self._model_items = cached
            return

        items: list[dict[str, Any]] = []
        curr_label = self._model or PROVIDER_LABELS.get(provider, provider.title())
        curr_prov_label = PROVIDER_LABELS.get(provider, provider.title())
        curr_key = f"{provider}:{self._model or '__default__'}"
        items.append({
            "label": curr_label,
            "displayName": curr_label,
            "value": self._model,
            "provider": provider,
            "providerLabel": curr_prov_label,
            "description": "Última seleção disponível",
            "key": curr_key,
            "favorite": curr_key in self._favorite_model_keys,
        })
        for p in enabled:
            if p == provider:
                continue
            saved_m = str(self._preferences.value(f"chat/last_model/{p}", "") or "")
            p_label = PROVIDER_LABELS.get(p, p.title())
            d_name = saved_m or p_label
            p_key = f"{p}:{saved_m or '__default__'}"
            items.append({
                "label": f"{d_name} · {p_label}" if saved_m else p_label,
                "displayName": d_name,
                "value": saved_m,
                "provider": p,
                "providerLabel": p_label,
                "description": "Provedor habilitado",
                "key": p_key,
                "favorite": p_key in self._favorite_model_keys,
            })
        self._model_items = items


    def refreshModels(self) -> None:  # noqa: N802
        if self._model_catalog_loading:
            return
        self._model_catalog_loading = True
        self.stateChanged.emit()
        enabled_providers = tuple(self._enabled_provider_names())
        providers = dict(self._orchestrator.providers)
        results = self._model_catalog_results

        def fetch_provider_items(provider_name: str) -> list[dict[str, Any]]:
            provider = providers.get(provider_name)
            if provider is None:
                return []
            provider_label = PROVIDER_LABELS.get(provider_name, provider_name.title())
            try:
                models = provider.list_models() if provider.available() else []
            except Exception:
                models = []
            provider_items: list[dict[str, Any]] = []
            for raw in models:
                model_id = str(raw.get("id") or raw.get("model") or "").strip()
                if not model_id:
                    continue
                display_name = str(raw.get("displayName") or raw.get("display_name") or model_id)
                raw_limit = raw.get("limit") or raw.get("limits") or {}
                if not isinstance(raw_limit, dict):
                    raw_limit = {}
                context_window = next(
                    (
                        value
                        for value in (
                            raw.get("contextWindow"),
                            raw.get("context_window"),
                            raw.get("contextWindowTokens"),
                            raw.get("inputTokenLimit"),
                            raw_limit.get("context"),
                            raw_limit.get("contextWindow"),
                        )
                        if value not in (None, "")
                    ),
                    0,
                )
                provider_items.append({
                    "label": f"{display_name} · {provider_label}",
                    "displayName": display_name,
                    "value": model_id,
                    "provider": provider_name,
                    "providerLabel": provider_label,
                    "description": str(raw.get("description") or model_id),
                    "key": f"{provider_name}:{model_id}",
                    "efforts": raw.get("supportedReasoningEfforts") or raw.get("supported_reasoning_efforts") or [],
                    "aliases": raw.get("aliases") or [],
                    "serviceTiers": raw.get("serviceTiers") or raw.get("service_tiers") or [],
                    "contextWindow": context_window,
                })
            return provider_items

        def load() -> None:
            if not enabled_providers:
                results.put((set(), {}, True))
                return

            provider_results: dict[str, list[dict[str, Any]]] = {}
            remaining = len(enabled_providers)
            lock = threading.Lock()

            def worker(p_name: str) -> None:
                nonlocal remaining
                res = fetch_provider_items(p_name)
                with lock:
                    provider_results[p_name] = res
                    remaining -= 1
                    is_done = remaining == 0
                    results.put((set(provider_results.keys()), dict(provider_results), is_done))

            threads = [
                threading.Thread(target=worker, args=(p,), daemon=True)
                for p in enabled_providers
            ]
            for t in threads:
                t.start()

        self._model_catalog_poll_timer.start()
        threading.Thread(target=load, daemon=True).start()


    def _poll_model_catalog(self) -> None:
        latest: Any = None
        while True:
            try:
                latest = self._model_catalog_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            if not self._model_catalog_loading:
                self._model_catalog_poll_timer.stop()
            return
        if isinstance(latest, tuple) and len(latest) == 3:
            completed_providers, provider_items_map, is_done = latest
            enabled = tuple(self._enabled_provider_names())
            merged_items: list[dict[str, Any]] = []
            for p in enabled:
                if p in completed_providers:
                    merged_items.extend(provider_items_map.get(p, []))
                else:
                    existing = [
                        item for item in self._model_items
                        if item.get("provider") == p
                    ]
                    merged_items.extend(existing)
            self._apply_model_catalog(merged_items, is_final=bool(is_done))
        elif isinstance(latest, tuple) and len(latest) == 2:
            items, is_done = latest
            self._apply_model_catalog(items, is_final=bool(is_done))
        else:
            self._apply_model_catalog(latest, is_final=True)
        if not self._model_catalog_loading:
            self._model_catalog_poll_timer.stop()


    def _apply_model_catalog(self, values: object, is_final: bool = True) -> None:
        items = [dict(item) for item in list(values or []) if isinstance(item, dict)]
        enabled_providers = set(self._enabled_provider_names())
        if self._provider == "antigravity":
            equivalent = next((item for item in items
                               if item.get("provider") == "antigravity"
                               and self._model in item.get("aliases", [])), None)
            if equivalent is not None:
                self._model = str(equivalent["value"])
            for item in items:
                if item.get("provider") == "antigravity" and any(
                    f"antigravity:{alias}" in self._favorite_model_keys
                    for alias in item.get("aliases", [])
                ):
                    self._favorite_model_keys.add(item["key"])
        if self._draft and not self._model:
            preferred = next(
                (
                    item
                    for item in items
                    if item.get("provider") == self._provider
                    and str(item.get("value") or "")
                ),
                None,
            )
            if preferred is not None:
                self._model = str(preferred.get("value") or "")
                self._remember_current_chat_options()
        current_key = f"{self._provider}:{self._model or '__default__'}"
        if not any(str(item.get("key") or "") == current_key for item in items):
            current = self._model_items[self.modelIndex] if self._model_items else None
            if current:
                historical = dict(current)
                historical["inactive"] = self._provider not in enabled_providers
                items.insert(0, historical)
        if self._draft and self._provider not in enabled_providers and items:
            preferred = next(
                (item for item in items if not item.get("inactive")), items[0]
            )
            self._provider = str(
                preferred.get("provider") or next(iter(enabled_providers), "codex")
            )
            self._model = str(preferred.get("value") or "")
            self._remember_current_chat_options()
            items = [item for item in items if not item.get("inactive")]
        self._model_items = items or self._model_items
        self._restore_effort_for_current_model()
        if not self.serviceTierItems:
            self._service_tier = ""
        if is_final:
            self._model_catalog_loading = False
            self._save_cached_model_catalog(self._model_items)
        self.stateChanged.emit()


    def setModel(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._model_items) or self.turnRunning:
            return
        item = self._model_items[index]
        provider = str(item.get("provider") or "codex")
        model = str(item.get("value") or "")
        if (provider, model) == (self._provider, self._model):
            return
        conversation_id = str(self._selected.get("conversationId") or "")
        if conversation_id and any(
            str(row["role"] or "") == "user"
            for row in self._database.messages(conversation_id)
        ):
            self._status_text = "Modelo principal bloqueado após a primeira mensagem"
            self.stateChanged.emit()
            return
        previous_provider = self._provider
        previous_model = self._model
        previous_effort = self._effort
        self._provider = provider
        self._model = model
        self._restore_effort_for_current_model()
        try:
            if conversation_id:
                self._orchestrator.switch_provider(
                    conversation_id, provider, model, self._effort
                )
        except Exception as exc:
            self._provider = previous_provider
            self._model = previous_model
            self._effort = previous_effort
            self._status_text = f"Falha: {exc}"
            self.stateChanged.emit()
            return
        if not self.serviceTierItems:
            self._service_tier = ""
        self._remember_current_chat_options()
        self._status_text = "Pronto"
        self.refresh()
        self.stateChanged.emit()


    def toggleModelFavorite(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._model_items):
            return
        key = str(self._model_items[index].get("key") or "")
        if not key:
            return
        if key in self._favorite_model_keys:
            self._favorite_model_keys.remove(key)
        else:
            self._favorite_model_keys.add(key)
        self._preferences.setValue(
            "chat/favorite_models",
            json.dumps(sorted(self._favorite_model_keys), ensure_ascii=False),
        )
        self._preferences.sync()
        self.stateChanged.emit()


    def _load_favorite_model_keys(self) -> set[str]:
        raw = self._preferences.value("chat/favorite_models", "[]")
        try:
            values = json.loads(str(raw)) if isinstance(raw, str) else list(raw or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        return {str(value) for value in values if str(value).strip()}


    def refreshExtensions(self) -> None:  # noqa: N802
        self._extensions_generation += 1
        generation = self._extensions_generation
        self._extensions_loading = True
        self.stateChanged.emit()
        provider_name = self._provider
        workspace = (self._project_scope or self._settings.root).resolve(strict=False)
        orchestrator = self._orchestrator
        results = self._extension_catalog_results

        def load() -> None:
            values: list[dict[str, Any]] = []
            try:
                skill_result = orchestrator.skills(provider_name, workspace)
            except Exception:
                skill_result = {"skills": []}
            for item in skill_result.get("skills", []):
                name = str(item.get("name") or "")
                if not name:
                    continue
                values.append({
                    "key": f"skill:{name}:{item.get('path') or ''}",
                    "kind": "skill",
                    "name": str(item.get("displayName") or name),
                    "description": str(item.get("description") or item.get("scope") or "Skill"),
                    "payload": dict(item),
                })
            try:
                tools = orchestrator.mcp_tools(provider_name)
            except Exception:
                tools = []
            for item in tools:
                server = str(item.get("server") or "")
                tool = str(item.get("tool") or "")
                if not server:
                    continue
                values.append({
                    "key": f"mcp:{server}:{tool}",
                    "kind": "mcp",
                    "name": f"{server} · {tool or 'servidor'}",
                    "description": str(item.get("description") or item.get("serverDescription") or "MCP"),
                    "payload": {"server": server, "tool": tool},
                })
            results.put(
                {
                    "generation": generation,
                    "provider": provider_name,
                    "workspace": str(workspace),
                    "items": values,
                }
            )

        self._extension_catalog_poll_timer.start()
        threading.Thread(target=load, daemon=True).start()


    def _poll_extension_catalog(self) -> None:
        latest: dict[str, Any] | None = None
        while True:
            try:
                latest = self._extension_catalog_results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            if not self._extensions_loading:
                self._extension_catalog_poll_timer.stop()
            return
        self._apply_extension_catalog(latest)
        if not self._extensions_loading:
            self._extension_catalog_poll_timer.stop()


    def _apply_extension_catalog(self, values: object) -> None:
        payload = dict(values) if isinstance(values, dict) else {"items": values}
        generation = int(payload.get("generation") or self._extensions_generation)
        current_workspace = str(
            (self._project_scope or self._settings.root).resolve(strict=False)
        )
        if (
            generation != self._extensions_generation
            or str(payload.get("provider") or self._provider) != self._provider
            or str(payload.get("workspace") or current_workspace) != current_workspace
        ):
            return
        self._extension_items = [
            dict(item)
            for item in list(payload.get("items") or [])
            if isinstance(item, dict)
        ]
        available = {str(item.get("key") or "") for item in self._extension_items}
        self._selected_extension_keys.intersection_update(available)
        self._extensions_loading = False
        self.stateChanged.emit()


    def toggleExtension(self, index: int, selected: bool) -> None:  # noqa: N802
        if not 0 <= index < len(self._extension_items):
            return
        key = str(self._extension_items[index].get("key") or "")
        if selected:
            self._selected_extension_keys.add(key)
        else:
            self._selected_extension_keys.discard(key)
        self.stateChanged.emit()


    def setEffort(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self.effortItems):
            return
        self._effort = self.effortItems[index]["value"]
        self._preferences.setValue("chat/last_effort", self._effort)
        self._preferences.setValue("chat/default_effort", self._effort)
        self._remember_model_effort(self._effort)
        self._preferences.sync()
        if self._selected:
            self._database.update_conversation(
                str(self._selected["conversationId"]), effort=self._effort
            )
        self.stateChanged.emit()


    def setServiceTier(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self.serviceTierItems):
            return
        self._service_tier = self.serviceTierItems[index]["value"]
        self._preferences.setValue("chat/last_service_tier", self._service_tier)
        self._preferences.sync()
        if self._selected:
            self._database.update_conversation(
                str(self._selected["conversationId"]),
                service_tier=self._service_tier,
            )
        self.stateChanged.emit()


    def _load_research_config(self) -> None:
        raw_keys = self._preferences.value("research/model_pool", "[]")
        try:
            values = json.loads(str(raw_keys or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        self._research_model_keys = [
            str(item) for item in values if str(item or "").strip()
        ][:1]
        try:
            parallel = int(self._preferences.value("research/max_parallel", 3))
        except (TypeError, ValueError):
            parallel = 3
        self._research_max_parallel = max(1, min(3, parallel))
        self._code_analysis_enabled = self._stored_bool(
            self._preferences.value("research/code_analysis_enabled", False),
            False,
        )
        try:
            contexts = json.loads(str(self._preferences.value(
                self._workspace_research_preference("application_contexts"), "[]")))
            self._ultra_application_contexts = [dict(item) for item in contexts
                if isinstance(item, dict) and all(item.get(key) for key in
                    ("app_id", "version", "variant_id", "package_id"))] if isinstance(contexts, list) else []
        except (TypeError, ValueError):
            self._ultra_application_contexts = []
        if not self._ultra_application_contexts:
            self._code_analysis_enabled = False
        release_preference = self._workspace_research_preference(
            "code_analysis_release"
        )
        requested_release = str(
            self._preferences.value(
                release_preference,
                self._preferences.value("research/code_analysis_release", "current"),
            )
            or "current"
        ).strip() or "current"
        self._code_analysis_release = requested_release
        source_preference = self._workspace_research_preference(
            "code_analysis_jar_source"
        )
        requested_source = str(
            self._preferences.value(
                source_preference,
                ERP_JAR_SOURCE_VR_EXEC,
            )
            or ERP_JAR_SOURCE_VR_EXEC
        ).strip()
        self._code_analysis_jar_source = (
            requested_source
            if requested_source
            in {ERP_JAR_SOURCE_VR_EXEC, ERP_JAR_SOURCE_WORKSPACE, ERP_JAR_SOURCE_CUSTOM}
            else ERP_JAR_SOURCE_VR_EXEC
        )
        scope_preference = self._workspace_research_preference(
            "code_analysis_snapshot_scope"
        )
        requested_scope = str(
            self._preferences.value(
                scope_preference,
                ERP_JAR_SCOPE_FULL_RELEASE,
            )
            or ERP_JAR_SCOPE_FULL_RELEASE
        ).strip()
        self._code_analysis_snapshot_scope = (
            requested_scope
            if requested_scope in {ERP_JAR_SCOPE_FULL_RELEASE, ERP_JAR_SCOPE_SINGLE}
            else ERP_JAR_SCOPE_FULL_RELEASE
        )
        single_jar_preference = self._workspace_research_preference(
            "code_analysis_single_jar_path"
        )
        requested_single_jar = str(
            self._preferences.value(single_jar_preference, "") or ""
        ).strip()
        self._code_analysis_single_jar_path = (
            requested_single_jar
            if requested_single_jar.casefold().endswith(".jar")
            else ""
        )
        heap_preference = self._workspace_research_preference(
            "code_processing_max_heap_mb"
        )
        timeout_preference = self._workspace_research_preference(
            "code_processing_timeout_seconds"
        )
        cpu_preference = self._workspace_research_preference(
            "code_processing_max_cpu_cores"
        )
        hardware_profile_preference = self._workspace_research_preference(
            "code_processing_hardware_profile_version"
        )
        disk_preference = self._workspace_research_preference(
            "code_processing_disk_multiplier"
        )
        window_preference = self._workspace_research_preference(
            "code_processing_window"
        )
        global_heap = self._preferences.value(
            "code_processing/max_heap_mb", DEFAULT_CODE_PROCESSING_HEAP_MB
        )
        try:
            requested_heap = int(
                self._preferences.value(heap_preference, global_heap)
            )
        except (TypeError, ValueError):
            requested_heap = DEFAULT_CODE_PROCESSING_HEAP_MB
        global_timeout = self._preferences.value(
            "code_processing/timeout_seconds", DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS
        )
        try:
            requested_timeout = int(
                self._preferences.value(timeout_preference, global_timeout)
            )
        except (TypeError, ValueError):
            requested_timeout = DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS
        global_cpu = self._preferences.value(
            "code_processing/max_cpu_cores", DEFAULT_CODE_PROCESSING_CPU_CORES
        )
        try:
            requested_cpu = int(
                self._preferences.value(cpu_preference, global_cpu)
            )
        except (TypeError, ValueError):
            requested_cpu = DEFAULT_CODE_PROCESSING_CPU_CORES
        try:
            hardware_profile_version = int(
                self._preferences.value(hardware_profile_preference, 0)
            )
        except (TypeError, ValueError):
            hardware_profile_version = 0
        if hardware_profile_version < CODE_PROCESSING_HARDWARE_PROFILE_VERSION:
            requested_heap = DEFAULT_CODE_PROCESSING_HEAP_MB
            requested_cpu = DEFAULT_CODE_PROCESSING_CPU_CORES
        global_disk = self._preferences.value(
            "code_processing/disk_multiplier", DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER
        )
        try:
            requested_disk = int(
                self._preferences.value(disk_preference, global_disk)
            )
        except (TypeError, ValueError):
            requested_disk = DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER
        global_window = self._preferences.value(
            "code_processing/window", DEFAULT_CODE_PROCESSING_WINDOW
        )
        requested_window = str(
            self._preferences.value(window_preference, global_window)
            or DEFAULT_CODE_PROCESSING_WINDOW
        )
        self._code_processing_max_heap_mb = (
            requested_heap
            if requested_heap in CODE_PROCESSING_HEAP_OPTIONS
            else DEFAULT_CODE_PROCESSING_HEAP_MB
        )
        self._code_processing_timeout_seconds = (
            requested_timeout
            if requested_timeout in CODE_PROCESSING_TIMEOUT_OPTIONS
            else DEFAULT_CODE_PROCESSING_TIMEOUT_SECONDS
        )
        self._code_processing_max_cpu_cores = (
            requested_cpu
            if requested_cpu in CODE_PROCESSING_CPU_CORE_OPTIONS
            else DEFAULT_CODE_PROCESSING_CPU_CORES
        )
        self._code_processing_disk_multiplier = (
            requested_disk
            if requested_disk in CODE_PROCESSING_DISK_MULTIPLIER_OPTIONS
            else DEFAULT_CODE_PROCESSING_DISK_MULTIPLIER
        )
        available_windows = {
            str(item["value"]) for item in CODE_PROCESSING_WINDOW_OPTIONS
        }
        self._code_processing_window = (
            requested_window
            if requested_window in available_windows
            else DEFAULT_CODE_PROCESSING_WINDOW
        )
        self._refresh_code_analysis_releases()
        self._refresh_code_analysis_jar_sources()
        self._preferences.setValue(
            release_preference,
            self._code_analysis_release,
        )
        self._preferences.setValue(
            source_preference,
            self._code_analysis_jar_source,
        )
        self._preferences.setValue(
            scope_preference,
            self._code_analysis_snapshot_scope,
        )
        self._preferences.setValue(
            single_jar_preference,
            self._code_analysis_single_jar_path,
        )
        self._preferences.setValue(
            heap_preference,
            self._code_processing_max_heap_mb,
        )
        self._preferences.setValue(
            "code_processing/max_heap_mb",
            self._code_processing_max_heap_mb,
        )
        self._preferences.setValue(
            timeout_preference,
            self._code_processing_timeout_seconds,
        )
        self._preferences.setValue(
            "code_processing/timeout_seconds",
            self._code_processing_timeout_seconds,
        )
        self._preferences.setValue(
            cpu_preference,
            self._code_processing_max_cpu_cores,
        )
        self._preferences.setValue(
            "code_processing/max_cpu_cores",
            self._code_processing_max_cpu_cores,
        )
        self._preferences.setValue(
            hardware_profile_preference,
            CODE_PROCESSING_HARDWARE_PROFILE_VERSION,
        )
        self._preferences.setValue(
            disk_preference,
            self._code_processing_disk_multiplier,
        )
        self._preferences.setValue(
            "code_processing/disk_multiplier",
            self._code_processing_disk_multiplier,
        )
        self._preferences.setValue(window_preference, self._code_processing_window)
        self._preferences.setValue("code_processing/window", self._code_processing_window)
        try:
            ErpReleaseCatalog(
                self._settings.root,
                storage_budget_multiplier=self._code_processing_disk_multiplier,
            ).set_storage_budget_multiplier(
                self._code_processing_disk_multiplier, inspect_storage=False
            )
        except (ErpReleaseError, OSError, ValueError):
            pass
        if not self._code_analysis_release_items and self._code_analysis_enabled:
            self._code_analysis_enabled = False
            self._preferences.setValue("research/code_analysis_enabled", False)
        self._preferences.sync()
        self._senior_profile_enabled = self._stored_bool(
            self._preferences.value("research/senior_profile_enabled", False),
            False,
        )
        saved_mode = self._normalize_response_mode(
            self._preferences.value("research/response_mode", "auto")
        )
        self._vr_response_mode = saved_mode if self._senior_profile_enabled else "auto"


    def _apply_research_config(self) -> None:
        wanted = set(self._research_model_keys)
        pool = [
            ModelRef(
                provider=str(item.get("provider") or ""),
                model=str(item.get("value") or ""),
                display_name=str(item.get("label") or ""),
            )
            for item in self._model_items
            if str(item.get("key") or "") in wanted and item.get("provider")
        ]
        try:
            self._orchestrator.set_research_config(
                pool=pool,
                max_parallel=self._research_max_parallel,
            )
        except Exception:
            pass


    def setResearchModels(self, keys: list) -> None:  # noqa: N802
        selected: list[str] = []
        for item in keys:
            key = str(item or "").strip()
            if key:
                selected.append(key)
            if selected:
                break
        self._research_model_keys = selected
        self._preferences.setValue(
            "research/model_pool",
            json.dumps(self._research_model_keys),
        )
        self._preferences.sync()
        self._apply_research_config()
        self.stateChanged.emit()


    def setResearchMaxParallel(self, value: int) -> None:  # noqa: N802
        try:
            parallel = int(value)
        except (TypeError, ValueError):
            return
        self._research_max_parallel = max(1, min(3, parallel))
        self._preferences.setValue("research/max_parallel", self._research_max_parallel)
        self._preferences.sync()
        self._apply_research_config()
        self.stateChanged.emit()


    def _workspace_research_preference(self, name: str) -> str:
        identity = str(self._settings.root.resolve()).replace("\\", "/").casefold()
        workspace_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"research/workspaces/{workspace_id}/{name}"


    def resumeResearch(self, grant_budget: bool = False) -> None:  # noqa: N802
        run = self.resumableResearch
        if not run or self.turnRunning:
            return
        self._send_message("Retomar investigação" + (" (+15 chamadas, +300 s)" if grant_budget else ""),
                           resume_run_id=run["runId"], grant_budget=grant_budget)
