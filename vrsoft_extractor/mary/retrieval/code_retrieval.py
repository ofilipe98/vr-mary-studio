from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ..models import EvidenceCandidate
from ..supervision import EvidenceClaim

LOGGER = logging.getLogger(__name__)


def _code_scope_queries(value: str, limit: int = 8) -> tuple[str, ...]:
    """Prefer code-shaped terms after documentation workers narrowed the scope."""

    ignored = {
        "ainda", "apenas", "como", "com", "das", "depois", "dos", "essa",
        "este", "esta", "isso", "para", "pela", "pelo", "porque", "qual",
        "quando", "sobre", "uma", "usar", "user", "request", "passo",
        "completa", "completo", "confirmado", "explicando", "fato", "fluxo",
        "funciona", "inferência", "hipótese", "analise",
        "analisar", "código", "codigo", "enviou", "evidência", "evidencias",
        "fonte", "informação", "informacao", "novamente", "original",
        "release", "solicitação", "solicitacao", "tente", "trecho", "trechos",
        "processo", "sistema", "utiliza", "utilizar", "validar", "validação",
        "validacao", "você", "voce", "vrmaster",
    }
    text_val = str(value or "")
    log_noise = {
        "ERRO", "ERROR", "CARREGANDO", "PROCESSANDO", "AUTORIZADOR", "CONCENTRADOR",
        "REDE", "RETORNO", "DISPLAY", "TECLADO", "ON", "OFF", "INFO", "WARN",
        "WARNING", "DEBUG", "TRACE", "FATAL", "NULL", "TRUE", "FALSE", "BANCO",
        "TECLA", "EVENT", "DISPATCHER",
    }
    stack_frames = re.findall(r"\bat\s+(?:[\w\$]+\.)*([A-Z][\w\$]+)\.([\w\$]+)\(", text_val)
    exceptions = re.findall(r"\b([A-Z][\w\$]+Exception)\b", text_val)
    java_files = re.findall(r"\b([A-Z][\w\$]+)\.java\b", text_val)

    stack_classes = [c for c, _ in stack_frames]
    stack_methods = [m for _, m in stack_frames if m not in {"main", "run"}]
    stack_symbols = list(dict.fromkeys(stack_classes + exceptions + java_files + stack_methods))

    raw = re.findall(r"[A-Za-zÀ-ÿ_$][A-Za-zÀ-ÿ0-9_$]{2,}", text_val)
    unique = list(dict.fromkeys(raw))

    camel = [
        item for item in unique
        if item.casefold() not in ignored
        and (re.search(r"[a-z0-9][A-Z]", item) or re.search(r"^[A-Z][a-z0-9]+[A-Z]", item))
        and item not in stack_symbols
    ]

    symbols = [
        item for item in unique
        if item.casefold() not in ignored
        and item.upper() not in log_noise
        and item not in stack_symbols
        and item not in camel
        and ("_" in item or (item.isupper() and len(item) <= 6))
    ]

    preferred = [
        item for item in unique
        if item.casefold() not in ignored
        and item.upper() not in log_noise
        and item not in stack_symbols
        and item not in camel
        and item not in symbols
        and len(item) >= 6
    ]

    fallback = [
        item for item in unique
        if item.casefold() not in ignored
        and item not in stack_symbols
        and item not in camel
        and item not in symbols
        and item not in preferred
    ]

    return tuple(dict.fromkeys(stack_symbols + camel + symbols + preferred + fallback))[: max(1, int(limit))]

def _has_stack_trace_elements(text: str) -> bool:
    val = str(text or "")
    return bool(
        re.search(r"\bat\s+(?:[\w\$]+\.)*[A-Z][\w\$]+\.[\w\$]+\(", val)
        or re.search(r"\b[A-Z][\w\$]+Exception\b", val)
        or re.search(r"\b[A-Z][\w\$]+\.java\b", val)
    )


