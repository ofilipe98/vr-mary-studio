"""Searchable Java/Kotlin source index with release and bytecode provenance."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .classpath import ClasspathResolver
from .erp_releases import ErpReleaseCatalog
from .java_ast import JavaAstUnavailable, parse_java_ast, tree_sitter_available
from .jvm_batches import (
    DECOMPILED_SOURCE_SUFFIXES,
    PROCESSING_SCHEMA_VERSION,
    DecompilationBatchError,
    DecompilationBatchStore,
    _class_family,
)


CODE_INDEX_SCHEMA_VERSION = 6
JAVA_PARSER_REVISION = 1
_PACKAGE_RE = re.compile(
    r"(?m)^\s*package\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;?\s*$"
)
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
                    class_version INTEGER NOT NULL DEFAULT 0,
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
                CREATE INDEX IF NOT EXISTS idx_code_sources_release_jar
                    ON code_sources(release_id, jar_relative_path);
                CREATE INDEX IF NOT EXISTS idx_code_sources_schema
                    ON code_sources(schema_version);
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
                CREATE INDEX IF NOT EXISTS idx_code_symbols_source_id
                    ON code_symbols(source_id);
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
                CREATE INDEX IF NOT EXISTS idx_code_relations_source_id
                    ON code_relations(source_id);
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
                "class_version",
                "INTEGER NOT NULL DEFAULT 0",
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
            _ensure_column(connection, "code_sources", "parser_revision", "INTEGER NOT NULL DEFAULT 0")
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
            self._migrate_source_identity(connection)
            connection.commit()

    @staticmethod
    def _migrate_source_identity(connection: sqlite3.Connection) -> None:
        """Add release_id to legacy source identities without re-decompiling."""

        # This probe reads the small schema index. Fetching complete source rows
        # would scan their bodies even when every identity is already current.
        if connection.execute(
            "SELECT 1 FROM code_sources WHERE schema_version != ? LIMIT 1",
            (CODE_INDEX_SCHEMA_VERSION,),
        ).fetchone() is None:
            return
        rows = connection.execute(
            """SELECT id, release_id, release_hash, artifact_sha256,
                      class_version, qualified_name, content_hashes_json
               FROM code_sources WHERE schema_version != ? ORDER BY id""",
            (CODE_INDEX_SCHEMA_VERSION,),
        ).fetchall()
        for row in rows:
            try:
                content_hashes = json.loads(row["content_hashes_json"] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                content_hashes = []
            if not isinstance(content_hashes, list):
                content_hashes = []
            source_key = _code_source_key(
                release_id=str(row["release_id"]),
                release_hash=str(row["release_hash"]),
                artifact_sha256=str(row["artifact_sha256"]),
                class_version=int(row["class_version"]),
                qualified_name=str(row["qualified_name"]),
                content_hashes=[str(item) for item in content_hashes],
            )
            duplicate = connection.execute(
                "SELECT id FROM code_sources WHERE source_key = ? AND id != ?",
                (source_key, row["id"]),
            ).fetchone()
            if duplicate is not None:
                connection.execute("DELETE FROM code_sources WHERE id = ?", (row["id"],))
            else:
                connection.execute(
                    """UPDATE code_sources SET source_key = ?, schema_version = ?
                       WHERE id = ?""",
                    (source_key, CODE_INDEX_SCHEMA_VERSION, row["id"]),
                )

    def index_plan(
        self,
        plan_id: str,
        *,
        batch_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        incremental = batch_ids is not None
        requested_batch_ids = tuple(
            dict.fromkeys(str(item) for item in (batch_ids or ()) if str(item))
        )
        with self.store.connect() as connection:
            plan = connection.execute(
                "SELECT * FROM decompilation_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if plan is None:
                raise DecompilationBatchError(f"Plano não encontrado: {plan_id}")
            if int(plan["schema_version"]) != PROCESSING_SCHEMA_VERSION:
                raise DecompilationBatchError(
                    "O plano usa um schema de processamento antigo e não pode ser indexado."
                )
            batch_filter = ""
            batch_parameters: list[Any] = [plan_id]
            if incremental:
                if requested_batch_ids:
                    placeholders = ",".join("?" for _ in requested_batch_ids)
                    batch_filter = f"""AND (
                        b.batch_id IN ({placeholders})
                        OR (SELECT count(*) FROM code_sources s
                            WHERE s.batch_id = b.batch_id
                              AND s.schema_version = ?)
                           < b.actual_source_files
                    )"""
                    batch_parameters.extend(requested_batch_ids)
                    batch_parameters.append(CODE_INDEX_SCHEMA_VERSION)
                else:
                    batch_filter = """AND (
                        SELECT count(*) FROM code_sources s
                        WHERE s.batch_id = b.batch_id
                          AND s.schema_version = ?
                    ) < b.actual_source_files"""
                    batch_parameters.append(CODE_INDEX_SCHEMA_VERSION)
            batches = connection.execute(
                f"""SELECT b.* FROM decompilation_batches b
                    WHERE b.plan_id = ? AND b.state = 'completed'
                      AND b.output_reference != '' AND b.tool != 'reused'
                      {batch_filter}
                    ORDER BY b.ordinal""",
                batch_parameters,
            ).fetchall()
            plan_artifacts = connection.execute(
                """SELECT relative_path, artifact_sha256 FROM plan_artifacts
                   WHERE plan_id = ? ORDER BY ordinal""",
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

        with self.store.connect() as connection:
            connection.execute(
                """DELETE FROM code_sources
                   WHERE release_hash = ? AND schema_version != ?""",
                (plan["release_hash"], CODE_INDEX_SCHEMA_VERSION),
            )
            connection.commit()

        indexed = 0
        unchanged = 0
        reused = 0
        errors: list[dict[str, str]] = []
        locally_decompiled_artifacts = {
            str(batch["artifact_sha256"]) for batch in batches
        }
        for artifact in plan_artifacts:
            if str(artifact["artifact_sha256"]) in locally_decompiled_artifacts:
                continue
            try:
                reused += self._reuse_artifact_sources(plan, artifact)
            except (sqlite3.Error, ValueError) as exc:
                errors.append(
                    {
                        "artifact": str(artifact["relative_path"]),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
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
            source_paths = sorted(
                item
                for item in output_dir.rglob("*")
                if item.is_file()
                and item.suffix.casefold() in DECOMPILED_SOURCE_SUFFIXES
            )

            def _parse_task(sp: Path) -> tuple[Path, dict[str, Any] | None, Exception | None]:
                try:
                    return sp, self._parse_source(plan, batch, output_dir, sp, provenance), None
                except (OSError, UnicodeError, ValueError) as exc:
                    return sp, None, exc

            parse_workers = min(16, os.cpu_count() or 4)
            # Bound retained source text/AST results to one transaction chunk.
            chunk_size = 200
            with ThreadPoolExecutor(max_workers=parse_workers, thread_name_prefix="vr-idx-ast") as pool:
                for chunk_start in range(0, len(source_paths), chunk_size):
                    paths = source_paths[chunk_start : chunk_start + chunk_size]
                    chunk = list(pool.map(_parse_task, paths))
                    valid_items: list[tuple[Path, dict[str, Any]]] = []
                    for sp, data, err in chunk:
                        if err is not None:
                            errors.append(
                                {
                                    "batch_id": batch["batch_id"],
                                    "source": sp.relative_to(output_dir).as_posix(),
                                    "error": f"{type(err).__name__}: {err}",
                                }
                            )
                        elif data is not None:
                            valid_items.append((sp, data))

                    if not valid_items:
                        continue

                    try:
                        now = _utc_now()
                        chunk_indexed = chunk_unchanged = 0
                        with self.store.connect() as connection:
                            connection.execute("BEGIN IMMEDIATE")
                            for sp, data in valid_items:
                                changed = self._apply_indexed_data(connection, plan, batch, data, now)
                                chunk_indexed += int(changed)
                                chunk_unchanged += int(not changed)
                            connection.commit()
                        indexed += chunk_indexed
                        unchanged += chunk_unchanged
                    except (sqlite3.Error, OSError, ValueError):
                        for sp, data in valid_items:
                            try:
                                changed = self._index_source(
                                    plan, batch, output_dir, sp, provenance, data=data
                                )
                            except (OSError, UnicodeError, sqlite3.Error, ValueError) as item_exc:
                                errors.append(
                                    {
                                        "batch_id": batch["batch_id"],
                                        "source": sp.relative_to(output_dir).as_posix(),
                                        "error": f"{type(item_exc).__name__}: {item_exc}",
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
            "incremental": incremental,
            "indexed_sources": indexed,
            "unchanged_sources": unchanged,
            "reused_sources": reused,
            "errors": errors,
            "indexed_at": _utc_now(),
        }

    def _reuse_artifact_sources(
        self,
        plan: sqlite3.Row,
        artifact: sqlite3.Row,
    ) -> int:
        """Clone searchable rows for an identical JAR into another release.

        Decompiled source and AST rows are immutable with respect to the JAR
        SHA-256.  Release-scoped rows are still created so queries and citations
        cannot leak the source release identity.
        """

        artifact_hash = str(artifact["artifact_sha256"])
        with self.store.connect() as connection:
            origin = connection.execute(
                """SELECT release_id, release_hash, count(*) AS total,
                          max(indexed_at) AS latest
                   FROM code_sources
                   WHERE artifact_sha256 = ? AND schema_version = ?
                     AND release_id != ?
                   GROUP BY release_id, release_hash
                   ORDER BY total DESC, latest DESC, release_id, release_hash
                   LIMIT 1""",
                (
                    artifact_hash,
                    CODE_INDEX_SCHEMA_VERSION,
                    plan["release_id"],
                ),
            ).fetchone()
            if origin is None:
                return 0
            sources = connection.execute(
                """SELECT * FROM code_sources
                   WHERE artifact_sha256 = ? AND schema_version = ?
                     AND release_id = ? AND release_hash = ?
                   ORDER BY id""",
                (
                    artifact_hash,
                    CODE_INDEX_SCHEMA_VERSION,
                    origin["release_id"],
                    origin["release_hash"],
                ),
            ).fetchall()
            inserted = 0
            now = _utc_now()
            connection.execute("BEGIN IMMEDIATE")
            for source in sources:
                content_hashes = json.loads(source["content_hashes_json"] or "[]")
                source_key = _code_source_key(
                    release_id=str(plan["release_id"]),
                    release_hash=str(plan["release_hash"]),
                    artifact_sha256=artifact_hash,
                    class_version=int(source["class_version"]),
                    qualified_name=str(source["qualified_name"]),
                    content_hashes=content_hashes,
                )
                existing = connection.execute(
                    "SELECT id FROM code_sources WHERE source_key = ?",
                    (source_key,),
                ).fetchone()
                if existing is not None:
                    continue
                cursor = connection.execute(
                    """INSERT INTO code_sources
                       (source_key, schema_version, release_id, release_hash,
                        jar_relative_path, artifact_sha256, batch_id,
                        class_version, tool, output_reference,
                        source_relative_path, source_sha256, package_name,
                        primary_type, qualified_name, logical_names_json,
                        content_hashes_json, occurrence_count, parser_kind,
                        syntax_error_count, symbols_text, body, indexed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source_key,
                        CODE_INDEX_SCHEMA_VERSION,
                        plan["release_id"],
                        plan["release_hash"],
                        artifact["relative_path"],
                        artifact_hash,
                        plan["plan_id"],
                        int(source["class_version"]),
                        "reused",
                        source["output_reference"],
                        source["source_relative_path"],
                        source["source_sha256"],
                        source["package_name"],
                        source["primary_type"],
                        source["qualified_name"],
                        source["logical_names_json"],
                        source["content_hashes_json"],
                        int(source["occurrence_count"]),
                        source["parser_kind"],
                        int(source["syntax_error_count"]),
                        source["symbols_text"],
                        source["body"],
                        now,
                    ),
                )
                target_id = int(cursor.lastrowid)
                connection.execute(
                    """INSERT INTO code_symbols
                       (source_id, kind, simple_name, qualified_name, signature,
                        visibility, line_start)
                       SELECT ?, kind, simple_name, qualified_name, signature,
                              visibility, line_start
                       FROM code_symbols WHERE source_id = ?""",
                    (target_id, int(source["id"])),
                )
                connection.execute(
                    """INSERT INTO code_relations
                       (source_id, kind, target, source_symbol, confidence, line_start)
                       SELECT ?, kind, target, source_symbol, confidence, line_start
                       FROM code_relations WHERE source_id = ?""",
                    (target_id, int(source["id"])),
                )
                inserted += 1
            connection.commit()
        return inserted

    def _batch_provenance(self, batch_id: str) -> dict[str, list[sqlite3.Row]]:
        with self.store.connect() as connection:
            rows = connection.execute(
                """SELECT o.* FROM batch_members m
                   JOIN class_occurrences o ON o.occurrence_id = m.occurrence_id
                   WHERE m.batch_id = ? ORDER BY m.ordinal""",
                (batch_id,),
            ).fetchall()
        result: dict[str, list[sqlite3.Row]] = {}
        known_names = {str(row["logical_name"]) for row in rows}
        for row in rows:
            family = _class_family(str(row["logical_name"]), known_names)
            result.setdefault(family, []).append(row)
        return result

    def _parse_source(
        self,
        plan: sqlite3.Row,
        batch: sqlite3.Row,
        output_dir: Path,
        source_path: Path,
        provenance: dict[str, list[sqlite3.Row]],
    ) -> dict[str, Any]:
        body = source_path.read_text(encoding="utf-8", errors="replace")
        relative_path = source_path.relative_to(output_dir).as_posix()
        fallback_qualified = relative_path.rsplit(".", 1)[0].replace("/", ".")
        if source_path.suffix.casefold() == ".kt":
            parsed = parse_kotlin_source(body, fallback_qualified=fallback_qualified)
        else:
            parsed = parse_java_source(body, fallback_qualified=fallback_qualified)
        rows = provenance.get(parsed.qualified_name) or provenance.get(fallback_qualified) or []
        logical_names = sorted({str(row["logical_name"]) for row in rows})
        content_hashes = sorted({str(row["content_sha256"]) for row in rows})
        source_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        source_key = _code_source_key(
            release_id=str(plan["release_id"]),
            release_hash=str(plan["release_hash"]),
            artifact_sha256=str(batch["artifact_sha256"]),
            class_version=int(batch["class_version"]),
            qualified_name=parsed.qualified_name,
            content_hashes=content_hashes,
        )
        symbols_text = " ".join(
            dict.fromkeys(
                [parsed.qualified_name]
                + [str(item["simple_name"]) for item in parsed.symbols]
                + [str(item["signature"]) for item in parsed.symbols]
                + [str(item["target"]) for item in parsed.relations]
            )
        )
        return {
            "source_key": source_key,
            "source_hash": source_hash,
            "relative_path": relative_path,
            "parsed": parsed,
            "logical_names": logical_names,
            "content_hashes": content_hashes,
            "rows": rows,
            "symbols_text": symbols_text,
            "body": body,
        }

    def _apply_indexed_data(
        self,
        connection: sqlite3.Connection,
        plan: sqlite3.Row,
        batch: sqlite3.Row,
        data: dict[str, Any],
        now: str,
    ) -> bool:
        source_key = data["source_key"]
        source_hash = data["source_hash"]
        parsed = data["parsed"]
        existing = connection.execute(
            """SELECT id, source_sha256, schema_version, parser_revision
               FROM code_sources WHERE source_key = ?""",
            (source_key,),
        ).fetchone()
        if (
            existing is not None
            and existing["source_sha256"] == source_hash
            and int(existing["schema_version"]) == CODE_INDEX_SCHEMA_VERSION
            and int(existing["parser_revision"]) == JAVA_PARSER_REVISION
        ):
            return False
        values = (
            CODE_INDEX_SCHEMA_VERSION,
            plan["release_id"],
            plan["release_hash"],
            batch["jar_relative_path"],
            batch["artifact_sha256"],
            batch["batch_id"],
            int(batch["class_version"]),
            batch["tool"],
            batch["output_reference"],
            data["relative_path"],
            source_hash,
            parsed.package_name,
            parsed.primary_type,
            parsed.qualified_name,
            json.dumps(data["logical_names"], ensure_ascii=False),
            json.dumps(data["content_hashes"]),
            len(data["rows"]),
            parsed.parser_kind,
            parsed.syntax_error_count,
            data["symbols_text"],
            data["body"],
            now,
            JAVA_PARSER_REVISION,
        )
        if existing is None:
            cursor = connection.execute(
                """INSERT INTO code_sources
                   (source_key, schema_version, release_id, release_hash,
                    jar_relative_path, artifact_sha256, batch_id,
                    class_version, tool,
                    output_reference, source_relative_path, source_sha256,
                    package_name, primary_type, qualified_name,
                    logical_names_json, content_hashes_json, occurrence_count,
                    parser_kind, syntax_error_count, symbols_text, body, indexed_at, parser_revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (source_key, *values),
            )
            source_id = int(cursor.lastrowid)
        else:
            source_id = int(existing["id"])
            connection.execute(
                """UPDATE code_sources SET
                   schema_version=?, release_id=?, release_hash=?,
                   jar_relative_path=?, artifact_sha256=?, batch_id=?,
                   class_version=?, tool=?,
                   output_reference=?, source_relative_path=?, source_sha256=?,
                   package_name=?, primary_type=?, qualified_name=?,
                   logical_names_json=?, content_hashes_json=?, occurrence_count=?,
                   parser_kind=?, syntax_error_count=?, symbols_text=?, body=?,
                   indexed_at=?, parser_revision=? WHERE id=?""",
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
        return True

    def _index_source(
        self,
        plan: sqlite3.Row,
        batch: sqlite3.Row,
        output_dir: Path,
        source_path: Path,
        provenance: dict[str, list[sqlite3.Row]],
        *,
        connection: sqlite3.Connection | None = None,
        data: dict[str, Any] | None = None,
    ) -> bool:
        if data is None:
            data = self._parse_source(plan, batch, output_dir, source_path, provenance)
        now = _utc_now()
        if connection is not None:
            return self._apply_indexed_data(connection, plan, batch, data, now)
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = self._apply_indexed_data(conn, plan, batch, data, now)
            conn.commit()
            return changed

    def search(
        self,
        query: str,
        *,
        release_id: str = "",
        classpath_profile: str = "",
        limit: int = 10,
        artifacts: list[dict[str, Any]] | None = None,
        manifest_hash: str = "",
    ) -> list[dict[str, Any]]:
        self.initialize()
        tokens = _search_tokens(query)
        if not tokens:
            return []
        if str(release_id or "").strip() in ("current", ""):
            try:
                from .erp_releases import ErpReleaseCatalog
                statuses = ErpReleaseCatalog(self.root).list_statuses(full_hash=False)
                if statuses:
                    release_id = str(statuses[0].get("release_id") or "")
            except Exception:
                pass
        selected: dict[int, dict[str, Any]] = {}
        release_filter = " AND s.release_id = ?" if release_id else ""
        release_params: list[Any] = [release_id] if release_id else []
        from .code_context import artifact_sql_filter
        scope_sql, scope_params = artifact_sql_filter(artifacts, manifest_hash)
        release_filter += scope_sql
        release_params.extend(scope_params)
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
        )
        freshness_cache: dict[str, dict[str, Any]] = {}
        resolver = ClasspathResolver(self.root, catalog=self.catalog)
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
            resolver.annotate(item, classpath_profile)
            matched_line = int(item.get("matched_line") or 0)
            line_start, line_end, excerpt = _source_excerpt(
                item["body"], tokens, preferred_line=matched_line
            )
            item["line_start"] = line_start
            item["line_end"] = line_end
            item["excerpt"] = excerpt
            item["citation"] = (
                f"Código ERP release {item['release_id']}, JAR {item['jar_relative_path']}, "
                f"classe {item['qualified_name']}, bytecode "
                f"{_class_version_label(item['class_version'])}, "
                f"classpath {item['classpath_resolution']}, "
                f"linhas {item['line_start']}-{line_end}, "
                f"SHA-256 {item['source_sha256']}"
            )
            item.pop("body", None)
            item.pop("symbols_text", None)
        if classpath_profile:
            results.sort(
                key=lambda item: (
                    _classpath_rank(str(item.get("classpath_resolution") or "")),
                    -float(item["score"]),
                    str(item["qualified_name"]).casefold(),
                )
            )
        return results[: max(1, int(limit))]

    def browse_application_sources(self, context: dict[str, Any], *, query: str = "", offset: int = 0,
                                   source_key: str = "") -> dict[str, Any]:
        """Browse an exact application artifact; paths and bodies come only from the index."""
        from .code_context import artifact_sql_filter
        self.initialize()
        artifacts = [a for a in context["artifacts"] if a["role"] == "application"]
        scope, params = artifact_sql_filter(artifacts, context["manifest_sha256"])
        predicate = "s.release_id=?" + scope
        params.insert(0, context["package_id"])
        with self.store.connect() as connection:
            if source_key:
                row = connection.execute(
                    f"SELECT s.qualified_name, s.body FROM code_sources s WHERE {predicate} AND s.source_key=?",
                    [*params, source_key]).fetchone()
                if row is None:
                    raise DecompilationBatchError("A classe não pertence ao aplicativo e origem selecionados.")
                body = str(row["body"])
                return {"state": "ready", "title": row["qualified_name"], "source_key": source_key, "body": body[:200000],
                        "truncated": len(body) > 200000, "context_label": context["label"]}
            if query.strip():
                predicate += " AND instr(lower(s.qualified_name), lower(?)) > 0"
                params.append(query.strip())
            rows = connection.execute(
                f"SELECT s.source_key, s.qualified_name FROM code_sources s WHERE {predicate} "
                "ORDER BY s.qualified_name COLLATE NOCASE, s.source_key LIMIT 101 OFFSET ?",
                [*params, max(0, offset)]).fetchall()
        return {"state": "ready", "sources": [dict(row) for row in rows[:100]],
                "offset": max(0, offset), "has_more": len(rows) > 100, "context_label": context["label"]}

    def expanded_excerpt(self, result: dict[str, Any], *, max_chars: int = 24000) -> dict[str, Any]:
        """Expand an exact indexed identity without trusting a model's path."""
        if not result.get("source_sha256"):
            return result
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT body FROM code_sources WHERE source_key=? AND release_id=? AND source_sha256=?",
                (result.get("source_key"), result.get("release_id"), result.get("source_sha256")),
            ).fetchone()
        if row is None:
            return result
        body = str(row["body"])
        lines = body.splitlines()
        if len(body) <= max_chars:
            start = 1
            selected = lines
        else:
            start = max(1, int(result.get("line_start", 1)) - 30)
            selected = []
            size = 0
            for line in lines[start - 1:]:
                if size + len(line) + 1 > max_chars:
                    break
                selected.append(line)
                size += len(line) + 1
        return {**result, "excerpt": "\n".join(selected), "line_start": start,
                "line_end": start + len(selected) - 1}

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
            class_versions = connection.execute(
                f"""SELECT class_version, count(*) AS total
                     FROM code_sources{filter_sql}
                     GROUP BY class_version ORDER BY class_version""",
                params,
            ).fetchall()
            jars = [
                str(item["jar_relative_path"])
                for item in connection.execute(
                    f"""SELECT DISTINCT jar_relative_path
                         FROM code_sources{filter_sql}
                         ORDER BY jar_relative_path COLLATE NOCASE""",
                    params,
                )
            ]
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
            "class_versions": {
                _class_version_label(item["class_version"]): int(item["total"])
                for item in class_versions
            },
            "jar_count": len(jars),
            "jars": jars,
            "tree_sitter_available": tree_sitter_available(),
            "batches": int(row["batches"]),
            "releases": int(row["releases"]),
            "indexed_at": row["indexed_at"] or "",
        }

    def coverage(self, release_id: str) -> dict[str, Any]:
        """Return JAR-level processing coverage without expensive symbol counts."""

        self.initialize()
        manifest = self.catalog.load_manifest(release_id)
        release_hash = str(manifest.get("release_manifest_sha256") or "")
        manifest_jars = {
            str(item.get("relative_path") or "")
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and item.get("relative_path")
        }
        with self.store.connect() as connection:
            indexed_jars = {
                str(item["jar_relative_path"])
                for item in connection.execute(
                    """SELECT DISTINCT jar_relative_path FROM code_sources
                       WHERE release_id = ?""",
                    (release_id,),
                )
            }
            completed_jars = {
                str(item["relative_path"])
                for item in connection.execute(
                    """SELECT DISTINCT a.relative_path
                       FROM plan_artifacts a
                       JOIN decompilation_plans p ON p.plan_id = a.plan_id
                       WHERE p.release_id = ? AND p.release_hash = ?
                          AND p.schema_version = ? AND p.state = 'completed'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM class_occurrences o
                              JOIN class_contents c
                                ON c.content_sha256 = o.content_sha256
                              WHERE o.release_hash = p.release_hash
                                AND o.jar_relative_path = a.relative_path
                                AND o.artifact_sha256 = a.artifact_sha256
                                AND (c.state != 'completed'
                                     OR c.processing_schema_version != ?)
                          )""",
                    (
                        release_id,
                        release_hash,
                        PROCESSING_SCHEMA_VERSION,
                        PROCESSING_SCHEMA_VERSION,
                    ),
                )
            }
        # A completed plan is not sufficient evidence on its own. The classes
        # must be processed with the current schema and the JAR must either have
        # searchable sources or contain no class entries at all.
        empty_jars = {
            str(item.get("relative_path") or "")
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict)
            and item.get("relative_path")
            and int(item.get("class_count") or 0) == 0
        }
        covered = completed_jars & manifest_jars & (indexed_jars | empty_jars)
        remaining = manifest_jars - covered
        total = len(manifest_jars)
        return {
            "release_id": release_id,
            "release_manifest_sha256": release_hash,
            "expected_jar_count": total,
            "covered_jar_count": len(covered),
            "coverage_ratio": round(len(covered) / total, 6) if total else 0.0,
            "covered_jars": sorted(covered, key=str.casefold),
            "remaining_jar_count": len(remaining),
            "remaining_jars": sorted(remaining, key=str.casefold),
            "indexed_source_jar_count": len(indexed_jars),
            "indexed_source_jars": sorted(indexed_jars, key=str.casefold),
        }

    def callers(
        self,
        target: str,
        *,
        release_id: str = "",
        classpath_profile: str = "",
        limit: int = 50,
        artifacts: list[dict[str, Any]] | None = None,
        manifest_hash: str = "",
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
        from .code_context import artifact_sql_filter
        scope_sql, scope_params = artifact_sql_filter(artifacts, manifest_hash)
        release_filter += scope_sql
        params.extend(scope_params)
        params.append(max(1, int(limit)))
        with self.store.connect() as connection:
            rows = connection.execute(
                f"""SELECT r.kind, r.target, r.source_symbol, r.confidence,
                            r.line_start, s.release_id, s.release_hash,
                            s.jar_relative_path, s.qualified_name, s.class_version,
                            s.source_sha256, s.logical_names_json,
                            s.content_hashes_json, s.parser_kind,
                            s.syntax_error_count, s.body
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
        resolver = ClasspathResolver(self.root, catalog=self.catalog)
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
            resolver.annotate(item, classpath_profile)
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
                f"classe {item['qualified_name']}, bytecode "
                f"{_class_version_label(item['class_version'])}, "
                f"classpath {item['classpath_resolution']}, "
                f"linhas {line_start}-{line_end}, "
                f"SHA-256 {item['source_sha256']}"
            )
            results.append(item)
        if classpath_profile:
            results.sort(
                key=lambda item: (
                    _classpath_rank(str(item.get("classpath_resolution") or "")),
                    -float(item.get("confidence") or 0.0),
                    str(item.get("qualified_name") or "").casefold(),
                )
            )
        return results[: max(1, int(limit))]


def _class_version_label(value: object) -> str:
    version = int(value or 0)
    return "base" if version == 0 else f"Java {version}"


def _classpath_rank(value: str) -> int:
    return {
        "resolved": 0,
        "unique": 1,
        "ambiguous": 2,
        "unknown": 3,
        "shadowed": 4,
    }.get(value, 5)


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


def parse_kotlin_source(body: str, *, fallback_qualified: str = "") -> ParsedJavaSource:
    package_match = _PACKAGE_RE.search(body)
    package_name = package_match.group(1) if package_match else ""
    primary_type = fallback_qualified.rsplit(".", 1)[-1] if fallback_qualified else ""
    qualified_name = (
        f"{package_name}.{primary_type}"
        if package_name and primary_type
        else fallback_qualified
    )
    return ParsedJavaSource(
        package_name=package_name,
        primary_type=primary_type,
        qualified_name=qualified_name,
        symbols=(),
        relations=(),
        parser_kind="kotlin_structural",
        syntax_error_count=0,
    )


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


def _code_source_key(
    *,
    release_id: str,
    release_hash: str,
    artifact_sha256: str,
    class_version: int,
    qualified_name: str,
    content_hashes: Sequence[str],
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "release_id": release_id,
                "release_hash": release_hash,
                "artifact": artifact_sha256,
                "class_version": int(class_version),
                "qualified_name": qualified_name,
                "content_hashes": list(content_hashes),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


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
