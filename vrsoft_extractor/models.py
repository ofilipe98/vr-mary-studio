from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .utils import resource_identity, stable_id


@dataclass
class VideoItem:
    area: str
    page_url: str
    media_url: str
    media_type: str
    lesson_title: str
    course: str = ""
    module: str = ""
    folder_path: list[str] = field(default_factory=list)
    source_course_id: str = ""
    source_chapter_id: str = ""
    source_task_id: str = ""
    source_file_id: str = ""
    source_order: int = 0
    business_module: str = "Revisar"
    classification_confidence: float = 0.0
    classification_status: str = "pending"
    classification_reasons: list[str] = field(default_factory=list)
    classification_source: str = "automatic"
    status: str = "found"
    local_path: str = ""
    error: str = ""
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    id: str = ""

    def __post_init__(self) -> None:
        if not self.folder_path:
            if self.area == "curso":
                self.folder_path = [value for value in (self.course, self.module) if value]
            else:
                self.folder_path = [value for value in (self.course, *self._legacy_module_parts()) if value]
        if not self.id:
            self.id = stable_id(self.dedupe_key())

    @property
    def title(self) -> str:
        return self.lesson_title

    def dedupe_key(self) -> str:
        media_key = resource_identity(self.media_url)
        if self.area == "curso" and (self.source_course_id or self.source_task_id):
            return f"course:{self.source_course_id}:task:{self.source_task_id}:media:{media_key}"
        if self.area == "biblioteca" and self.source_file_id:
            return f"file:{self.source_file_id}:media:{media_key}"
        return f"item:{self.area}:{resource_identity(self.page_url)}:{media_key}"

    def compatibility_key(self) -> str:
        """Identity shared by legacy and source-ID aware inventories."""
        return (
            f"legacy:{self.area}:{resource_identity(self.page_url)}:"
            f"{resource_identity(self.media_url)}"
        )

    def group_key(self) -> str:
        if self.area == "curso":
            return f"course:{self.source_course_id or self.course.casefold()}"
        path = self.folder_path or [self.course]
        return "folder:" + "/".join(part.casefold() for part in path)

    def _legacy_module_parts(self) -> list[str]:
        return [part.strip() for part in self.module.split(" / ") if part.strip()]

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
            folder_path=[str(value) for value in data.get("folder_path", []) if str(value).strip()]
            if isinstance(data.get("folder_path", []), list)
            else [],
            source_course_id=str(data.get("source_course_id", "")),
            source_chapter_id=str(data.get("source_chapter_id", "")),
            source_task_id=str(data.get("source_task_id", "")),
            source_file_id=str(data.get("source_file_id", "")),
            source_order=int(data.get("source_order", 0) or 0),
            business_module=str(data.get("business_module", "Revisar")),
            classification_confidence=float(data.get("classification_confidence", 0.0) or 0.0),
            classification_status=str(data.get("classification_status", "pending")),
            classification_reasons=[str(value) for value in data.get("classification_reasons", [])]
            if isinstance(data.get("classification_reasons", []), list)
            else [],
            classification_source=str(data.get("classification_source", "automatic")),
            status=str(data.get("status", "found")),
            local_path=str(data.get("local_path", "")),
            error=str(data.get("error", "")),
            discovered_at=str(data.get("discovered_at", "")),
            id=str(data.get("id", "")),
        )