_MASTER_MENTION_RE = re.compile(r"(?i)\bvrmaster\s*[.:$]")
FALLBACK_WARNING = (
    "Trecho obtido no VRMaster central como fallback do escopo selecionado."
)


def _mentions_master(text: str) -> bool:
    """True when the text points at a Master frame/FQCN, never a loose word."""
    return bool(_MASTER_MENTION_RE.search(str(text or "")))



def check_code_availability(
    root: Path,
    *,
    application_contexts: list[dict[str, Any]] | None = None,
    release_id: str = "current",
    manifest_hash: str = "",
) -> dict[str, Any]:
    """Inspect availability and freshness of indexed Java code."""
    from ..code_index import JavaCodeIndex
    from ..erp_releases import ErpReleaseCatalog

    if application_contexts is not None and len(application_contexts) == 0:
        return {
            "state": "disabled",
            "message": "Nenhum contexto de aplicativo selecionado para busca em código.",
        }

    try:
        application_contexts = resolve_code_contexts(root, application_contexts)
        release_id = _resolve_release_id(root, release_id)
        index = JavaCodeIndex(root)
        if application_contexts:
            predicate, params = _source_scope(application_contexts, release_id)
            index.initialize()
            with index.store.connect() as conn:
                count = conn.execute("SELECT count(*) FROM code_sources s WHERE " + predicate, params).fetchone()[0]
            return {"state": "available" if count else "not_indexed", "sources": count}
        status = index.status(release_id if not application_contexts else "")
        if not status.get("sources"):
            return {
                "state": "not_indexed",
                "message": "Índice de código Java não contém classes indexadas.",
            }

        if manifest_hash or release_id:
            catalog = ErpReleaseCatalog(root)
            rel_status = catalog.status(release_id)
            if rel_status.get("freshness") == "stale":
                return {
                    "state": "stale",
                    "message": "Os JARs da release foram alterados após indexação.",
                }
            if manifest_hash and rel_status.get("release_manifest_sha256") != manifest_hash:
                return {
                    "state": "stale",
                    "message": "Hash do manifesto difere da versão congelada no turno.",
                }
        return {"state": "available", "message": "Código Java indexado e pronto para consulta."}
    except Exception as exc:
        LOGGER.warning("Erro ao verificar disponibilidade de código: %s", exc)
        return {"state": "unavailable", "message": str(exc)}


