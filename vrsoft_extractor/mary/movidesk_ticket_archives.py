"""Read-only intake for Movidesk ticket pages archived as ZIP files."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from bs4 import BeautifulSoup

from .classifier import classify
from .code_analysis_benchmark import (
    redact_benchmark_sensitive_text,
    sensitive_text_findings,
)
from .models import utc_now


ARCHIVE_SCHEMA_VERSION = 1
MAX_ARCHIVE_ENTRIES = 5_000
MAX_HTML_BYTES = 20 * 1024 * 1024
SIGNAL_TERMS = {
    "fix_confirmed": (
        "corrigido",
        "corrigida",
        "ajustado",
        "ajustada",
        "resolvido",
        "resolvida",
        "normalizado",
        "normalizada",
    ),
    "code": (
        "bug",
        "código",
        "classe",
        "método",
        "stack trace",
        "exception",
        "nullpointer",
        "desenvolvimento",
        "versão",
        "build",
        "jar",
    ),
    "data": (
        "banco",
        "sql",
        "script",
        "tabela",
        "campo",
        "registro",
        "update",
        "insert",
        "delete",
        "select",
    ),
    "configuration": (
        "configuração",
        "configurar",
        "configurado",
        "parâmetro",
        "cadastro",
        "permissão",
    ),
    "workaround": (
        "contorno",
        "workaround",
        "provisoriamente",
        "temporário",
        "paliativo",
    ),
}
WEB_ASSET_EXTENSIONS = {
    "",
    ".base",
    ".bin",
    ".core",
    ".css",
    ".eot",
    ".gif",
    ".html",
    ".jpeg",
    ".jpg",
    ".js",
    ".lib",
    ".png",
    ".svg",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
}


class MovideskTicketArchiveError(RuntimeError):
    """Controlled failure while reading an archived ticket."""


def audit_movidesk_ticket_archives(root: str | Path) -> dict[str, Any]:
    source_root = _source_root(root)
    parsed = [_parse_archive(path, source_root) for path in _archive_paths(source_root)]
    candidates = [_safe_candidate_summary(item) for item in parsed]
    channels = Counter(str(item["channel"]) for item in candidates)
    statuses = Counter(str(item["status"]) for item in candidates)
    modules = Counter(str(item["module_hint"]) for item in candidates)
    priority = [
        item["candidate_id"]
        for item in candidates
        if item["review_priority"] == "code_evidence_candidate"
    ]
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "checked_at": utc_now(),
        "archive_count": len(candidates),
        "resolved_count": sum(bool(item["resolved"]) for item in candidates),
        "channel_distribution": dict(sorted(channels.items())),
        "status_distribution": dict(sorted(statuses.items())),
        "module_hint_distribution": dict(sorted(modules.items())),
        "code_evidence_candidate_count": len(priority),
        "code_evidence_candidate_ids": priority,
        "enough_for_triage": len(candidates) >= 10,
        "enough_confirmed_for_benchmark": False,
        "benchmark_blocker": (
            "A causa-raiz, o JAR-alvo e a evidência de resolução ainda precisam "
            "de revisão humana; status Resolvido não confirma causa em código."
        ),
        "candidates": candidates,
    }


def build_movidesk_ticket_review_packet(
    root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_root = _source_root(root)
    parsed = [_parse_archive(path, source_root) for path in _archive_paths(source_root)]
    packet_id = f"ticket-review-{uuid.uuid4().hex[:16]}"
    ticket_numbers = tuple(
        str(item["ticket_number"]) for item in parsed if item["ticket_number"]
    )
    candidates: list[dict[str, Any]] = []
    mappings: dict[str, dict[str, str]] = {}
    for item in parsed:
        identities = _identity_candidates(item["container"])
        ticket_number = str(item["ticket_number"])
        subject = _redact_ticket_text(
            str(item["subject"]),
            identities=identities,
            ticket_numbers=ticket_numbers,
        )
        actions: list[dict[str, Any]] = []
        remaining_findings = 0
        for action in item["actions"]:
            content = _redact_ticket_text(
                str(action["content"]),
                identities=identities,
                ticket_numbers=ticket_numbers,
            )
            remaining_findings += len(sensitive_text_findings(content))
            actions.append(
                {
                    "role": action["role"],
                    "visibility": action["visibility"],
                    "created_at": action["created_at"],
                    "content": content,
                }
            )
        remaining_findings += len(sensitive_text_findings(subject))
        if remaining_findings:
            raise MovideskTicketArchiveError(
                f"A pseudonimização automática do candidato {item['candidate_id']} "
                "deixou padrões sensíveis reconhecíveis."
            )
        summary = _safe_candidate_summary(item)
        candidates.append(
            {
                **summary,
                "subject": subject,
                "actions": actions,
                "automated_redaction": {
                    "known_identity_count": len(identities),
                    "remaining_sensitive_pattern_count": remaining_findings,
                    "manual_review_required": True,
                },
                "review": {
                    "anonymization_approved": False,
                    "eligible_for_code_benchmark": False,
                    "paired_candidate_id": "",
                    "module": "",
                    "target_jars": [],
                    "known_root_cause": "",
                    "root_cause_evidence": "",
                    "expected_terms": [],
                    "expected_code_symbols": [],
                    "expected_citation_sources": [],
                    "forbidden_terms": [],
                    "notes": "",
                },
            }
        )
        mappings[str(item["candidate_id"])] = {
            "relative_archive_path": str(item["relative_path"]),
            "archive_sha256": str(item["archive_sha256"]),
            "source_ticket_number": ticket_number,
        }
    packet = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "packet_id": packet_id,
        "created_at": utc_now(),
        "safe_for_model": False,
        "instructions": (
            "Revise localmente nomes e contexto residual. Marque anonymization_approved "
            "somente depois da revisão humana. Status Resolvido não comprova causa-raiz."
        ),
        "source_set_fingerprint": _source_set_fingerprint(parsed),
        "candidates": candidates,
    }
    content_fingerprint = _packet_fingerprint(packet)
    packet["content_fingerprint"] = content_fingerprint
    key = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "packet_id": packet_id,
        "created_at": utc_now(),
        "sensitive_source_key": True,
        "share_with_reviewer": False,
        "source_set_fingerprint": packet["source_set_fingerprint"],
        "content_fingerprint": content_fingerprint,
        "mappings": mappings,
    }
    return packet, key


def _source_root(root: str | Path) -> Path:
    source = Path(root).resolve()
    if not source.is_dir():
        raise MovideskTicketArchiveError(f"Pasta de auditoria inexistente: {source}")
    return source


def _archive_paths(root: Path) -> list[Path]:
    paths = sorted(root.rglob("*.zip"), key=lambda item: str(item).casefold())
    if not paths:
        raise MovideskTicketArchiveError("Nenhum arquivo ZIP foi encontrado.")
    return paths


def _parse_archive(path: Path, root: Path) -> dict[str, Any]:
    archive_sha256 = _file_sha256(path)
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise MovideskTicketArchiveError(
                    f"Arquivo {archive_sha256[:12]} excede o limite de entradas."
                )
            if any(item.flag_bits & 0x1 for item in entries):
                raise MovideskTicketArchiveError(
                    f"Arquivo {archive_sha256[:12]} contém entrada criptografada."
                )
            html_entries = [
                item
                for item in entries
                if PurePosixPath(item.filename).name.casefold() == "index.html"
            ]
            if len(html_entries) != 1:
                raise MovideskTicketArchiveError(
                    f"Arquivo {archive_sha256[:12]} precisa conter um index.html."
                )
            html_entry = html_entries[0]
            if html_entry.file_size > MAX_HTML_BYTES:
                raise MovideskTicketArchiveError(
                    f"HTML do arquivo {archive_sha256[:12]} excede o limite seguro."
                )
            try:
                html = archive.read(html_entry).decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise MovideskTicketArchiveError(
                    f"HTML do arquivo {archive_sha256[:12]} não é UTF-8 válido."
                ) from exc
            extensions = Counter(
                PurePosixPath(item.filename).suffix.casefold()
                for item in entries
                if not item.is_dir()
            )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, MovideskTicketArchiveError):
            raise
        raise MovideskTicketArchiveError(
            f"Falha ao ler o arquivo {archive_sha256[:12]}: {type(exc).__name__}: {exc}"
        ) from exc
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select("div.ticket-container")
    container = (
        max(containers, key=lambda item: len(item.get_text(" ", strip=True)))
        if containers
        else soup
    )
    subject_node = container.select_one("input.subject")
    subject = str(subject_node.get("value") or "") if subject_node else ""
    status_node = container.select_one("#ticket-status-container .select2-chosen")
    if status_node is None:
        status_node = container.select_one("#ticket-status-container")
    status = status_node.get_text(" ", strip=True) if status_node else "não informado"
    actions: list[dict[str, str]] = []
    for action in container.select("#action-list > .action-item"):
        content = action.select_one(".action-item-content")
        if content is None:
            continue
        classes = {str(item).casefold() for item in action.get("class") or []}
        created = action.select_one(".createdDate")
        actions.append(
            {
                "role": (
                    "client"
                    if "client" in classes
                    else "agent"
                    if "agent" in classes
                    else "unknown"
                ),
                "visibility": (
                    "internal"
                    if {"internal", "private"} & classes
                    else "public"
                ),
                "created_at": created.get_text(" ", strip=True) if created else "",
                "content": content.get_text(" ", strip=True),
            }
        )
    corpus = " ".join([subject, *(item["content"] for item in actions)])
    classification = classify(subject, corpus, "", "")
    ticket_match = re.search(r"Ticket-Edit-(\d+)", path.name, re.IGNORECASE)
    channel = _channel(path.parent.name)
    signals = _signal_counts(corpus)
    candidate_id = f"candidate-{archive_sha256[:12]}"
    raw_sensitive = sensitive_text_findings(corpus)
    non_web_extensions = {
        extension or "[sem_ext]": count
        for extension, count in sorted(extensions.items())
        if extension not in WEB_ASSET_EXTENSIONS
    }
    return {
        "candidate_id": candidate_id,
        "channel": channel,
        "relative_path": path.relative_to(root).as_posix(),
        "archive_sha256": archive_sha256,
        "ticket_number": ticket_match.group(1) if ticket_match else "",
        "container": container,
        "subject": subject,
        "status": status,
        "resolved": _normalized(status) in {"resolvido", "resolvido n1", "fechado"},
        "actions": actions,
        "module_hint": classification.module,
        "module_confidence": round(float(classification.confidence), 4),
        "signals": signals,
        "raw_sensitive_counts": dict(
            sorted(Counter(item["kind"] for item in raw_sensitive).items())
        ),
        "archive_entry_count": sum(extensions.values()),
        "non_web_attachment_types": non_web_extensions,
    }


def _safe_candidate_summary(item: dict[str, Any]) -> dict[str, Any]:
    roles = Counter(str(action["role"]) for action in item["actions"])
    visibility = Counter(str(action["visibility"]) for action in item["actions"])
    priority = (
        "code_evidence_candidate"
        if item["channel"] == "n2_n1" and int(item["signals"]["code"]) > 0
        else "n2_resolution_review"
        if item["channel"] == "n2_n1"
        else "n1_question_context"
    )
    return {
        "candidate_id": item["candidate_id"],
        "channel": item["channel"],
        "archive_sha256": item["archive_sha256"],
        "status": item["status"],
        "resolved": item["resolved"],
        "action_count": len(item["actions"]),
        "role_distribution": dict(sorted(roles.items())),
        "visibility_distribution": dict(sorted(visibility.items())),
        "content_chars": sum(len(str(action["content"])) for action in item["actions"]),
        "module_hint": item["module_hint"],
        "module_confidence": item["module_confidence"],
        "signals": item["signals"],
        "raw_sensitive_counts": item["raw_sensitive_counts"],
        "archive_entry_count": item["archive_entry_count"],
        "non_web_attachment_types": item["non_web_attachment_types"],
        "review_priority": priority,
        "eligible_for_code_benchmark": False,
    }


def _identity_candidates(container: Any) -> tuple[str, ...]:
    selectors = (
        ".createdBy",
        "#client-container .select2-chosen",
        ".owner .select2-chosen",
        ".requester .select2-chosen",
    )
    identities: set[str] = set()
    for selector in selectors:
        for node in container.select(selector):
            value = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if 3 <= len(value) <= 120:
                identities.add(value)
    return tuple(sorted(identities, key=lambda value: (-len(value), value.casefold())))


def _redact_ticket_text(
    value: str, *, identities: tuple[str, ...], ticket_numbers: tuple[str, ...]
) -> str:
    redacted = str(value or "")
    for identity in identities:
        redacted = re.sub(re.escape(identity), "[IDENTIDADE]", redacted, flags=re.I)
    for ticket_number in ticket_numbers:
        redacted = re.sub(
            rf"(?<!\d){re.escape(ticket_number)}(?!\d)", "[TICKET]", redacted
        )
    redacted = redact_benchmark_sensitive_text(redacted)
    redacted = re.sub(
        r"\b(?:ticket|chamado|protocolo)\s*(?:n[ºo]\.?\s*)?[#:]?\s*\d+",
        "[TICKET]",
        redacted,
        flags=re.I,
    )
    redacted = re.sub(
        r"\b(?:cliente|empresa|contato|solicitante|respons[aá]vel)\s*:\s*"
        r"[^|;]{3,80}",
        lambda match: match.group(0).split(":", 1)[0] + ": [IDENTIDADE]",
        redacted,
        flags=re.I,
    )
    redacted = re.sub(
        r"\b(ol[aá\ufffd]|bom dia|boa tarde|boa noite|prezad[oa])\s*,?\s+"
        r"(?!\[IDENTIDADE\])[^,!.?:;\r\n]{1,60}",
        lambda match: f"{match.group(1)} [IDENTIDADE]",
        redacted,
        flags=re.I,
    )
    redacted = re.sub(
        r"(?i)\b[^\s/\\]{1,70}\.(?:pdf|png|jpe?g|gif|xlsx?|csv|txt|log|zip)\b",
        "[ANEXO]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        "[UUID]",
        redacted,
    )
    return re.sub(r"\s+", " ", redacted).strip()


def _channel(folder_name: str) -> str:
    normalized = _normalized(folder_name)
    if "n1" in normalized and "cliente" in normalized:
        return "n1_client"
    if "n2" in normalized and "n1" in normalized:
        return "n2_n1"
    return "unclassified"


def _signal_counts(value: str) -> dict[str, int]:
    normalized = _normalized(value)
    return {
        name: sum(normalized.count(_normalized(term)) for term in terms)
        for name, terms in SIGNAL_TERMS.items()
    }


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _source_set_fingerprint(parsed: list[dict[str, Any]]) -> str:
    encoded = "\n".join(sorted(str(item["archive_sha256"]) for item in parsed))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _packet_fingerprint(packet: dict[str, Any]) -> str:
    immutable = {
        "packet_id": packet["packet_id"],
        "source_set_fingerprint": packet["source_set_fingerprint"],
        "candidates": [
            {
                key: value
                for key, value in candidate.items()
                if key != "review"
            }
            for candidate in packet["candidates"]
        ],
    }
    encoded = json.dumps(
        immutable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ARCHIVE_SCHEMA_VERSION",
    "MovideskTicketArchiveError",
    "audit_movidesk_ticket_archives",
    "build_movidesk_ticket_review_packet",
]
