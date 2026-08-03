from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .auth import ensure_session
from .scanner import API_BASE_URL, MediaRecorder
from .settings import ConfigError, Settings, ensure_runtime_dirs


LOGGER = logging.getLogger(__name__)
COURSE_REGISTER_URL = f"{API_BASE_URL}/courses/register"


@dataclass
class CourseClass:
    id: str
    name: str = ""
    date_start: str = ""
    date_end: str = ""


@dataclass
class CourseCatalogItem:
    course_id: str
    name: str
    status: str
    reason: str = ""
    participant_id: str = ""
    application_method: str = ""
    selected_class_id: str = ""
    classes: list[CourseClass] = field(default_factory=list)
    business_module: str = "Revisar"
    classification_confidence: float = 0.0
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def selectable(self) -> bool:
        return self.status == "available" and bool(self.selected_class_id)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["selectable"] = self.selectable
        return value


def load_course_catalog(path: Path) -> list[CourseCatalogItem]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    result: list[CourseCatalogItem] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        classes = [
            CourseClass(
                id=str(value.get("id", "")),
                name=str(value.get("name") or value.get("cod") or ""),
                date_start=str(value.get("date_start") or ""),
                date_end=str(value.get("date_end") or ""),
            )
            for value in row.get("classes", [])
            if isinstance(value, dict) and value.get("id")
        ]
        result.append(
            CourseCatalogItem(
                course_id=str(row.get("course_id", "")),
                name=str(row.get("name", "")),
                status=str(row.get("status", "unavailable")),
                reason=str(row.get("reason", "")),
                participant_id=str(row.get("participant_id", "")),
                application_method=str(row.get("application_method", "")),
                selected_class_id=str(row.get("selected_class_id", "")),
                classes=classes,
                business_module=str(row.get("business_module", "Revisar")),
                classification_confidence=float(row.get("classification_confidence", 0.0) or 0.0),
                discovered_at=str(row.get("discovered_at", "")),
            )
        )
    return result


def save_course_catalog(items: Iterable[CourseCatalogItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def course_from_payload(summary: dict[str, Any], detail: dict[str, Any]) -> CourseCatalogItem:
    course_id = str(detail.get("id") or summary.get("id") or "")
    name = str(detail.get("name") or summary.get("name") or f"Curso {course_id}")
    participant = detail.get("participant") or summary.get("participant") or {}
    from .mary.classifier import classify

    classification = classify(name, "", product=name)
    business_module = (
        classification.module if classification.status == "approved" else "Revisar"
    )
    if isinstance(participant, dict) and participant.get("id"):
        return CourseCatalogItem(
            course_id=course_id,
            name=name,
            status="enrolled",
            reason="Inscricao ativa",
            participant_id=str(participant.get("id")),
            application_method=str(detail.get("application_method") or ""),
            selected_class_id=str(participant.get("course_class_id") or ""),
            business_module=business_module,
            classification_confidence=classification.confidence,
        )

    application_method = str(detail.get("application_method") or "")
    classes = _available_classes(detail)
    if application_method == "3":
        status = "waitlist"
        reason = "Curso sujeito a fila de espera"
    elif classes:
        status = "available"
        reason = "Inscricao imediata disponivel"
    else:
        status = "unavailable"
        reason = "Nenhuma turma aberta"
    return CourseCatalogItem(
        course_id=course_id,
        name=name,
        status=status,
        reason=reason,
        application_method=application_method,
        selected_class_id=classes[0].id if classes else "",
        classes=classes,
        business_module=business_module,
        classification_confidence=classification.confidence,
    )


def refresh_courses(settings: Settings, *, headless: bool = True) -> list[CourseCatalogItem]:
    ensure_runtime_dirs(settings)
    ensure_session(settings, headless=headless)
    from .runtime import configure_playwright_runtime

    configure_playwright_runtime()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ConfigError("Playwright nao esta instalado") from exc

    items: list[CourseCatalogItem] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(settings.storage_state_path))
        page = context.new_page()
        recorder = MediaRecorder()
        page.on("request", recorder.request_handler)
        page.goto(f"{settings.base_url}/cursos", wait_until="domcontentloaded")
        page.wait_for_timeout(1_500)
        if not recorder.api_headers:
            browser.close()
            raise ConfigError("Sessao Endoo expirada. Execute Login antes de atualizar cursos.")

        for summary in _iter_course_summaries(
            lambda url: _request_json(page, recorder.api_headers, url),
            settings.max_pages_per_section,
        ):
            participant = summary.get("participant") or {}
            detail: dict[str, Any] = summary
            if not (isinstance(participant, dict) and participant.get("id")):
                loaded = _request_json(
                    page,
                    recorder.api_headers,
                    f"{API_BASE_URL}/courses/{summary.get('id')}/0",
                )
                if isinstance(loaded, dict):
                    detail = loaded
            items.append(course_from_payload(summary, detail))
        browser.close()

    items.sort(key=lambda item: item.name.casefold())
    save_course_catalog(items, settings.courses_json_path)
    LOGGER.info(
        "Catalogo salvo com %s cursos (%s disponiveis)",
        len(items),
        sum(item.selectable for item in items),
    )
    return items


def enroll_courses(
    settings: Settings,
    selections: Iterable[tuple[str, str]],
    *,
    confirmed: bool,
    scan_after: bool = False,
) -> dict[str, Any]:
    if not confirmed:
        raise ConfigError("Inscricao cancelada: use --confirm apos revisar os cursos.")
    pairs = [(str(course_id), str(class_id)) for course_id, class_id in selections]
    if not pairs:
        raise ConfigError("Nenhum curso selecionado para inscricao.")

    ensure_runtime_dirs(settings)
    ensure_session(settings, headless=True)
    from .runtime import configure_playwright_runtime

    configure_playwright_runtime()
    from playwright.sync_api import sync_playwright

    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(settings.storage_state_path))
        page = context.new_page()
        recorder = MediaRecorder()
        page.on("request", recorder.request_handler)
        page.goto(f"{settings.base_url}/cursos", wait_until="domcontentloaded")
        page.wait_for_timeout(1_500)
        if not recorder.api_headers:
            browser.close()
            raise ConfigError("Sessao Endoo expirada. Execute Login antes de inscrever.")

        for course_id, class_id in pairs:
            result = _enroll_one(page, recorder.api_headers, course_id, class_id)
            results.append(result)
            LOGGER.info(
                "[Cursos] Inscricao %s: %s",
                "confirmada" if result["success"] else "nao realizada",
                result["message"],
            )
        browser.close()

    successful = sum(bool(result["success"]) for result in results)
    refresh_courses(settings, headless=True)
    if scan_after and successful:
        from .scanner import scan

        scan(settings, headless=True)
    return {"selected": len(pairs), "successful": successful, "results": results}