def retrieve_code_candidates(
    root: Path,
    scoped_text: str,
    *,
    application_contexts: list[dict[str, Any]] | None = None,
    code_analysis_release: str = "current",
    code_analysis_manifest_sha256: str = "",
    limit_per_scope: int = 8,
    limit_per_query: int = 3,
    max_caller_nodes: int = 3,
    max_seconds: float = 0.3,
    module: str = "",
    product: str = "",
    budget_remaining: float | None = None,
    max_excerpt_chars: int = 24000,
    master_fallback: bool = False,
) -> tuple[list[EvidenceCandidate], list[EvidenceClaim], list[dict[str, Any]]]:
    """Deterministic Java code candidate retrieval across configured application contexts.

    With ``master_fallback`` the central VRMaster of the same package is searched
    only when the selected scopes return nothing or the text mentions Master.
    """
    from ..code_index import JavaCodeIndex
    from ..erp_releases import ErpReleaseCatalog
    from .code_relations import caller_evidence

    if application_contexts is not None and len(application_contexts) == 0:
        return [], [], []

    expected_release_hash = str(code_analysis_manifest_sha256 or "").strip()
    application_contexts = resolve_code_contexts(root, application_contexts)

    if expected_release_hash and application_contexts is None:
        release_status = ErpReleaseCatalog(root).status(code_analysis_release)
        current_release_hash = str(release_status.get("release_manifest_sha256") or "")
        if release_status.get("freshness") != "fresh":
            raise RuntimeError(
                "Os JARs da release mudaram depois da seleção; "
                "o Agente de Código não usará um índice possivelmente desatualizado."
            )
        if current_release_hash != expected_release_hash:
            raise RuntimeError(
                "O hash do manifesto mudou depois do início do turno; "
                "o Agente de Código foi interrompido."
            )

    code_results: list[dict[str, Any]] = []
    seen_code: set[str] = set()
    fallback_keys: set[str] = set()
    scopes = application_contexts if application_contexts is not None else [None]

    def _collect(scope_context: dict[str, Any] | None, *, fallback: bool) -> int:
        scope_release = scope_context["package_id"] if scope_context else code_analysis_release
        scope_hash = scope_context["manifest_sha256"] if scope_context else expected_release_hash
        scope_id = scope_context["context_id"] if scope_context else ""
        scoped_count = 0
        for code_query in _code_scope_queries(scoped_text):
            for res in JavaCodeIndex(root).search(
                code_query,
                release_id=scope_release,
                limit=limit_per_query,
                **({"artifacts": scope_context["artifacts"], "manifest_hash": scope_hash} if scope_context else {}),
            ):
                if scope_hash and str(res.get("release_hash") or "") != scope_hash:
                    continue
                key = str(res.get("source_key") or "")
                identity = scope_id + key
                if not key or identity in seen_code:
                    continue
                seen_code.add(identity)
                res["application_context"] = scope_context or {}
                if fallback:
                    fallback_keys.add(key)
                    res["fallback"] = True
                    res["fallback_warning"] = FALLBACK_WARNING
                code_results.append(res)
                scoped_count += 1
                if scoped_count >= limit_per_scope:
                    break
            if scoped_count >= limit_per_scope:
                break
        return scoped_count

    for app_context in scopes:
        _collect(app_context, fallback=False)

    # VRMaster is a fallback: only when the selected scopes return nothing or
    # the request explicitly points at a Master frame/FQCN.
    if master_fallback and application_contexts:
        if not code_results or _mentions_master(scoped_text):
            from ..code_context import master_fallback_context
            fallback_context = master_fallback_context(root, application_contexts)
            if fallback_context is not None:
                _collect(fallback_context, fallback=True)

    # If stack-trace classes exist outside the selected app_context,
    # search across the release as fallback:
    if (
        _has_stack_trace_elements(scoped_text)
        and bool(code_analysis_release)
        and len(code_results) < limit_per_scope
        and application_contexts is not None
    ):
        for code_query in _code_scope_queries(scoped_text):
            for res in JavaCodeIndex(root).search(
                code_query,
                release_id=code_analysis_release,
                limit=limit_per_query,
            ):
                if expected_release_hash and str(res.get("release_hash") or "") != expected_release_hash:
                    continue
                key = str(res.get("source_key") or "")
                if key and key not in seen_code and key not in fallback_keys:
                    seen_code.add(key)
                    jar_path = str(res.get("jar_relative_path") or "")
                    app_name = jar_path.split("/")[0] if "/" in jar_path else "Código"
                    res["application_context"] = {
                        "app_id": app_name.lower(),
                        "application": app_name,
                        "label": app_name,
                    }
                    code_results.append(res)
                if len(code_results) >= limit_per_scope:
                    break
            if len(code_results) >= limit_per_scope:
                break

    code_candidates: list[EvidenceCandidate] = []
    code_claims: list[EvidenceClaim] = []
    for result in code_results:
        result = JavaCodeIndex(root).expanded_excerpt(result, max_chars=max_excerpt_chars)
        code_confidence = (
            0.85
            if result["freshness"] == "fresh"
            and result.get("classpath_resolution") in {"unique", "resolved"}
            else 0.45
        )
        app_context = result.get("application_context", {})
        context_prefix = app_context.get("context_id", "")
        evidence_id = f"code:{context_prefix + ':' if context_prefix else ''}{str(result['source_key'])}"
        fallback = bool(result.get("fallback"))
        title = (
            f"{app_context.get('label', 'Código')} · {result['release_id']} · {result['jar_relative_path']} · "
            f"{result['qualified_name']} · linhas {result['line_start']}-{result['line_end']}"
            + (" · fallback VRMaster" if fallback else "")
        )
        code_candidates.append(
            EvidenceCandidate(
                evidence_id=evidence_id,
                source="code",
                source_id=str(result["source_key"]),
                document_id=0,
                chunk_id=0,
                title=title,
                heading=str(result["qualified_name"]),
                content_type="java_decompiled",
                module=module or "Multimodulo",
                product=product or "VRMaster",
                excerpt=str(result["excerpt"]),
                local_path=f"{result['output_reference']}/{result['source_relative_path']}",
                updated_at=str(result.get("indexed_at") or ""),
                score=float(result.get("score") or 1.0),
                confidence=code_confidence,
                entities={
                    "source_sha256": (str(result.get("source_sha256") or ""),),
                    "application_context": (app_context.get("context_id", ""),),
                    "application": (app_context.get("label", ""),),
                    "release_id": (str(result["release_id"]),),
                    "release_manifest_sha256": (str(result.get("release_hash") or ""),),
                    "jar_relative_path": (str(result["jar_relative_path"]),),
                    **({"fallback": ("vrmaster",)} if fallback else {}),
                },
            )
        )
        code_claims.append(
            EvidenceClaim(
                text=(
                    ("[fallback VRMaster] " if fallback else "")
                    + f"{result['qualified_name']}: {result['excerpt']}"
                ),
                evidence_ids=(evidence_id,),
                kind="fact",
                confidence=code_confidence,
                worker_id="ultra_code",
            )
        )

    remaining_time = max_seconds
    if budget_remaining is not None:
        remaining_time = min(remaining_time, max(0.05, budget_remaining))

    related = []
    for app_context in scopes:
        related.extend(
            caller_evidence(
                root,
                list(_code_scope_queries(scoped_text)),
                release_id=app_context["package_id"] if app_context else code_analysis_release,
                manifest_hash=app_context["manifest_sha256"] if app_context else expected_release_hash,
                **({"application_context": app_context} if app_context else {}),
                max_seconds=remaining_time,
                max_nodes=max_caller_nodes,
            )
        )
    for related_candidate in related[:max_caller_nodes]:
        code_candidates.append(related_candidate)
        code_claims.append(
            EvidenceClaim(
                text=related_candidate.title + ": " + related_candidate.excerpt,
                evidence_ids=(related_candidate.evidence_id,),
                kind="fact",
                confidence=related_candidate.confidence,
                worker_id="ultra_code",
            )
        )

    if application_contexts:
        resolve_code_contexts(root, application_contexts)
    return code_candidates, code_claims, code_results


