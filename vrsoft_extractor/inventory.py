from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .models import VideoItem


CSV_FIELDS = [
    "id",
    "area",
    "course",
    "module",
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
    json_path.write_text(
        json.dumps([item.to_dict() for item in item_list], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in item_list:
            row = item.to_dict()
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def merge_inventory(existing: Iterable[VideoItem], discovered: Iterable[VideoItem]) -> list[VideoItem]:
    merged: dict[str, VideoItem] = {}
    for item in existing:
        merged[item.dedupe_key()] = item
    for item in discovered:
        key = item.dedupe_key()
        previous = merged.get(key)
        if previous and previous.status in {"downloaded", "skipped"}:
            item.status = previous.status
            item.local_path = previous.local_path
            item.error = previous.error
        merged[key] = item
    return sorted(
        merged.values(),
        key=lambda item: (item.area, item.course, item.module, item.lesson_title, item.media_url),
    )

