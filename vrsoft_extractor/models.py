from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .utils import stable_id


@dataclass
class VideoItem:
    area: str
    page_url: str
    media_url: str
    media_type: str
    lesson_title: str
    course: str = ""
    module: str = ""
    status: str = "found"
    local_path: str = ""
    error: str = ""
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = stable_id(self.area, self.page_url, self.media_url, self.lesson_title)

    @property
    def title(self) -> str:
        return self.lesson_title

    def dedupe_key(self) -> str:
        if self.media_url:
            return f"media:{self.media_url}"
        return f"page:{self.page_url}:{self.lesson_title}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoItem":
        return cls(
            area=str(data.get("area", "")),
            page_url=str(data.get("page_url", "")),
            media_url=str(data.get("media_url", "")),
            media_type=str(data.get("media_type", "unknown")),
            lesson_title=str(data.get("lesson_title") or data.get("title") or ""),
            course=str(data.get("course", "")),
            module=str(data.get("module", "")),
            status=str(data.get("status", "found")),
            local_path=str(data.get("local_path", "")),
            error=str(data.get("error", "")),
            discovered_at=str(data.get("discovered_at", "")),
            id=str(data.get("id", "")),
        )

