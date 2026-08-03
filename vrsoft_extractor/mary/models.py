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
class ConversationOptions:
    """Sticky runtime options shared by the UI, orchestrator and providers."""

    model: str = ""
    effort: str = "medium"
    service_tier: str = ""
    approval_profile: str = "auto"
    collaboration_mode: str = "default"
    dynamic_tools: tuple[dict[str, Any], ...] = ()
    mcp_tools: tuple[dict[str, str], ...] = ()

    @classmethod
    def from_mapping(cls, value: Any) -> "ConversationOptions":
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