def resolve_code_contexts(root: Path, contexts: list[dict[str, Any]] | None, context: str = "") -> list[dict[str, Any]] | None:
    """Resolve selections once and reject changed frozen identities on subsequent calls."""
    from ..code_context import freeze_application_contexts
    if contexts:
        if all("context_id" in c for c in contexts):
            # The turn already verified content hashes while freezing its selection.
            # Recheck catalogue, artifacts and file metadata without rehashing entire
            # distributions on every paginated read.
            if freeze_application_contexts(root, contexts, full_hash=False) != contexts:
                raise ValueError("O contexto de aplicativos mudou durante o turno.")
        else:
            contexts = freeze_application_contexts(root, contexts)
    if context:
        if contexts is None:
            contexts = [c for c in available_code_contexts(root) if context in
                        {c["context_id"], c["app_id"], c["package_id"]}]
            if len(contexts) != 1:
                raise ValueError("Selecione um contexto exato de aplicativo, versão e origem em vr_sources.")
            contexts = freeze_application_contexts(root, contexts)
        else:
            contexts = [c for c in contexts if context in {c["context_id"], c["app_id"], c["package_id"]}]
    return contexts


def available_code_contexts(root: Path) -> list[dict[str, Any]]:
    from ..code_context import freeze_application_contexts
    from ..erp_releases import ErpReleaseCatalog
    catalog = ErpReleaseCatalog(root)
    catalog.ensure_apps_catalog_synced()
    data = catalog.apps_store.load_catalog()
    result = []
    for package_id, package in sorted(data.get("packages", {}).items()):
        for item in package.get("composition", []):
            selection = {k: item[k] for k in ("app_id", "version", "variant_id")}
            selection["package_id"] = package_id
            try:
                result.extend(freeze_application_contexts(root, [selection], full_hash=False))
            except (ValueError, RuntimeError):
                continue
    return result


