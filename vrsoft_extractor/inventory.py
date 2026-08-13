from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path
from typing import Iterable

from .models import VideoItem


CSV_FIELDS = [
    "id",
    "area",
    "course",
    "module",
    "folder_path",
    "source_course_id",
    "source_chapter_id",
    "source_task_id",
    "source_file_id",
    "source_order",
    "business_module",
    "classification_confidence",
    "classification_status",
    "classification_reasons",
    "classification_source",
    "lesson_title",
    "page_url",
    "media_url",
    "media_type",
    "status",
    "local_path",
    "error",
    "discovered_at",
]


def load_inventory(path: Path) -> list[VideoItem]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Inventario invalido: {path}")
    return [VideoItem.from_dict(item) for item in data]


def save_inventory(items: Iterable[VideoItem], json_path: Path, csv_path: Path) -> None:
    item_list = list(items)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    json_temporary = json_path.with_suffix(json_path.suffix + f".{token}.tmp")
    csv_temporary = csv_path.with_suffix(csv_path.suffix + f".{token}.tmp")
    backups: dict[Path, Path] = {}
    committed = False
    try:
        json_temporary.write_text(
            json.dumps(
                [item.to_dict() for item in item_list],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        with csv_temporary.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for item in item_list:
                row = item.to_dict()
                row["folder_path"] = json.dumps(item.folder_path, ensure_ascii=False)
                row["classification_reasons"] = json.dumps(
                    item.classification_reasons, ensure_ascii=False
                )
                writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
        for target in (json_path, csv_path):
            if target.exists():
                backup = target.with_suffix(target.suffix + f".{token}.bak")
                target.replace(backup)
                backups[target] = backup
        try:
            json_temporary.replace(json_path)
            csv_temporary.replace(csv_path)
        except Exception:
            for target in (json_path, csv_path):
                target.unlink(missing_ok=True)
            for target, backup in backups.items():
                if backup.exists():
                    backup.replace(target)
            raise
        committed = True
    finally:
        json_temporary.unlink(missing_ok=True)
        csv_temporary.unlink(missing_ok=True)
        if committed:
            for backup in backups.values():
                backup.unlink(missing_ok=True)


def merge_inventory(existing: Iterable[VideoItem], discovered: Iterable[VideoItem]) -> list[VideoItem]:
    merged: dict[str, VideoItem] = {}
    existing_by_compatibility: dict[str, VideoItem] = {}
    for item in existing:
        merged[item.dedupe_key()] = item
        existing_by_compatibility[item.compatibility_key()] = item
    for item in discovered:
        key = item.dedupe_key()
        previous = merged.get(key) or existing_by_compatibility.get(
            item.compatibility_key()
        )
        if previous:
            previous_key = previous.dedupe_key()
            if previous_key != key:
                merged.pop(previous_key, None)
            if previous.status in {"downloaded", "skipped"}:
                item.status = previous.status
                item.local_path = previous.local_path
                item.error = previous.error
            if previous.classification_source.startswith("manual"):
                item.business_module = previous.business_module
                item.classification_confidence = 1.0
                item.classification_status = "approved"
                item.classification_reasons = list(previous.classification_reasons)
                item.classification_source = previous.classification_source
        merged[key] = item
    return sorted(
        merged.values(),
        key=lambda item: (item.area, item.course, item.module, item.lesson_title, item.media_url),
    )
