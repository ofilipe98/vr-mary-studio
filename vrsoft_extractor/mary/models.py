from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Classification:
    module: str
    confidence: float
    status: str
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewFilters:
    query: str = ""
    source: str = ""
    current_module: str = ""
    suggested_module: str = ""
    confidence_band: str = ""
    product: str = ""
    category: str = ""
    status: str = "pending"
    period_days: int = 0
    special: str = ""
    sort: str = "risk"
    limit: int = 100
    offset: int = 0


@dataclass
class ReviewPage:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0


@dataclass
class KnowledgeDocument:
    source: str
    source_id: str
    title: str
    url: str
    html: str = ""
    markdown: str = ""
    module: str = "Revisar"
    classification_confidence: float = 0.0
    review_status: str = "pending"
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    synced_at: str = field(default_factory=utc_now)
    revision: str = ""
    content_hash: str = ""
    category: str = ""
    product: str = ""
    assets: list[str] = field(default_factory=list)
    ocr_text: str = ""
    local_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyncStats:
    source: str
    discovered: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    inactive: int = 0
    errors: int = 0
    review: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeEvent:
    conversation_id: str
    kind: str
    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ModelRef:
    """Provider-qualified model identity used by the VR scheduler."""

    provider: str
    model: str
    display_name: str = ""
    description: str = ""
    capabilities: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model or '__default__'}"

    @classmethod
    def from_mapping(cls, value: Any) -> "ModelRef":
        get = value.get if hasattr(value, "get") else lambda _key, default="": default
        raw_capabilities = get("capabilities", ()) or ()
        if isinstance(raw_capabilities, str):
            raw_capabilities = (raw_capabilities,)
        return cls(
            provider=str(get("provider", "") or "").strip().casefold(),
            model=str(get("model", get("model_id", "")) or "").strip(),
            display_name=str(
                get("display_name", get("displayName", "")) or ""
            ).strip(),
            description=str(get("description", "") or "").strip(),
            capabilities=tuple(
                str(item).strip()
                for item in raw_capabilities
                if str(item).strip()
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "display_name": self.display_name,
            "description": self.description,
            "capabilities": list(self.capabilities),
        }


ORCHESTRATION_STRATEGIES = {
    "automatic",
    "parallel",
    "specialized",
    "sequential",
    "debate",
    "consensus",
    "adaptive",
}

ORCHESTRATION_MODES = {"off", "automatic", "standard", "ultra"}


@dataclass(frozen=True)
class OrchestrationOptions:
    """Sticky VR routing options, kept separate from provider settings."""

    enabled: bool = False
    strategy: str = "automatic"
    model_pool: tuple[ModelRef, ...] = ()
    ultra: bool = False
    mode: str = ""
    show_execution: bool = True
    explain_routing: bool = False
    dynamic_model_routing: bool = True
    dynamic_agent_count: bool = True
    difficulty_routing: bool = True

    def __post_init__(self) -> None:
        mode = str(self.mode or "").strip().casefold()
        if mode not in ORCHESTRATION_MODES:
            mode = "ultra" if self.ultra else "automatic" if self.enabled else "off"
        object.__setattr__(self, "mode", mode)
        # Keep the legacy booleans coherent for providers and older callers.
        object.__setattr__(self, "enabled", mode != "off")
        object.__setattr__(self, "ultra", mode == "ultra")

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        model_pool: tuple[ModelRef, ...] | list[ModelRef] = (),
    ) -> "OrchestrationOptions":
        keys = value.keys() if hasattr(value, "keys") else ()
        get = value.__getitem__ if hasattr(value, "__getitem__") else lambda _key: ""

        def boolean(name: str, default: bool) -> bool:
            if name not in keys:
                return default
            raw = get(name)
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, (int, float)):
                return bool(raw)
            return str(raw).strip().casefold() not in {"", "0", "false", "no", "off"}

        strategy = (
            str(get("orchestration_strategy") or "automatic")
            if "orchestration_strategy" in keys
            else "automatic"
        ).strip().casefold()
        if strategy not in ORCHESTRATION_STRATEGIES:
            strategy = "automatic"
        enabled = boolean("orchestration_enabled", False)
        ultra = boolean("ultra_enabled", False)
        mode = (
            str(get("orchestration_mode") or "").strip().casefold()
            if "orchestration_mode" in keys
            else ""
        )
        return cls(
            enabled=enabled,
            strategy=strategy,
            model_pool=tuple(model_pool),
            ultra=ultra,
            mode=mode,
            show_execution=boolean("show_execution", True),
            explain_routing=boolean("explain_routing", False),
            dynamic_model_routing=boolean("dynamic_model_routing", True),
            dynamic_agent_count=boolean("dynamic_agent_count", True),
            difficulty_routing=boolean("difficulty_routing", True),
        )


@dataclass(frozen=True)
class ConversationOptions:
    """Sticky runtime options shared by the UI, orchestrator and providers."""

    model: str = ""
    effort: str = "medium"
    service_tier: str = ""
    approval_profile: str = "auto"
    collaboration_mode: str = "default"
    dynamic_tools: tuple[dict[str, Any], ...] = ()
    mcp_tools: tuple[dict[str, str], ...] = ()
    orchestration: OrchestrationOptions = field(default_factory=OrchestrationOptions)

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        model_pool: tuple[ModelRef, ...] | list[ModelRef] = (),
    ) -> "ConversationOptions":
        keys = value.keys() if hasattr(value, "keys") else ()
        get = value.__getitem__ if hasattr(value, "__getitem__") else lambda _key: ""

        def field_value(name: str, default: str = "") -> str:
            return str(get(name) if name in keys else default)

        return cls(
            model=field_value("model"),
            effort=field_value("effort", "medium") or "medium",
            service_tier=field_value("service_tier"),
            approval_profile=field_value("approval_profile", "auto") or "auto",
            collaboration_mode=field_value("collaboration_mode", "default") or "default",
            orchestration=OrchestrationOptions.from_mapping(value, model_pool),
        )


@dataclass(frozen=True)
class ApprovalPreset:
    id: str
    label: str
    description: str
    sandbox: str
    sandbox_policy_type: str
    approval_policy: str
    reviewer: str = "user"


APPROVAL_PRESETS: dict[str, ApprovalPreset] = {
    "supervised": ApprovalPreset(
        "supervised",
        "Supervisionado",
        "Perguntar antes de comandos e alterações de arquivo.",
        "read-only",
        "readOnly",
        "on-request",
    ),
    "auto_edits": ApprovalPreset(
        "auto_edits",
        "Aceitar edições",
        "Aceitar edições e perguntar antes das demais ações.",
        "workspace-write",
        "workspaceWrite",
        "untrusted",
    ),
    "auto": ApprovalPreset(
        "auto",
        "Auto",
        "O revisor do Codex decide ações rotineiras e pergunta nas arriscadas.",
        "workspace-write",
        "workspaceWrite",
        "on-request",
        "auto_review",
    ),
    "full_access": ApprovalPreset(
        "full_access",
        "Acesso completo",
        "Permitir comandos, internet e arquivos sem solicitar aprovação.",
        "danger-full-access",
        "dangerFullAccess",
        "never",
    ),
}


def approval_preset(profile: str) -> ApprovalPreset:
    return APPROVAL_PRESETS.get(str(profile), APPROVAL_PRESETS["auto"])