def _resolve_release_id(root: Path, release_id: str) -> str:
    """Mirror JavaCodeIndex.search: map 'current'/'' to the indexed release id."""
    normalized = str(release_id or "").strip()
    if normalized not in ("", "current"):
        return normalized
    try:
        from ..erp_releases import ErpReleaseCatalog
        statuses = ErpReleaseCatalog(root).list_statuses(full_hash=False)
        if statuses:
            return str(statuses[0].get("release_id") or normalized)
    except Exception:
        pass
    return normalized


def _source_scope(contexts: list[dict[str, Any]] | None, release_id: str) -> tuple[str, list[Any]]:
    from ..code_context import artifact_sql_filter
    if contexts is None:
        return "s.release_id=?", [release_id or "current"]
    predicates, params = [], []
    for ctx in contexts:
        clause, values = artifact_sql_filter(ctx["artifacts"], ctx["manifest_sha256"])
        predicates.append("(s.release_id=?" + clause + ")")
        params.extend([ctx["package_id"], *values])
    return " OR ".join(predicates) or "0", params


def _row_context(row: dict, contexts: list[dict[str, Any]] | None) -> dict:
    return next((c for c in contexts or [] if c["package_id"] == row["release_id"] and any(
        a["relative_path"] == row["jar_relative_path"] and a["sha256"] == row["artifact_sha256"]
        for a in c["artifacts"])), {})


def code_reference(row: dict, context: dict | None = None) -> str:
    ctx = (context or {}).get("context_id", "")
    return "code:" + (ctx + ":" if ctx else "") + row["source_key"]


def _scope_content_hashes(
    connection: Any, contexts: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], set[str]]]:
    """Class contents physically present in each selected context's artifacts."""

    scoped: list[tuple[dict[str, Any], set[str]]] = []
    for context in contexts or []:
        artifacts = list(context.get("artifacts") or [])
        manifest = str(context.get("manifest_sha256") or "")
        if not artifacts or not manifest:
            continue
        clause = " OR ".join(
            "(jar_relative_path=? AND artifact_sha256=?)" for _ in artifacts
        )
        params: list[Any] = [manifest]
        for artifact in artifacts:
            params.extend((artifact["relative_path"], artifact["sha256"]))
        rows = connection.execute(
            "SELECT DISTINCT content_sha256 FROM class_occurrences "
            "WHERE release_hash=? AND (" + clause + ")",
            params,
        ).fetchall()
        hashes = {str(row[0]) for row in rows}
        if hashes:
            scoped.append((context, hashes))
    return scoped


