from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .mary.classifier import classify
from .models import VideoItem


BUSINESS_MODULES = ("Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar")
LESSON_OVERRIDE_CONFIDENCE = 0.90


def load_module_overrides(path: Path | None) -> dict[str, dict[str, str]]:
    empty = {"groups": {}, "items": {}}
    if path is None or not path.exists():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    result: dict[str, dict[str, str]] = {"groups": {}, "items": {}}
    for section in result:
        values = raw.get(section, {})
        if not isinstance(values, dict):
            continue
        result[section] = {
            str(key): str(value)
            for key, value in values.items()
            if str(value) in BUSINESS_MODULES
        }
    return result


def save_module_override(
    path: Path,
    *,
    key: str,
    module: str,
    scope: str,
) -> None:
    if module not in BUSINESS_MODULES:
        raise ValueError(f"Modulo de negocio invalido: {module}")
    if scope not in {"groups", "items"}:
        raise ValueError(f"Escopo de classificacao invalido: {scope}")
    values = load_module_overrides(path)
    values[scope][key] = module
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(values, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def classify_inventory(
    items: Iterable[VideoItem],
    overrides_path: Path | None = None,
) -> list[VideoItem]:
    rows = list(items)
    overrides = load_module_overrides(overrides_path)
    grouped: dict[str, list[VideoItem]] = defaultdict(list)
    for item in rows:
        grouped[item.group_key()].append(item)

    for group_key, members in grouped.items():
        group_override = overrides["groups"].get(group_key)
        group_result = _classify_group(members)
        for item in members:
            item_override = overrides["items"].get(item.dedupe_key())
            if item_override:
                _assign_manual(item, item_override, "manual_item")
                continue
            if group_override:
                _assign_manual(item, group_override, "manual_group")
                continue

            lesson_result = _classify_lesson(item)
            if group_result.status == "approved":
                if (
                    lesson_result.status == "approved"
                    and lesson_result.confidence >= LESSON_OVERRIDE_CONFIDENCE
                    and lesson_result.module != group_result.module
                ):
                    _assign_result(item, lesson_result, "lesson_exception")
                else:
                    _assign_result(item, group_result, "course_inherited")
            elif lesson_result.status == "approved":
                _assign_result(item, lesson_result, "lesson_automatic")
            else:
                item.business_module = "Revisar"
                item.classification_confidence = max(
                    group_result.confidence, lesson_result.confidence
                )
                item.classification_status = "pending"
                item.classification_reasons = _unique(
                    [*group_result.reasons, *lesson_result.reasons]
                )[:7]
                item.classification_source = "automatic_review"
    return rows


def _classify_group(items: list[VideoItem]):
    first = items[0]
    if first.area == "curso":
        title = first.course or (first.folder_path[0] if first.folder_path else "")
        chapters = " ".join(
            sorted({item.module for item in items if item.module})
        )
        return classify(
            title,
            chapters,
            product=_video_product(title),
        )

    folder_path = first.folder_path or [first.course]
    title = folder_path[-1] if folder_path else first.course
    context = " ".join(folder_path)
    return classify(title, context, product=_video_product(title))


def _classify_lesson(item: VideoItem):
    hierarchy = " ".join(item.folder_path)
    product = item.course if item.area == "curso" else (
        item.folder_path[-1] if item.folder_path else item.course
    )
    return classify(
        item.lesson_title,
        f"{item.course} {item.module} {hierarchy}",
        product=_video_product(product),
    )


def _video_product(value: str) -> str:
    return re.sub(
        r"^(?:curso|treinamento|capacitacao|capacitação)\s+(?:de\s+)?",
        "",
        value or "",
        flags=re.IGNORECASE,
    ).strip()


def _assign_manual(item: VideoItem, module: str, source: str) -> None:
    item.business_module = module
    item.classification_confidence = 1.0
    item.classification_status = "approved"
    item.classification_reasons = [f"classificacao manual: {module}"]
    item.classification_source = source


def _assign_result(item: VideoItem, result, source: str) -> None:
    item.business_module = result.module
    item.classification_confidence = float(result.confidence)
    item.classification_status = result.status
    item.classification_reasons = list(result.reasons)
    item.classification_source = source


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
