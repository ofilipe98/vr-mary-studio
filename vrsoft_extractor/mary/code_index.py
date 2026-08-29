"""Searchable Java source index with release and bytecode provenance."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .erp_releases import ErpReleaseCatalog
from .java_ast import JavaAstUnavailable, parse_java_ast, tree_sitter_available
from .jvm_batches import DecompilationBatchError, DecompilationBatchStore


CODE_INDEX_SCHEMA_VERSION = 4
_PACKAGE_RE = re.compile(r"(?m)^\s*package\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;")
_IMPORT_RE = re.compile(
    r"(?m)^\s*import\s+(static\s+)?([A-Za-z_$][\w$]*(?:\.[A-Za-z_$*][\w$*]*)+)\s*;"
)
_TYPE_RE = re.compile(
    r"(?m)^\s*(?P<mods>(?:(?:public|protected|private|abstract|static|final|sealed|non-sealed|strictfp)\s+)*)"
    r"(?P<kind>@interface|class|interface|enum|record)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
    r"(?P<tail>[^\n{]*)[\n{]"
)
_METHOD_RE = re.compile(
    r"(?m)^\s*(?P<mods>(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)\s+)*)"
    r"(?:<[^>{}\n]+>\s+)?"
    r"(?P<return>[A-Za-z_$][\w$.,<>?\[\] @]*)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^;{}\n]*)\)\s*"
    r"(?:throws\s+[^;{\n]+\s*)?[;{]"
)
_FIELD_RE = re.compile(
    r"(?m)^\s*(?P<mods>(?:(?:public|protected|private|static|final|transient|volatile)\s+)+)"
    r"(?P<type>[A-Za-z_$][\w$.,<>?\[\] @]*)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:=[^;\n]*)?;"
)
_EXTENDS_RE = re.compile(
    r"\bextends\s+([A-Za-z_$][\w$.,<>? ]*?)(?=\s+implements\b|$)"
)
_IMPLEMENTS_RE = re.compile(r"\bimplements\s+([A-Za-z_$][\w$.,<>? ]*)$")
_SEARCH_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_$]+", re.UNICODE)


@dataclass(frozen=True)
class ParsedJavaSource:
    package_name: str
    primary_type: str
    qualified_name: str
    symbols: tuple[dict[str, Any], ...]
    relations: tuple[dict[str, Any], ...]
    parser_kind: str = "structural_fallback"
    syntax_error_count: int = 0


class JavaCodeIndex:
    def __init__(
        self,
        root: str | Path,
        *,
        catalog: ErpReleaseCatalog | None = None,
        store: DecompilationBatchStore | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.store = store or DecompilationBatchStore(self.root)

    def initialize(self) -> None:
        with self.store.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS code_sources (
                    id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL,
                    release_id TEXT NOT NULL,
                    release_hash TEXT NOT NULL,
                    jar_relative_path TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    output_reference TEXT NOT NULL,
                    source_relative_path TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    primary_type TEXT NOT NULL,
                    qualified_name TEXT NOT NULL,
                    logical_names_json TEXT NOT NULL,
                    content_hashes_json TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL,
                    parser_kind TEXT NOT NULL DEFAULT 'structural_fallback',
                    syntax_error_count INTEGER NOT NULL DEFAULT 0,
                    symbols_text TEXT NOT NULL,
                    body TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_code_sources_release
                    ON code_sources(release_id, release_hash);
                CREATE INDEX IF NOT EXISTS idx_code_sources_qualified
                    ON code_sources(qualified_name COLLATE NOCASE);
                CREATE TABLE IF NOT EXISTS code_symbols (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL REFERENCES code_sources(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    simple_name TEXT NOT NULL,
                    qualified_name TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    line_start INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_code_symbols_name
                    ON code_symbols(simple_name COLLATE NOCASE, qualified_name COLLATE NOCASE);
                CREATE TABLE IF NOT EXISTS code_relations (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL REFERENCES code_sources(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    source_symbol TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    line_start INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_code_relations_target
                    ON code_relations(target COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_code_relations_kind_target
                    ON code_relations(kind, target COLLATE NOCASE);
                CREATE VIRTUAL TABLE IF NOT EXISTS code_sources_fts USING fts5(
                    qualified_name,
                    symbols_text,
                    body,
                    content='code_sources',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TRIGGER IF NOT EXISTS code_sources_ai AFTER INSERT ON code_sources BEGIN
                  INSERT INTO code_sources_fts(rowid,qualified_name,symbols_text,body)
                  VALUES(new.id,new.qualified_name,new.symbols_text,new.body);
                END;
                CREATE TRIGGER IF NOT EXISTS code_sources_ad AFTER DELETE ON code_sources BEGIN
                  INSERT INTO code_sources_fts(code_sources_fts,rowid,qualified_name,symbols_text,body)
                  VALUES('delete',old.id,old.qualified_name,old.symbols_text,old.body);
                END;
                CREATE TRIGGER IF NOT EXISTS code_sources_au AFTER UPDATE ON code_sources BEGIN
                  INSERT INTO code_sources_fts(code_sources_fts,rowid,qualified_name,symbols_text,body)
                  VALUES('delete',old.id,old.qualified_name,old.symbols_text,old.body);
                  INSERT INTO code_sources_fts(rowid,qualified_name,symbols_text,body)
                  VALUES(new.id,new.qualified_name,new.symbols_text,new.body);
                END;
                """
            )
            _ensure_column(
                connection,
                "code_sources",
                "parser_kind",
                "TEXT NOT NULL DEFAULT 'structural_fallback'",
            )
            _ensure_column(
                connection,
                "code_sources",
                "syntax_error_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                connection,
                "code_relations",
                "source_symbol",
                "TEXT NOT NULL DEFAULT ''",
            )
            _ensure_column(
                connection,
                "code_relations",
                "confidence",
                "REAL NOT NULL DEFAULT 0.0",
            )
            connection.commit()

    def index_plan(self, plan_id: str) -> dict[str, Any]:
        self.initialize()
        with self.store.connect() as connection:
            plan = connection.execute(
                "SELECT * FROM decompilation_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if plan is None:
                raise DecompilationBatchError(f"Plano não encontrado: {plan_id}")
            batches = connection.execute(
                """SELECT * FROM decompilation_batches
                   WHERE plan_id = ? AND state = 'completed'
                     AND output_reference != '' AND tool != 'reused'
                   ORDER BY ordinal""",
                (plan_id,),
            ).fetchall()
        manifest = self.catalog.load_manifest(plan["release_id"])
        freshness = self.catalog.status(plan["release_id"])
        if (
            manifest.get("release_manifest_sha256") != plan["release_hash"]
            or freshness.get("freshness") != "fresh"
        ):
            raise DecompilationBatchError(
                "A release mudou depois da decompilação; o código não será indexado."
            )

        indexed = 0
        unchanged = 0
        errors: list[dict[str, str]] = []
        for batch in batches:
            output_dir = _resolve_output(self.root, batch["output_reference"])
            if not output_dir.is_dir():
                errors.append(
                    {
                        "batch_id": batch["batch_id"],
                        "error": "Pasta de saída não encontrada.",
                    }
                )
                continue
            provenance = self._batch_provenance(batch["batch_id"])
            for source_path in sorted(output_dir.rglob("*.java")):
                try:
                    changed = self._index_source(plan, batch, output_dir, source_path, provenance)
                except (OSError, UnicodeError, sqlite3.Error, ValueError) as exc:
                    errors.append(
                        {
                            "batch_id": batch["batch_id"],
                            "source": source_path.relative_to(output_dir).as_posix(),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                else:
                    indexed += int(changed)
                    unchanged += int(not changed)
        return {
            "schema_version": CODE_INDEX_SCHEMA_VERSION,
            "plan_id": plan_id,
            "release_id": plan["release_id"],
            "release_manifest_sha256": plan["release_hash"],
            "completed_batches": len(batches),
            "indexed_sources": indexed,
            "unchanged_sources": unchanged,
            "errors": errors,
            "indexed_at": _utc_now(),
        }

    def _batch_provenance(self, batch_id: str) -> dict[str, list[sqlite3.Row]]:
        with self.store.connect() as connection:
            rows = connection.execute(
                """SELECT o.* FROM batch_members m
                   JOIN class_occurrences o ON o.occurrence_id = m.occurrence_id
                   WHERE m.batch_id = ? ORDER BY m.ordinal""",
                (batch_id,),
            ).fetchall()
        result: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            family = str(row["logical_name"]).split("$", 1)[0]
            result.setdefault(family, []).append(row)
        return result

    def _index_source(
        self,
        plan: sqlite3.Row,
        batch: sqlite3.Row,
        output_dir: Path,
        source_path: Path,
        provenance: dict[str, list[sqlite3.Row]],
    ) -> bool:
        body = source_path.read_text(encoding="utf-8", errors="replace")
        relative_path = source_path.relative_to(output_dir).as_posix()
        fallback_qualified = relative_path.removesuffix(".java").replace("/", ".")
        parsed = parse_java_source(body, fallback_qualified=fallback_qualified)
        rows = provenance.get(parsed.qualified_name) or provenance.get(fallback_qualified) or []
        logical_names = sorted({str(row["logical_name"]) for row in rows})
        content_hashes = sorted({str(row["content_sha256"]) for row in rows})
        source_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        source_key = hashlib.sha256(
            json.dumps(
                {
                    "release_hash": plan["release_hash"],
                    "artifact": batch["artifact_sha256"],
                    "qualified_name": parsed.qualified_name,
                    "content_hashes": content_hashes,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        symbols_text = " ".join(
            dict.fromkeys(
                [parsed.qualified_name]
                + [str(item["simple_name"]) for item in parsed.symbols]
                + [str(item["signature"]) for item in parsed.symbols]
                + [str(item["target"]) for item in parsed.relations]
            )
        )
        now = _utc_now()
        with self.store.connect() as connection:
            existing = connection.execute(
                """SELECT id, source_sha256, schema_version
                   FROM code_sources WHERE source_key = ?""",
                (source_key,),
            ).fetchone()
            if (
                existing is not None
                and existing["source_sha256"] == source_hash
                and int(existing["schema_version"]) == CODE_INDEX_SCHEMA_VERSION
            ):
                return False
            connection.execute("BEGIN IMMEDIATE")
            values = (
                CODE_INDEX_SCHEMA_VERSION,
                plan["release_id"],
                plan["release_hash"],
                batch["jar_relative_path"],
                batch["artifact_sha256"],
                batch["batch_id"],
                batch["tool"],
                batch["output_reference"],
                relative_path,
                source_hash,
                parsed.package_name,
                parsed.primary_type,
                parsed.qualified_name,
                json.dumps(logical_names, ensure_ascii=False),
                json.dumps(content_hashes),
                len(rows),
                parsed.parser_kind,
                parsed.syntax_error_count,
                symbols_text,
                body,
                now,
            )
            if existing is None:
                cursor = connection.execute(
                    """INSERT INTO code_sources
                       (source_key, schema_version, release_id, release_hash,
                        jar_relative_path, artifact_sha256, batch_id, tool,
                        output_reference, source_relative_path, source_sha256,
                        package_name, primary_type, qualified_name,
                        logical_names_json, content_hashes_json, occurrence_count,
                        parser_kind, syntax_error_count, symbols_text, body, indexed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source_key, *values),
                )
                source_id = int(cursor.lastrowid)
            else:
                source_id = int(existing["id"])
                connection.execute(
                    """UPDATE code_sources SET
                       schema_version=?, release_id=?, release_hash=?,
                       jar_relative_path=?, artifact_sha256=?, batch_id=?, tool=?,
                       output_reference=?, source_relative_path=?, source_sha256=?,
                       package_name=?, primary_type=?, qualified_name=?,
                       logical_names_json=?, content_hashes_json=?, occurrence_count=?,
                       parser_kind=?, syntax_error_count=?, symbols_text=?, body=?,
                       indexed_at=? WHERE id=?""",
                    (*values, source_id),
                )
                connection.execute("DELETE FROM code_symbols WHERE source_id = ?", (source_id,))
                connection.execute("DELETE FROM code_relations WHERE source_id = ?", (source_id,))
            connection.executemany(
                """INSERT INTO code_symbols
                   (source_id, kind, simple_name, qualified_name, signature,
                    visibility, line_start) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        source_id,
                        item["kind"],
                        item["simple_name"],
                        item["qualified_name"],
                        item["signature"],
                        item["visibility"],
                        item["line_start"],
                    )
                    for item in parsed.symbols
                ],
            )
            connection.executemany(
                """INSERT INTO code_relations
                   (source_id, kind, target, source_symbol, confidence, line_start)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        source_id,
                        item["kind"],
                        item["target"],
                        item.get("source_symbol", ""),
                        float(item.get("confidence", 0.0)),
                        item["line_start"],
                    )
                    for item in parsed.relations
                ],
            )
            connection.commit()
        return True

    def search(
        self,
        query: str,
        *,
        release_id: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        self.initialize()
        tokens = _search_tokens(query)
        if not tokens:
            return []
        selected: dict[int, dict[str, Any]] = {}
        release_filter = " AND s.release_id = ?" if release_id else ""
        release_params: list[Any] = [release_id] if release_id else []
        with self.store.connect() as connection:
            exact_rows = connection.execute(
                f"""SELECT s.*, y.kind AS matched_kind, y.simple_name AS matched_symbol,
                            y.signature AS matched_signature, y.line_start AS matched_line
                     FROM code_symbols y JOIN code_sources s ON s.id = y.source_id
                     WHERE (lower(y.simple_name) = lower(?)
                            OR lower(y.qualified_name) = lower(?))
                           {release_filter}
                     ORDER BY CASE
                                WHEN y.kind IN ('class','interface','enum','record') THEN 0
                                WHEN y.kind = 'constructor' THEN 1
                                ELSE 2
                              END,
                              s.qualified_name COLLATE NOCASE LIMIT ?""",
                [query.strip(), query.strip(), *release_params, max(20, limit * 4)],
            ).fetchall()
            for row in exact_rows:
                item = dict(row)
                item["score"] = (
                    120.0
                    if row["matched_kind"] in {"class", "interface", "enum", "record"}
                    else 110.0
                    if row["matched_kind"] == "constructor"
                    else 100.0
                )
                selected.setdefault(int(row["id"]), item)
            fts_rows = connection.execute(
                f"""SELECT s.*, bm25(code_sources_fts, 8.0, 5.0, 1.0) AS rank
                     FROM code_sources_fts
                     JOIN code_sources s ON s.id = code_sources_fts.rowid
                     WHERE code_sources_fts MATCH ? {release_filter}
                     ORDER BY rank LIMIT ?""",
                [_fts_query(tokens), *release_params, max(40, limit * 8)],
            ).fetchall()
            for row in fts_rows:
                item = dict(row)
                item["score"] = max(1.0, 50.0 - float(row["rank"] or 0.0))
                selected.setdefault(int(row["id"]), item)
        results = sorted(
            selected.values(),
            key=lambda item: (-float(item["score"]), str(item["qualified_name"]).casefold()),
        )[: max(1, int(limit))]
        freshness_cache: dict[str, dict[str, Any]] = {}
        for item in results:
            current_release = str(item["release_id"])
            if current_release not in freshness_cache:
                freshness_cache[current_release] = self.catalog.status(current_release)
            freshness = freshness_cache[current_release]
            item["freshness"] = freshness.get("freshness", "unknown")
            item["freshness_warning"] = (
                "O índice pode estar desatualizado porque os JARs mudaram."
                if item["freshness"] != "fresh"
                else ""
            )
            matched_line = int(item.get("matched_line") or 0)
            line_start, line_end, excerpt = _source_excerpt(
                item["body"], tokens, preferred_line=matched_line
            )
            item["line_start"] = line_start
            item["line_end"] = line_end
            item["excerpt"] = excerpt
            item["citation"] = (
                f"Código ERP release {item['release_id']}, JAR {item['jar_relative_path']}, "
                f"classe {item['qualified_name']}, linhas {item['line_start']}-{line_end}, "
                f"SHA-256 {item['source_sha256']}"
            )
            item.pop("body", None)
            item.pop("symbols_text", None)
        return results

    def status(self, release_id: str = "") -> dict[str, Any]:
        self.initialize()
        filter_sql = " WHERE release_id = ?" if release_id else ""
        params: Sequence[Any] = (release_id,) if release_id else ()
        with self.store.connect() as connection:
            row = connection.execute(
                f"""SELECT count(*) AS sources,
                           count(DISTINCT batch_id) AS batches,
                           count(DISTINCT release_id) AS releases,
                           max(indexed_at) AS indexed_at
                    FROM code_sources{filter_sql}""",
                params,
            ).fetchone()
            symbols = connection.execute(
                f"""SELECT count(*) FROM code_symbols y
                     JOIN code_sources s ON s.id = y.source_id
                     {('WHERE s.release_id = ?' if release_id else '')}""",
                params,
            ).fetchone()[0]
            relations = connection.execute(
                f"""SELECT count(*) FROM code_relations r
                     JOIN code_sources s ON s.id = r.source_id
                     {('WHERE s.release_id = ?' if release_id else '')}""",
                params,
            ).fetchone()[0]
            relation_kinds = connection.execute(
                f"""SELECT r.kind, count(*) AS total FROM code_relations r
                     JOIN code_sources s ON s.id = r.source_id
                     {('WHERE s.release_id = ?' if release_id else '')}
                     GROUP BY r.kind ORDER BY r.kind""",
                params,
            ).fetchall()
            parser_kinds = connection.execute(
                f"""SELECT parser_kind, count(*) AS total,
                            sum(CASE WHEN syntax_error_count > 0 THEN 1 ELSE 0 END)
                                AS sources_with_syntax_errors,
                            sum(syntax_error_count) AS syntax_errors
                     FROM code_sources{filter_sql}
                     GROUP BY parser_kind ORDER BY parser_kind""",
                params,
            ).fetchall()
        return {
            "schema_version": CODE_INDEX_SCHEMA_VERSION,
            "release_id": release_id,
            "sources": int(row["sources"]),
            "symbols": int(symbols),
            "relations": int(relations),
            "relation_kinds": {str(item["kind"]): int(item["total"]) for item in relation_kinds},
            "parser_kinds": {
                str(item["parser_kind"]): {
                    "sources": int(item["total"]),
                    "sources_with_syntax_errors": int(item["sources_with_syntax_errors"] or 0),
                    "syntax_errors": int(item["syntax_errors"] or 0),
                }
                for item in parser_kinds
            },
            "tree_sitter_available": tree_sitter_available(),
            "batches": int(row["batches"]),
            "releases": int(row["releases"]),
            "indexed_at": row["indexed_at"] or "",
        }

    def callers(
        self,
        target: str,
        *,
        release_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return grounded syntactic callers without claiming classpath resolution."""

        self.initialize()
        normalized = str(target or "").strip()
        if not normalized:
            return []
        release_filter = " AND s.release_id = ?" if release_id else ""
        params: list[Any] = [normalized, f"%.{normalized}"]
        if release_id:
            params.append(release_id)
        params.append(max(1, int(limit)))
        with self.store.connect() as connection:
            rows = connection.execute(
                f"""SELECT r.kind, r.target, r.source_symbol, r.confidence,
                            r.line_start, s.release_id, s.release_hash,
                            s.jar_relative_path, s.qualified_name, s.source_sha256,
                            s.parser_kind, s.syntax_error_count, s.body
                     FROM code_relations r
                     JOIN code_sources s ON s.id = r.source_id
                     WHERE r.kind IN ('calls', 'constructs')
                       AND (r.target = ? COLLATE NOCASE
                            OR r.target LIKE ? COLLATE NOCASE)
                       {release_filter}
                     ORDER BY r.confidence DESC, s.qualified_name COLLATE NOCASE,
                              r.line_start
                     LIMIT ?""",
                params,
            ).fetchall()
        freshness_cache: dict[str, dict[str, Any]] = {}
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            current_release = str(item["release_id"])
            if current_release not in freshness_cache:
                freshness_cache[current_release] = self.catalog.status(current_release)
            item["freshness"] = freshness_cache[current_release].get("freshness", "unknown")
            item["freshness_warning"] = (
                "O índice pode estar desatualizado porque os JARs mudaram."
                if item["freshness"] != "fresh"
                else ""
            )
            line_start, line_end, excerpt = _source_excerpt(
                str(item.pop("body")),
                _search_tokens(normalized),
                radius=2,
                preferred_line=int(item["line_start"]),
            )
            item["line_start"] = line_start
            item["line_end"] = line_end
            item["excerpt"] = excerpt
            item["resolution"] = "syntactic"
            item["citation"] = (
                f"Código ERP release {item['release_id']}, JAR {item['jar_relative_path']}, "
                f"classe {item['qualified_name']}, linhas {line_start}-{line_end}, "
                f"SHA-256 {item['source_sha256']}"
            )
            results.append(item)
        return results


def parse_java_source(body: str, *, fallback_qualified: str = "") -> ParsedJavaSource:
    try:
        ast = parse_java_ast(body, fallback_qualified=fallback_qualified)
    except (JavaAstUnavailable, RuntimeError, ValueError):
        return _parse_java_source_structural(body, fallback_qualified=fallback_qualified)
    if ast.symbols or ast.qualified_name:
        return ParsedJavaSource(
            package_name=ast.package_name,
            primary_type=ast.primary_type,
            qualified_name=ast.qualified_name,
            symbols=ast.symbols,
            relations=ast.relations,
            parser_kind="tree_sitter",
            syntax_error_count=ast.syntax_error_count,
        )
    return _parse_java_source_structural(body, fallback_qualified=fallback_qualified)


def _parse_java_source_structural(
    body: str, *, fallback_qualified: str = ""
) -> ParsedJavaSource:
    package_match = _PACKAGE_RE.search(body)
    package_name = package_match.group(1) if package_match else ""
    type_matches = list(_TYPE_RE.finditer(body))
    primary_type = type_matches[0].group("name") if type_matches else (
        fallback_qualified.rsplit(".", 1)[-1] if fallback_qualified else ""
    )
    qualified_name = (
        f"{package_name}.{primary_type}" if package_name and primary_type else fallback_qualified
    )
    symbols: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    for match in type_matches:
        name = match.group("name")
        qualified = f"{package_name}.{name}" if package_name else name
        symbols.append(
            {
                "kind": match.group("kind").lstrip("@"),
                "simple_name": name,
                "qualified_name": qualified,
                "signature": _compact(match.group(0).rstrip("{\n")),
                "visibility": _visibility(match.group("mods")),
                "line_start": _line_number(body, match.start()),
            }
        )
        tail = match.group("tail")
        for relation_kind, pattern in (("extends", _EXTENDS_RE), ("implements", _IMPLEMENTS_RE)):
            relation = pattern.search(tail)
            if relation:
                for target in _split_types(relation.group(1)):
                    relations.append(
                        {
                            "kind": relation_kind,
                            "target": target,
                            "source_symbol": qualified,
                            "confidence": 0.55,
                            "line_start": _line_number(body, match.start()),
                        }
                    )
    for match in _METHOD_RE.finditer(body):
        name = match.group("name")
        return_type = _compact(match.group("return")).casefold()
        statement_words = {"return", "throw", "new", "case", "yield", "else"}
        if (
            name in {"if", "for", "while", "switch", "catch", "return", "new"}
            or statement_words & set(return_type.split())
        ):
            continue
        signature = _compact(match.group(0).rstrip("{;"))
        symbol_kind = "constructor" if name == primary_type else "method"
        symbols.append(
            {
                "kind": symbol_kind,
                "simple_name": name,
                "qualified_name": f"{qualified_name}.{name}" if qualified_name else name,
                "signature": signature,
                "visibility": _visibility(
                    f"{match.group('mods')} {match.group('return')}"
                    if symbol_kind == "constructor"
                    else match.group("mods")
                ),
                "line_start": _line_number(body, match.start()),
            }
        )
    for match in _FIELD_RE.finditer(body):
        name = match.group("name")
        symbols.append(
            {
                "kind": "field",
                "simple_name": name,
                "qualified_name": f"{qualified_name}.{name}" if qualified_name else name,
                "signature": _compact(match.group(0)),
                "visibility": _visibility(match.group("mods")),
                "line_start": _line_number(body, match.start()),
            }
        )
    for match in _IMPORT_RE.finditer(body):
        relations.append(
            {
                "kind": "static_import" if match.group(1) else "import",
                "target": match.group(2),
                "source_symbol": qualified_name,
                "confidence": 0.55,
                "line_start": _line_number(body, match.start()),
            }
        )
    return ParsedJavaSource(
        package_name=package_name,
        primary_type=primary_type,
        qualified_name=qualified_name,
        symbols=tuple(symbols),
        relations=tuple(relations),
        parser_kind="structural_fallback",
        syntax_error_count=0,
    )


def _split_types(value: str) -> list[str]:
    return [
        re.sub(r"<.*>", "", item).strip()
        for item in value.split(",")
        if re.sub(r"<.*>", "", item).strip()
    ]


def _visibility(modifiers: str) -> str:
    for value in ("public", "protected", "private"):
        if re.search(rf"\b{value}\b", modifiers):
            return value
    return "package"


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _line_number(body: str, offset: int) -> int:
    return body.count("\n", 0, offset) + 1


def _search_tokens(query: str) -> list[str]:
    return list(dict.fromkeys(_SEARCH_TOKEN_RE.findall(str(query or ""))))


def _fts_query(tokens: Iterable[str]) -> str:
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _source_excerpt(
    body: str,
    tokens: Sequence[str],
    radius: int = 4,
    *,
    preferred_line: int = 0,
) -> tuple[int, int, str]:
    lines = body.splitlines()
    if not lines:
        return 1, 1, ""
    lowered = [line.casefold() for line in lines]
    match_index = (
        min(len(lines) - 1, preferred_line - 1)
        if preferred_line > 0
        else next(
            (
                index
                for index, line in enumerate(lowered)
                if any(token.casefold() in line for token in tokens)
            ),
            0,
        )
    )
    start = max(0, match_index - radius)
    end = min(len(lines), match_index + radius + 1)
    return start + 1, end, "\n".join(lines[start:end])


def _resolve_output(root: Path, value: str) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    allowed = (root / "indice" / "codigo" / "decompilation").resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise DecompilationBatchError("Saída de código fora do índice permitido.") from exc
    return resolved


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    existing = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