def _lookup_canonical_rows(
    connection: Any, contexts: list[dict[str, Any]], key: str
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Rows indexed under another artifact but present in the selected contexts.

    Decompilation is content-addressed: a class identical across JARs of the
    same release is indexed only once, under the canonical artifact. A scoped
    lookup then finds nothing even though the class belongs to the selected
    application. This resolves those rows through class occurrences.
    """

    scoped = _scope_content_hashes(connection, contexts)
    packages = sorted(
        {str(context.get("package_id") or "") for context, _ in scoped} - {""}
    )
    if not scoped or not packages:
        return []
    manifests = {
        str(context.get("manifest_sha256") or "") for context, _ in scoped
    } - {""}
    placeholders = ",".join("?" for _ in packages)
    candidates: list[Any] = []
    seen_ids: set[int] = set()
    for column in ("s.source_key", "s.qualified_name COLLATE NOCASE"):
        for candidate in connection.execute(
            "SELECT s.* FROM code_sources s WHERE s.release_id IN ("
            + placeholders
            + f") AND {column}=? LIMIT 6",
            [*packages, key],
        ).fetchall():
            candidate_id = int(candidate["id"])
            if candidate_id not in seen_ids:
                seen_ids.add(candidate_id)
                candidates.append(candidate)
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in candidates:
        if manifests and str(candidate["release_hash"]) not in manifests:
            continue
        try:
            row_hashes = set(json.loads(candidate["content_hashes_json"] or "[]"))
        except (TypeError, ValueError):
            row_hashes = set()
        if not row_hashes:
            continue
        context = next(
            (ctx for ctx, hashes in scoped if hashes & row_hashes), None
        )
        if context is not None:
            matches.append((dict(candidate), context))
    return matches


def read_code_source(root: Path, reference: str, *, application_contexts: list[dict[str, Any]] | None = None,
                     code_analysis_release: str = "current", code_analysis_manifest_sha256: str = "",
                     start_line: int | None = None, end_line: int | None = None,
                     cursor: int = 0, limit: int = 8000,
                     master_fallback: bool = False) -> dict[str, Any]:
    from ..code_index import JavaCodeIndex
    from ..erp_releases import ErpReleaseCatalog
    try:
        context = ""
        key = reference
        if reference.startswith("code:"):
            parts = reference.split(":")
            key = parts[-1]
            if len(parts) == 3:
                context = parts[1]
        if application_contexts is not None and len(application_contexts) == 0:
            return {"state": "scope_required", "reference": reference, "selected_contexts": [],
                    "error": "Nenhum aplicativo/versão selecionado para busca em código. "
                             "Confira o aplicativo e a versão em Aplicativos."}
        contexts = resolve_code_contexts(root, application_contexts, context)
        index = JavaCodeIndex(root)
        index.initialize()

        def _lookup(scope_contexts: list[dict[str, Any]] | None) -> list[Any]:
            predicate, params = _source_scope(
                scope_contexts, _resolve_release_id(root, code_analysis_release)
            )
            with index.store.connect() as conn:
                return conn.execute(
                    "SELECT s.* FROM code_sources s WHERE (" + predicate +
                    ") AND (s.source_key=? OR s.qualified_name=?) LIMIT 2",
                    [*params, key, key],
                ).fetchall()

        rows = [dict(item) for item in _lookup(contexts)]
        fallback_context: dict[str, Any] | None = None
        fallback_used = False
        canonical_context: dict[str, Any] | None = None
        canonical_used = False
        if not rows and contexts:
            with index.store.connect() as connection:
                canonical_rows = _lookup_canonical_rows(connection, contexts, key)
            if len(canonical_rows) == 1:
                rows = [canonical_rows[0][0]]
                canonical_context = canonical_rows[0][1]
                canonical_used = True
            elif len(canonical_rows) > 1:
                rows = [match[0] for match in canonical_rows]
        if not rows and master_fallback and application_contexts:
            from ..code_context import master_fallback_context
            fallback_context = master_fallback_context(root, application_contexts)
            if fallback_context is not None:
                rows = [dict(item) for item in _lookup([fallback_context])]
                fallback_used = bool(rows)
        if len(rows) != 1:
            selected = [str(c.get("label") or c.get("app_id") or "") for c in contexts or []]
            message = ("Referência ambígua; use a referência exata retornada por vr_search."
                       if len(rows) > 1 else
                       "Fonte não encontrada no contexto selecionado. Confira o aplicativo e a versão "
                       "em Aplicativos e use a referência retornada por vr_search.")
            return {"state": "scope_required" if len(rows) > 1 else "no_results", "reference": reference,
                    "selected_contexts": selected, "error": message}
        row = rows[0]
        status = ErpReleaseCatalog(root).status(row["release_id"], full_hash=not bool(contexts))
        if status.get("freshness") != "fresh" or status.get("release_manifest_sha256") != row["release_hash"] or (
                code_analysis_manifest_sha256 and row["release_hash"] != code_analysis_manifest_sha256):
            return {"state": "stale", "reference": reference, "error": "O índice mudou; selecione novamente a origem."}
        body = str(row["body"] or "")
        lines = body.splitlines()
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line) if end_line is not None else len(lines))
        selected = "\n".join(lines[start - 1:end])
        offset, size = max(0, int(cursor)), max(1, min(8000, int(limit)))
        content = selected[offset:offset + size]
        first = start + selected[:offset].count("\n")
        last = first + content.count("\n")
        ctx = (
            _row_context(row, contexts)
            or (canonical_context if canonical_used else None)
            or (fallback_context if fallback_used else None)
            or {}
        )
        canonical_reference = code_reference(row, ctx)
        fallback_payload: dict[str, Any] = {}
        if fallback_used:
            fallback_payload["fallback"] = "vrmaster"
        elif canonical_used:
            fallback_payload["fallback"] = "canonical"
            fallback_payload["canonical_jar_relative_path"] = str(row["jar_relative_path"])
        return {"state": "available", "reference": reference, "evidence_id": canonical_reference,
                "source": "code", "source_id": row["source_key"], "document_id": 0,
                "title": f"{ctx.get('label', 'Código')} · {row['release_id']} · {row['jar_relative_path']} · {row['qualified_name']} · linhas {first}-{last}"
                + (" · fallback VRMaster" if fallback_used else "")
                + (f" · cópia canônica {row['jar_relative_path']}" if canonical_used else ""),
                "heading": row["qualified_name"], "qualified_name": row["qualified_name"],
                "release_id": row["release_id"], "jar_relative_path": row["jar_relative_path"],
                "source_sha256": row["source_sha256"], "release_manifest_sha256": row["release_hash"],
                "context_id": ctx.get("context_id", ""), "line_start": first, "line_end": last,
                "local_path": f"{row['output_reference']}/{row['source_relative_path']}",
                "total_lines": len(lines), "total_chars": len(body), "cursor": offset, "limit": size,
                "has_more": offset + len(content) < len(selected),
                "next_cursor": offset + len(content) if offset + len(content) < len(selected) else None,
                **fallback_payload,
                "content": content}
    except (ValueError, RuntimeError) as exc:
        return {"state": "unavailable", "reference": reference, "error": str(exc)}


def list_code_sources(root: Path, *, context_id: str = "", query: str = "", offset: int = 0,
                      limit: int = 20, application_contexts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from ..code_index import JavaCodeIndex
    offset, limit = max(0, int(offset)), max(1, min(50, int(limit)))
    if not context_id and not application_contexts:
        contexts = available_code_contexts(root)
        items = [{k: c[k] for k in ("context_id", "app_id", "version", "variant_id", "package_id", "label")}
                 for c in contexts]
        page = items[offset:offset + limit]
        more = offset + len(page) < len(items)
        return {"state": "available", "applications": page, "total_applications": len(items),
                "offset": offset, "has_more": more, "next_cursor": offset + len(page) if more else None}
    contexts = resolve_code_contexts(root, application_contexts, context_id)
    predicate, params = _source_scope(contexts, "current")
    index = JavaCodeIndex(root)
    index.initialize()
    with index.store.connect() as conn:
        rows = conn.execute("SELECT s.source_key,s.qualified_name,s.release_id,s.release_hash,s.artifact_sha256,s.jar_relative_path "
            "FROM code_sources s WHERE (" + predicate + ") AND instr(lower(s.qualified_name), lower(?))>0 "
            "ORDER BY s.qualified_name,s.source_key LIMIT ? OFFSET ?", [*params, query, limit + 1, offset]).fetchall()
    page = [{**dict(r), "reference": code_reference(dict(r), _row_context(dict(r), contexts))} for r in rows[:limit]]
    return {"state": "available", "context_id": context_id, "sources": page, "offset": offset,
            "has_more": len(rows) > limit, "next_cursor": offset + len(page) if len(rows) > limit else None}
