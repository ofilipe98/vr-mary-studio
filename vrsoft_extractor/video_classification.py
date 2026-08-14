from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .mary.classifier import classify, explicit_module_category
from .models import VideoItem


BUSINESS_MODULES = ("Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar")
LESSON_OVERRIDE_CONFIDENCE = 0.90


def load_module_overrides(path: Path | None) -> dict[str, dict[str, str]]:
    empty: dict[str, dict[str, str]] = {"groups": {}, "items": {}}
    if path is None or not path.exists():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Arquivo de classificações manuais inválido: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Arquivo de classificações manuais inválido: {path}")
    result: dict[str, dict[str, str]] = {"groups": {}, "items": {}}
    for section in result:
        values = raw.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(
                f"Seção '{section}' inválida nas classificações manuais: {path}"
            )
        invalid = [value for value in values.values() if str(value) not in BUSINESS_MODULES]
        if invalid:
            raise ValueError(
                f"Módulo inválido nas classificações manuais: {invalid[0]}"
            )
        result[section] = {str(key): str(value) for key, value in values.items()}
    return result


def save_module_override(
    path: Path,
    *,
    key: str,
    module: str,
    scope: str,
) -> None:
    save_module_overrides(path, [(scope, key, module)])


def save_module_overrides(
    path: Path,
    updates: Iterable[tuple[str, str, str]],
) -> None:
    normalized = [(str(scope), str(key), str(module)) for scope, key, module in updates]
    if not normalized:
        return
    for scope, key, module in normalized:
        if module not in BUSINESS_MODULES:
            raise ValueError(f"Modulo de negocio invalido: {module}")
        if scope not in {"groups", "items"}:
            raise ValueError(f"Escopo de classificacao invalido: {scope}")
        if not key.strip():
            raise ValueError("Chave de classificacao manual vazia.")
    values = load_module_overrides(path)
    for scope, key, module in normalized:
        values[scope][key] = module
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
    category = explicit_module_category(
        part
        for item in items
        for part in (item.course, item.module, *item.folder_path)
    )
    if first.area == "curso":
        title = first.course or (first.folder_path[0] if first.folder_path else "")
        chapters = " ".join(
            sorted({item.module for item in items if item.module})
        )
        return classify(
            title,
            chapters,
            category=category,
            product=_video_product(title),
        )

    folder_path = first.folder_path or [first.course]
    title = folder_path[-1] if folder_path else first.course
    context = " ".join(folder_path)
    return classify(
        title,
        context,
        category=category,
        product=_video_product(title),
    )


def _classify_lesson(item: VideoItem):
    hierarchy = " ".join(item.folder_path)
    category = explicit_module_category(
        (item.course, item.module, *item.folder_path)
    )
    product = item.course if item.area == "curso" else (
        item.folder_path[-1] if item.folder_path else item.course
    )
    return classify(
        item.lesson_title,
        f"{item.course} {item.module} {hierarchy}",
        category=category,
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