def parse_course_selections(values: Iterable[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for value in values:
        course_id, separator, class_id = str(value).partition(":")
        if not separator or not course_id.isdigit() or not class_id.isdigit():
            raise ConfigError(
                f"Selecao invalida '{value}'. Use o formato CURSO:TURMA."
            )
        result.append((course_id, class_id))
    return result


def _enroll_one(page, headers: dict[str, str], course_id: str, class_id: str) -> dict[str, Any]:
    detail = _request_json(page, headers, f"{API_BASE_URL}/courses/{course_id}/0")
    if not isinstance(detail, dict):
        return _result(course_id, class_id, False, "Detalhe do curso indisponivel")
    participant = detail.get("participant") or {}
    if isinstance(participant, dict) and participant.get("id"):
        return _result(course_id, class_id, False, "Curso ja inscrito")
    candidate = course_from_payload(detail, detail)
    if not candidate.selectable:
        return _result(course_id, class_id, False, candidate.reason)
    if class_id not in {row.id for row in candidate.classes}:
        return _result(course_id, class_id, False, "Turma nao esta mais disponivel")

    response = page.request.post(
        COURSE_REGISTER_URL,
        headers=headers,
        data={"id": int(course_id), "class_id": int(class_id)},
    )
    if response.status < 200 or response.status >= 300:
        return _result(course_id, class_id, False, f"API retornou HTTP {response.status}")
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict) or "redirect" not in payload:
        return _result(course_id, class_id, False, "Resposta de inscricao nao confirmada")

    for _attempt in range(3):
        page.wait_for_timeout(500)
        verified = _request_json(page, headers, f"{API_BASE_URL}/courses/{course_id}/0")
        participant = verified.get("participant") if isinstance(verified, dict) else None
        if isinstance(participant, dict) and participant.get("id"):
            return _result(course_id, class_id, True, "Inscricao confirmada")
    return _result(
        course_id,
        class_id,
        False,
        "API aceitou a solicitacao, mas a inscricao ainda nao foi confirmada",
    )


def _result(course_id: str, class_id: str, success: bool, message: str) -> dict[str, Any]:
    return {
        "course_id": course_id,
        "class_id": class_id,
        "success": success,
        "message": message,
    }


def _iter_course_summaries(
    get_json: Callable[[str], Any],
    max_pages: int,
):
    page_index = 0
    while page_index < max_pages:
        url = (
            f"{API_BASE_URL}/courses/student/?items=&filter=all&status=all"
            f"&category_id=all&class_status=all&shelf=0&include_training_courses=0"
            f"&order=created_at&position=0&limit=8&page={page_index}&required=0"
        )
        data = get_json(url)
        if not isinstance(data, list) or not data:
            break
        yield from (row for row in data if isinstance(row, dict))
        page_index += 1


def _available_classes(detail: dict[str, Any]) -> list[CourseClass]:
    raw = detail.get("available_classes") or []
    if isinstance(raw, dict):
        raw = raw.get("data") or []
    if not isinstance(raw, list):
        raw = []
    current = detail.get("current_class")
    if not raw and isinstance(current, dict):
        raw = [current]
    result = [
        CourseClass(
            id=str(value.get("id")),
            name=str(value.get("name") or value.get("cod") or ""),
            date_start=str(value.get("date_start") or ""),
            date_end=str(value.get("date_end") or ""),
        )
        for value in raw
        if isinstance(value, dict)
        and value.get("id")
        and value.get("closed") in (None, 0, "0", False)
    ]
    return sorted(result, key=lambda value: (value.date_start, value.id))


def _request_json(page, headers: dict[str, str], url: str) -> Any:
    response = page.request.get(url, headers=headers)
    if response.status < 200 or response.status >= 300:
        return {}
    try:
        return response.json()
    except Exception:
        return {}
