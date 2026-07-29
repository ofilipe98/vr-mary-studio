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
