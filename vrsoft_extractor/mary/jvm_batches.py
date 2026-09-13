"""Deterministic, resumable class batches for ERP JAR decompilation."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable, Iterator, Sequence

from .erp_releases import (
    ErpReleaseCatalog,
    normalize_class_entry,
    sha256_file,
)
from .code_processing_policy import processing_window_status
from .jvm_toolchain import DecompileRequest, DecompileResult, JvmToolchain


warnings.filterwarnings(
    "ignore",
    message=r"Overlapped entries: .*possible zip bomb.*",
    category=UserWarning,
)


PROCESSING_SCHEMA_VERSION = 2
DEFAULT_MAX_CLASSES = 1000
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
DECOMPILED_SOURCE_SUFFIXES = frozenset({".java", ".kt"})


class DecompilationBatchError(RuntimeError):
    """Controlled failure while planning or executing decompilation batches."""


class DecompilationBatchStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.code_index = self.root / "indice" / "codigo"
        self.database_path = self.code_index / "processing.sqlite"
        self.work_dir = self.code_index / "decompilation"
        self.lock_path = self.code_index / "decompilation.lock"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.code_index.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        self._initialize(connection)
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS decompilation_plans (
                plan_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                release_id TEXT NOT NULL,
                release_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                max_classes INTEGER NOT NULL,
                max_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plan_artifacts (
                plan_id TEXT NOT NULL REFERENCES decompilation_plans(plan_id),
                ordinal INTEGER NOT NULL,
                relative_path TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                PRIMARY KEY (plan_id, relative_path)
            );
            CREATE TABLE IF NOT EXISTS class_contents (
                content_sha256 TEXT PRIMARY KEY,
                byte_size INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                output_reference TEXT NOT NULL DEFAULT '',
                processing_schema_version INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS class_occurrences (
                occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                release_id TEXT NOT NULL,
                release_hash TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                jar_relative_path TEXT NOT NULL,
                entry_index INTEGER NOT NULL,
                entry_name TEXT NOT NULL,
                logical_name TEXT NOT NULL,
                class_version INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL REFERENCES class_contents(content_sha256),
                byte_size INTEGER NOT NULL,
                UNIQUE (release_hash, jar_relative_path, entry_index)
            );
            CREATE INDEX IF NOT EXISTS idx_occurrences_release_artifact
                ON class_occurrences(release_hash, jar_relative_path);
            CREATE INDEX IF NOT EXISTS idx_occurrences_content
                ON class_occurrences(content_sha256);
            CREATE INDEX IF NOT EXISTS idx_occurrences_release_id
                ON class_occurrences(release_id);
            CREATE TABLE IF NOT EXISTS decompilation_batches (
                batch_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL REFERENCES decompilation_plans(plan_id),
                ordinal INTEGER NOT NULL,
                jar_relative_path TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                class_version INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL,
                class_count INTEGER NOT NULL,
                bytecode_bytes INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                tool TEXT NOT NULL DEFAULT '',
                output_reference TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                expected_source_files INTEGER NOT NULL DEFAULT 0,
                actual_source_files INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (plan_id, ordinal)
            );
            CREATE INDEX IF NOT EXISTS idx_batches_plan_state
                ON decompilation_batches(plan_id, state, ordinal);
            CREATE TABLE IF NOT EXISTS batch_members (
                batch_id TEXT NOT NULL REFERENCES decompilation_batches(batch_id),
                ordinal INTEGER NOT NULL,
                occurrence_id INTEGER NOT NULL REFERENCES class_occurrences(occurrence_id),
                content_sha256 TEXT NOT NULL,
                PRIMARY KEY (batch_id, ordinal),
                UNIQUE (batch_id, occurrence_id)
            );
            CREATE INDEX IF NOT EXISTS idx_batch_members_occurrence
                ON batch_members(occurrence_id);
            """
        )
        batch_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(decompilation_batches)")
        }
        if "expected_source_files" not in batch_columns:
            connection.execute(
                """ALTER TABLE decompilation_batches
                   ADD COLUMN expected_source_files INTEGER NOT NULL DEFAULT 0"""
            )
        if "actual_source_files" not in batch_columns:
            connection.execute(
                """ALTER TABLE decompilation_batches
                   ADD COLUMN actual_source_files INTEGER NOT NULL DEFAULT 0"""
            )
        if "class_version" not in batch_columns:
            connection.execute(
                """ALTER TABLE decompilation_batches
                   ADD COLUMN class_version INTEGER NOT NULL DEFAULT 0"""
            )
        content_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(class_contents)")
        }
        if "processing_schema_version" not in content_columns:
            connection.execute(
                """ALTER TABLE class_contents
                   ADD COLUMN processing_schema_version INTEGER NOT NULL DEFAULT 0"""
            )
        connection.commit()

    def status(self, plan_id: str = "") -> dict[str, Any] | list[dict[str, Any]]:
        with self.connect() as connection:
            if plan_id:
                row = connection.execute(
                    "SELECT * FROM decompilation_plans WHERE plan_id = ?", (plan_id,)
                ).fetchone()
                if row is None:
                    raise DecompilationBatchError(f"Plano não encontrado: {plan_id}")
                return self._plan_status(connection, row)
            rows = connection.execute(
                "SELECT * FROM decompilation_plans ORDER BY created_at DESC, plan_id"
            ).fetchall()
            return [self._plan_status(connection, row) for row in rows]

    @staticmethod
    def _plan_status(
        connection: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, Any]:
        counts = {
            item["state"]: int(item["total"])
            for item in connection.execute(
                """SELECT state, count(*) AS total
                   FROM decompilation_batches WHERE plan_id = ? GROUP BY state""",
                (row["plan_id"],),
            )
        }
        artifacts = [
            item["relative_path"]
            for item in connection.execute(
                """SELECT relative_path FROM plan_artifacts
                   WHERE plan_id = ? ORDER BY ordinal""",
                (row["plan_id"],),
            )
        ]
        totals = connection.execute(
            """SELECT count(*) AS batches,
                      coalesce(sum(class_count), 0) AS classes,
                      coalesce(sum(bytecode_bytes), 0) AS bytes,
                      coalesce(sum(expected_source_files), 0) AS expected_sources,
                      coalesce(sum(actual_source_files), 0) AS actual_sources
               FROM decompilation_batches WHERE plan_id = ?""",
            (row["plan_id"],),
        ).fetchone()
        attention_batches = [
            {
                "batch_id": item["batch_id"],
                "ordinal": int(item["ordinal"]),
                "jar_relative_path": item["jar_relative_path"],
                "state": item["state"],
                "class_version": int(item["class_version"]),
                "attempt_count": int(item["attempt_count"]),
                "expected_source_files": int(item["expected_source_files"]),
                "actual_source_files": int(item["actual_source_files"]),
                "error": item["last_error"],
            }
            for item in connection.execute(
                """SELECT * FROM decompilation_batches
                   WHERE plan_id = ? AND state IN ('failed', 'partial')
                   ORDER BY ordinal""",
                (row["plan_id"],),
            )
        ]
        current_row = connection.execute(
            """SELECT batch_id, ordinal, jar_relative_path, state, class_version,
                      class_count, attempt_count
               FROM decompilation_batches
               WHERE plan_id = ? AND state IN ('running', 'pending', 'failed', 'partial')
               ORDER BY CASE state
                          WHEN 'running' THEN 0
                          WHEN 'pending' THEN 1
                          WHEN 'failed' THEN 2
                          ELSE 3
                        END,
                        ordinal
               LIMIT 1""",
            (row["plan_id"],),
        ).fetchone()
        current_batch = (
            {
                "batch_id": current_row["batch_id"],
                "ordinal": int(current_row["ordinal"]),
                "jar_relative_path": current_row["jar_relative_path"],
                "state": current_row["state"],
                "class_version": int(current_row["class_version"]),
                "class_count": int(current_row["class_count"]),
                "attempt_count": int(current_row["attempt_count"]),
            }
            if current_row is not None
            else {}
        )
        return {
            "plan_id": row["plan_id"],
            "schema_version": int(row["schema_version"]),
            "release_id": row["release_id"],
            "release_manifest_sha256": row["release_hash"],
            "state": row["state"],
            "max_classes": row["max_classes"],
            "max_bytes": row["max_bytes"],
            "selected_jars": artifacts,
            "batch_count": int(totals["batches"]),
            "class_content_count": int(totals["classes"]),
            "bytecode_bytes": int(totals["bytes"]),
            "expected_source_files": int(totals["expected_sources"]),
            "actual_source_files": int(totals["actual_sources"]),
            "batches_by_state": counts,
            "current_batch": current_batch,
            "attention_batches": attention_batches,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def cancel_active_plans(self, release_id: str, *, relative_jars: Iterable[str] = ()) -> list[str]:
        with _exclusive_file_lock(self.lock_path), self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT plan_id FROM decompilation_plans
                   WHERE release_id = ? AND state != 'completed'""",
                (release_id,),
            ).fetchall()
            plan_ids = [str(row["plan_id"]) for row in rows]
            selected = set(relative_jars)
            if selected:
                scoped_ids = []
                for plan_id in plan_ids:
                    jars = {str(row[0]) for row in connection.execute(
                        "SELECT relative_path FROM plan_artifacts WHERE plan_id = ?", (plan_id,)
                    )}
                    if jars.intersection(selected):
                        if not jars.issubset(selected):
                            raise DecompilationBatchError("O plano inclui outros aplicativos; cancele o lote completo.")
                        scoped_ids.append(plan_id)
                plan_ids = scoped_ids
            if plan_ids:
                placeholders = ",".join("?" for _ in plan_ids)
                connection.execute(
                    f"""DELETE FROM batch_members WHERE batch_id IN
                         (SELECT batch_id FROM decompilation_batches
                          WHERE plan_id IN ({placeholders}))""",
                    plan_ids,
                )
                connection.execute(
                    f"DELETE FROM decompilation_batches WHERE plan_id IN ({placeholders})",
                    plan_ids,
                )
                connection.execute(
                    f"DELETE FROM plan_artifacts WHERE plan_id IN ({placeholders})",
                    plan_ids,
                )
                connection.execute(
                    f"DELETE FROM decompilation_plans WHERE plan_id IN ({placeholders})",
                    plan_ids,
                )
                connection.commit()
            return plan_ids


class DecompilationBatchPlanner:
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

    def plan(
        self,
        release_id: str,
        relative_jars: Iterable[str] = (),
        *,
        max_classes: int = DEFAULT_MAX_CLASSES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        max_classes = max(1, int(max_classes))
        max_bytes = max(1, int(max_bytes))
        manifest = self.catalog.load_manifest(release_id)
        freshness = self.catalog.status(release_id)
        if manifest.get("state") != "ready" or freshness.get("freshness") != "fresh":
            raise DecompilationBatchError(
                "A release precisa estar pronta e atual antes do planejamento."
            )
        release_hash = str(manifest.get("release_manifest_sha256") or "")
        artifacts = {
            str(item.get("relative_path") or ""): item
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and item.get("relative_path")
        }
        requested = tuple(
            dict.fromkeys(str(item).replace("\\", "/") for item in relative_jars)
        )
        selected_paths = (
            tuple(sorted(requested, key=str.casefold))
            if requested
            else tuple(sorted(artifacts, key=str.casefold))
        )
        missing = [item for item in selected_paths if item not in artifacts]
        if missing:
            raise DecompilationBatchError(
                "JARs não encontrados no manifesto: " + ", ".join(missing)
            )
        selected = [(path, artifacts[path]) for path in selected_paths]
        plan_id = _stable_id(
            "plan",
            {
                "schema": PROCESSING_SCHEMA_VERSION,
                "release_id": release_id,
                "release_hash": release_hash,
                "artifacts": [
                    [path, str(artifact.get("sha256") or "")]
                    for path, artifact in selected
                ],
                "max_classes": max_classes,
                "max_bytes": max_bytes,
            },
        )

        expected_classes = sum(
            int(artifact.get("class_count") or 0) for _path, artifact in selected
        )
        resume_empty_plan = False
        scanned_classes = 0
        with self.store.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM decompilation_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if existing:
                existing_plan = connection.execute(
                    "SELECT * FROM decompilation_plans WHERE plan_id = ?", (plan_id,)
                ).fetchone()
                status = self.store._plan_status(
                    connection,
                    existing_plan,
                )
                pending_classes = int(
                    connection.execute(
                        """SELECT count(*)
                           FROM class_occurrences o
                           JOIN plan_artifacts a
                             ON a.plan_id = ?
                            AND a.relative_path = o.jar_relative_path
                            AND a.artifact_sha256 = o.artifact_sha256
                           JOIN class_contents c
                             ON c.content_sha256 = o.content_sha256
                           WHERE o.release_hash = ?
                             AND (c.state != 'completed'
                                  OR c.processing_schema_version != ?)""",
                        (plan_id, release_hash, PROCESSING_SCHEMA_VERSION),
                    ).fetchone()[0]
                )
                scanned_classes = int(
                    connection.execute(
                        """SELECT count(*)
                           FROM class_occurrences o
                           JOIN plan_artifacts a
                             ON a.plan_id = ?
                            AND a.relative_path = o.jar_relative_path
                            AND a.artifact_sha256 = o.artifact_sha256
                           WHERE o.release_hash = ?""",
                        (plan_id, release_hash),
                    ).fetchone()[0]
                )
                resume_empty_plan = bool(
                    int(status["batch_count"]) == 0
                    and expected_classes > 0
                    and (
                        status["state"] in {"planning", "failed"}
                        or pending_classes > 0
                        or (expected_classes > 0 and scanned_classes == 0)
                    )
                )
                if not resume_empty_plan:
                    return status
                connection.execute(
                    """UPDATE decompilation_plans
                       SET state = 'planning', updated_at = ? WHERE plan_id = ?""",
                    (_utc_now(), plan_id),
                )
                connection.commit()

            if not resume_empty_plan:
                now = _utc_now()
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO decompilation_plans
                       (plan_id, schema_version, release_id, release_hash, state,
                        max_classes, max_bytes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'planning', ?, ?, ?, ?)""",
                    (
                        plan_id,
                        PROCESSING_SCHEMA_VERSION,
                        release_id,
                        release_hash,
                        max_classes,
                        max_bytes,
                        now,
                        now,
                    ),
                )
                for ordinal, (relative_path, artifact) in enumerate(selected):
                    connection.execute(
                        """INSERT INTO plan_artifacts
                           (plan_id, ordinal, relative_path, artifact_sha256)
                           VALUES (?, ?, ?, ?)""",
                        (plan_id, ordinal, relative_path, str(artifact["sha256"])),
                    )
                connection.commit()
                scanned_classes = int(
                    connection.execute(
                        """SELECT count(*)
                           FROM class_occurrences o
                           JOIN plan_artifacts a
                             ON a.plan_id = ?
                            AND a.relative_path = o.jar_relative_path
                            AND a.artifact_sha256 = o.artifact_sha256
                           WHERE o.release_hash = ?""",
                        (plan_id, release_hash),
                    ).fetchone()[0]
                )

        try:
            if scanned_classes < expected_classes:
                self._scan_occurrences(
                    release_id,
                    release_hash,
                    manifest,
                    selected,
                    progress=progress,
                )
            elif progress is not None:
                progress(
                    {
                        "phase": "scanning",
                        "current": expected_classes,
                        "total": expected_classes,
                        "resumed": True,
                    }
                )
            self._create_batches(
                plan_id,
                release_hash,
                selected,
                max_classes,
                max_bytes,
                progress=progress,
            )
        except Exception as exc:
            with self.store.connect() as connection:
                connection.execute(
                    """UPDATE decompilation_plans
                       SET state = 'failed', updated_at = ? WHERE plan_id = ?""",
                    (_utc_now(), plan_id),
                )
                connection.commit()
            if isinstance(exc, DecompilationBatchError):
                raise
            raise DecompilationBatchError(
                f"Falha ao planejar lotes: {type(exc).__name__}: {exc}"
            ) from exc
        return self.store.status(plan_id)  # type: ignore[return-value]

    def _scan_occurrences(
        self,
        release_id: str,
        release_hash: str,
        manifest: dict[str, Any],
        selected: Sequence[tuple[str, dict[str, Any]]],
        *,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        source = _source_path(self.root, manifest)
        expected_classes = sum(
            int(artifact.get("class_count") or 0) for _path, artifact in selected
        )
        scanned_classes = 0
        if progress is not None:
            progress({"phase": "scanning", "current": 0, "total": expected_classes})
        for relative_path, artifact in selected:
            jar_path = _safe_child(source / relative_path, source)
            if sha256_file(jar_path) != str(artifact["sha256"]):
                raise DecompilationBatchError(
                    f"O JAR mudou depois do inventário: {relative_path}"
                )
            rows: list[tuple[Any, ...]] = []
            try:
                with zipfile.ZipFile(jar_path) as archive, warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r"Overlapped entries: .*possible zip bomb.*",
                        category=UserWarning,
                    )
                    for entry_index, info in enumerate(archive.infolist()):
                        normalized = normalize_class_entry(info.filename)
                        if normalized is None or info.is_dir():
                            continue
                        bytecode = archive.read(info)
                        logical_name, class_version = normalized
                        content_hash = hashlib.sha256(bytecode).hexdigest()
                        scanned_classes += 1
                        rows.append(
                            (
                                content_hash,
                                len(bytecode),
                                release_id,
                                release_hash,
                                str(artifact["sha256"]),
                                relative_path,
                                entry_index,
                                info.filename,
                                logical_name,
                                class_version,
                            )
                        )
                        if progress is not None and scanned_classes % 256 == 0:
                            progress(
                                {
                                    "phase": "scanning",
                                    "current": scanned_classes,
                                    "total": expected_classes,
                                    "jar": relative_path,
                                }
                            )
            except (OSError, RuntimeError, zipfile.BadZipFile, KeyError) as exc:
                raise DecompilationBatchError(
                    f"Falha ao ler {relative_path}: {type(exc).__name__}: {exc}"
                ) from exc
            now = _utc_now()
            with self.store.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    """INSERT INTO class_contents
                       (content_sha256, byte_size, state, updated_at)
                       VALUES (?, ?, 'pending', ?)
                       ON CONFLICT(content_sha256) DO NOTHING""",
                    [(row[0], row[1], now) for row in rows],
                )
                connection.executemany(
                    """INSERT INTO class_occurrences
                       (content_sha256, byte_size, release_id, release_hash,
                        artifact_sha256, jar_relative_path, entry_index,
                        entry_name, logical_name, class_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(release_hash, jar_relative_path, entry_index)
                       DO NOTHING""",
                    rows,
                )
                connection.commit()
        if progress is not None:
            progress(
                {
                    "phase": "scanning",
                    "current": scanned_classes,
                    "total": expected_classes,
                }
            )

    def _create_batches(
        self,
        plan_id: str,
        release_hash: str,
        selected: Sequence[tuple[str, dict[str, Any]]],
        max_classes: int,
        max_bytes: int,
        *,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if progress is not None:
            progress({"phase": "batch_planning", "current": 0, "total": 1})
        with self.store.connect() as connection:
            occurrences = connection.execute(
                """SELECT o.*
                   FROM class_occurrences o
                   JOIN plan_artifacts a
                     ON a.plan_id = ?
                    AND a.relative_path = o.jar_relative_path
                    AND a.artifact_sha256 = o.artifact_sha256
                   LEFT JOIN class_contents c
                     ON c.content_sha256 = o.content_sha256
                   WHERE o.release_hash = ?
                     AND (c.state != 'completed'
                          OR c.processing_schema_version != ?)
                   ORDER BY a.ordinal, o.class_version, lower(o.logical_name),
                            o.entry_name, o.entry_index""",
                (plan_id, release_hash, PROCESSING_SCHEMA_VERSION),
            ).fetchall()

            representatives: list[sqlite3.Row] = []
            seen: set[str] = set()
            occurrence_count = len(occurrences)
            if progress is not None:
                progress(
                    {
                        "phase": "batch_planning",
                        "current": 0,
                        "total": max(1, occurrence_count),
                    }
                )
            for occurrence_ordinal, row in enumerate(occurrences, start=1):
                if row["content_sha256"] not in seen:
                    seen.add(row["content_sha256"])
                    representatives.append(row)
                if progress is not None and occurrence_ordinal % 1000 == 0:
                    progress(
                        {
                            "phase": "batch_planning",
                            "current": occurrence_ordinal,
                            "total": max(1, occurrence_count),
                        }
                    )

            by_artifact: dict[str, list[sqlite3.Row]] = {
                relative_path: [] for relative_path, _ in selected
            }
            for row in representatives:
                by_artifact[row["jar_relative_path"]].append(row)

            batches: list[tuple[str, str, int, list[sqlite3.Row]]] = []
            for relative_path, artifact in selected:
                known_names = {
                    str(row["logical_name"])
                    for row in by_artifact[relative_path]
                }
                families: list[list[sqlite3.Row]] = []
                current_key: tuple[int, str] | None = None
                for row in by_artifact[relative_path]:
                    key = (
                        int(row["class_version"]),
                        _class_family(row["logical_name"], known_names),
                    )
                    if key != current_key:
                        families.append([])
                        current_key = key
                    families[-1].append(row)

                current: list[sqlite3.Row] = []
                current_bytes = 0
                current_version: int | None = None
                for family in families:
                    family_version = int(family[0]["class_version"])
                    family_bytes = sum(int(row["byte_size"]) for row in family)
                    exceeds = current and (
                        family_version != current_version
                        or len(current) + len(family) > max_classes
                        or current_bytes + family_bytes > max_bytes
                    )
                    if exceeds:
                        batches.append(
                            (
                                relative_path,
                                str(artifact["sha256"]),
                                int(current_version or 0),
                                current,
                            )
                        )
                        current = []
                        current_bytes = 0
                    current_version = family_version
                    current.extend(family)
                    current_bytes += family_bytes
                if current:
                    batches.append(
                        (
                            relative_path,
                            str(artifact["sha256"]),
                            int(current_version or 0),
                            current,
                        )
                    )

            now = _utc_now()
            connection.execute("BEGIN IMMEDIATE")
            for ordinal, (
                relative_path,
                artifact_hash,
                class_version,
                members,
            ) in enumerate(batches):
                batch_id = _stable_id(
                    "batch",
                    {
                        "plan_id": plan_id,
                        "ordinal": ordinal,
                        "artifact": artifact_hash,
                        "class_version": class_version,
                        "contents": [row["content_sha256"] for row in members],
                    },
                )
                connection.execute(
                    """INSERT INTO decompilation_batches
                       (batch_id, plan_id, ordinal, jar_relative_path,
                        artifact_sha256, class_version, state, class_count,
                        bytecode_bytes,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
                    (
                        batch_id,
                        plan_id,
                        ordinal,
                        relative_path,
                        artifact_hash,
                        class_version,
                        len(members),
                        sum(int(row["byte_size"]) for row in members),
                        now,
                        now,
                    ),
                )
                connection.executemany(
                    """INSERT INTO batch_members
                       (batch_id, ordinal, occurrence_id, content_sha256)
                       VALUES (?, ?, ?, ?)""",
                    [
                        (batch_id, member_ordinal, row["occurrence_id"], row["content_sha256"])
                        for member_ordinal, row in enumerate(members)
                    ],
                )
            state = "completed" if not batches else "pending"
            connection.execute(
                """UPDATE decompilation_plans
                   SET state = ?, updated_at = ? WHERE plan_id = ?""",
                (state, now, plan_id),
            )
            connection.commit()
        if progress is not None:
            progress(
                {
                    "phase": "batch_planning",
                    "current": max(1, occurrence_count),
                    "total": max(1, occurrence_count),
                }
            )


class DecompilationBatchExecutor:
    def __init__(
        self,
        root: str | Path,
        *,
        catalog: ErpReleaseCatalog | None = None,
        store: DecompilationBatchStore | None = None,
        adapters: Sequence[Any] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.store = store or DecompilationBatchStore(self.root)
        self.adapters = tuple(adapters or JvmToolchain(self.root).adapters())
        self._database_write_lock = Lock()

    def run(
        self,
        plan_id: str,
        *,
        limit: int = 1,
        max_heap_mb: int = 2048,
        timeout_seconds: int = 300,
        max_cpu_cores: int = 1,
        max_workers: int = 1,
        process_priority: str = "low",
        processing_window: str = "always",
    ) -> dict[str, Any]:
        limit = max(1, int(limit))
        worker_count = min(limit, max(1, int(max_workers)))
        cores_per_worker = max(1, int(max_cpu_cores) // worker_count)
        results: list[dict[str, Any]] = []
        with _exclusive_file_lock(self.store.lock_path):
            plan = self._load_plan(plan_id)
            self._verify_release(plan)
            self._recover_interrupted(plan_id)
            claimed: list[sqlite3.Row] = []
            for _ in range(limit):
                window = processing_window_status(processing_window)
                if not window["allowed"]:
                    raise DecompilationBatchError(
                        "Processamento fora da janela ociosa configurada: "
                        + str(window["label"])
                    )
                batch = self._claim_next(plan_id)
                if batch is None:
                    break
                claimed.append(batch)
            active_workers = min(worker_count, max(1, len(claimed)))
            cores_per_worker = max(1, int(max_cpu_cores) // active_workers)
            if worker_count > 1 and len(claimed) > 1:
                with ThreadPoolExecutor(
                    max_workers=active_workers,
                    thread_name_prefix="vr-decompile",
                ) as pool:
                    futures = [
                        pool.submit(
                            self._execute_batch,
                            plan,
                            batch,
                            max_heap_mb=max_heap_mb,
                            timeout_seconds=timeout_seconds,
                            max_cpu_cores=cores_per_worker,
                            cpu_core_offset=(ordinal % active_workers)
                            * cores_per_worker,
                            process_priority=process_priority,
                        )
                        for ordinal, batch in enumerate(claimed)
                    ]
                    results.extend(future.result() for future in futures)
            else:
                results.extend(
                    self._execute_batch(
                        plan,
                        batch,
                        max_heap_mb=max_heap_mb,
                        timeout_seconds=timeout_seconds,
                        max_cpu_cores=cores_per_worker,
                        cpu_core_offset=0,
                        process_priority=process_priority,
                    )
                    for batch in claimed
                )
            self._refresh_plan_state(plan_id)
        return {
            "plan": self.store.status(plan_id),
            "executed": results,
            "global_concurrency": min(worker_count, max(1, len(claimed))),
            "max_cpu_cores": max(1, int(max_cpu_cores)),
            "cpu_cores_per_worker": cores_per_worker,
            "process_priority": (
                "low" if str(process_priority).casefold() == "low" else "normal"
            ),
            "processing_window": str(processing_window),
        }

    def retry(self, batch_id: str) -> dict[str, Any]:
        with self.store.connect() as connection:
            row = connection.execute(
                """SELECT b.state, b.plan_id, p.schema_version
                   FROM decompilation_batches b
                   JOIN decompilation_plans p ON p.plan_id = b.plan_id
                   WHERE b.batch_id = ?""",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise DecompilationBatchError(f"Lote não encontrado: {batch_id}")
            if int(row["schema_version"]) != PROCESSING_SCHEMA_VERSION:
                raise DecompilationBatchError(
                    "O plano usa um schema de processamento antigo; gere um novo plano."
                )
            if row["state"] not in {"failed", "partial"}:
                raise DecompilationBatchError(
                    "Somente lotes com falha ou saída parcial podem ser reenfileirados."
                )
            now = _utc_now()
            connection.execute(
                """UPDATE decompilation_batches
                   SET state = 'pending', last_error = '', updated_at = ?
                   WHERE batch_id = ?""",
                (now, batch_id),
            )
            connection.execute(
                """UPDATE decompilation_plans SET state = 'pending', updated_at = ?
                   WHERE plan_id = ?""",
                (now, row["plan_id"]),
            )
            connection.commit()
        return self.store.status(row["plan_id"])  # type: ignore[return-value]

    def _load_plan(self, plan_id: str) -> sqlite3.Row:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM decompilation_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            raise DecompilationBatchError(f"Plano não encontrado: {plan_id}")
        if int(row["schema_version"]) != PROCESSING_SCHEMA_VERSION:
            raise DecompilationBatchError(
                "O plano usa um schema de processamento antigo; gere um novo plano."
            )
        return row

    def _verify_release(self, plan: sqlite3.Row) -> None:
        manifest = self.catalog.load_manifest(plan["release_id"])
        status = self.catalog.status(plan["release_id"])
        if (
            manifest.get("release_manifest_sha256") != plan["release_hash"]
            or manifest.get("state") != "ready"
            or status.get("freshness") != "fresh"
        ):
            raise DecompilationBatchError(
                "O manifesto ou os JARs mudaram; gere um novo plano antes de continuar."
            )

    def _recover_interrupted(self, plan_id: str) -> None:
        with self.store.connect() as connection:
            connection.execute(
                """UPDATE decompilation_batches
                   SET state = 'pending',
                       last_error = 'Execução anterior interrompida; lote retomado.',
                       updated_at = ?
                   WHERE plan_id = ? AND state = 'running'""",
                (_utc_now(), plan_id),
            )
            connection.commit()

    def _claim_next(self, plan_id: str) -> sqlite3.Row | None:
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM decompilation_batches
                   WHERE plan_id = ? AND state = 'pending' ORDER BY ordinal LIMIT 1""",
                (plan_id,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """UPDATE decompilation_batches
                   SET state = 'running', attempt_count = attempt_count + 1,
                       updated_at = ? WHERE batch_id = ? AND state = 'pending'""",
                (_utc_now(), row["batch_id"]),
            )
            connection.execute(
                """UPDATE decompilation_plans SET state = 'running', updated_at = ?
                   WHERE plan_id = ?""",
                (_utc_now(), plan_id),
            )
            connection.commit()
        with self.store.connect() as connection:
            return connection.execute(
                "SELECT * FROM decompilation_batches WHERE batch_id = ?",
                (row["batch_id"],),
            ).fetchone()

    def _execute_batch(
        self,
        plan: sqlite3.Row,
        batch: sqlite3.Row,
        *,
        max_heap_mb: int,
        timeout_seconds: int,
        max_cpu_cores: int,
        cpu_core_offset: int,
        process_priority: str,
    ) -> dict[str, Any]:
        manifest = self.catalog.load_manifest(plan["release_id"])
        source = _source_path(self.root, manifest)
        jar_path = _safe_child(source / batch["jar_relative_path"], source)
        if sha256_file(jar_path) != batch["artifact_sha256"]:
            return self._finish_failed(
                batch,
                [],
                f"O JAR mudou depois do planejamento: {batch['jar_relative_path']}",
            )

        with self.store.connect() as connection:
            members = connection.execute(
                """SELECT o.*, c.state AS content_state,
                          c.processing_schema_version
                   FROM batch_members m
                   JOIN class_occurrences o ON o.occurrence_id = m.occurrence_id
                   JOIN class_contents c ON c.content_sha256 = m.content_sha256
                   WHERE m.batch_id = ? ORDER BY m.ordinal""",
                (batch["batch_id"],),
            ).fetchall()
            namespace_names = {
                str(row["logical_name"])
                for row in connection.execute(
                    """SELECT DISTINCT logical_name
                       FROM class_occurrences
                       WHERE release_hash = ? AND jar_relative_path = ?
                         AND class_version = ?""",
                    (
                        plan["release_hash"],
                        batch["jar_relative_path"],
                        batch["class_version"],
                    ),
                ).fetchall()
            }
        pending = [
            row
            for row in members
            if row["content_state"] != "completed"
            or int(row["processing_schema_version"]) != PROCESSING_SCHEMA_VERSION
        ]
        if not pending:
            return self._finish_completed(batch, "reused", "", [], expected=0, actual=0)

        # Resolve nested-class families against the whole artifact namespace.
        # A deduplicated outer class may already be completed and therefore not
        # be a member of this plan even though the decompiler folds a pending
        # nested class into that outer source file.
        known_names = namespace_names | {
            str(row["logical_name"]) for row in members
        }
        logical_names = {str(row["logical_name"]) for row in members}
        expected_paths = {
            _class_family(logical_name, known_names).replace(".", "/") + ".java"
            for logical_name in logical_names
        }
        expected_sources = len(expected_paths)

        attempt_dir = (
            self.store.work_dir
            / plan["plan_id"]
            / batch["batch_id"]
            / f"attempt-{int(batch['attempt_count']):04d}"
        )
        input_path = attempt_dir / "input.jar"
        self._build_input(jar_path, input_path, members)
        attempts: list[DecompileResult] = []
        for adapter in self.adapters:
            output_dir = attempt_dir / str(adapter.name)
            result = adapter.decompile(
                DecompileRequest(
                    input_path=input_path,
                    output_dir=output_dir,
                    timeout_seconds=max(1, int(timeout_seconds)),
                    max_heap_mb=max(512, int(max_heap_mb)),
                    max_cpu_cores=max(1, int(max_cpu_cores)),
                    cpu_core_offset=max(0, int(cpu_core_offset)),
                    process_priority=(
                        "low"
                        if str(process_priority).casefold() == "low"
                        else "normal"
                    ),
                )
            )
            attempts.append(result)
            actual_paths = _java_source_paths(output_dir)
            java_files = len(actual_paths)
            missing = _missing_java_sources(
                logical_names,
                known_names,
                actual_paths,
            )
            if result.status == "completed" and not missing:
                reference = _portable_path(self.root, output_dir)
                self._write_attempt_report(
                    attempt_dir,
                    plan,
                    batch,
                    attempts,
                    expected_sources,
                    java_files,
                    "completed",
                )
                return self._finish_completed(
                    batch,
                    result.tool,
                    reference,
                    attempts,
                    pending,
                    expected=expected_sources,
                    actual=java_files,
                )
        errors = []
        for result in attempts:
            actual_paths = _java_source_paths(Path(result.output_dir))
            missing = sorted(
                _missing_java_sources(logical_names, known_names, actual_paths)
            )
            errors.append(
                {
                    "tool": result.tool,
                    "status": result.status,
                    "exit_code": result.exit_code,
                    "error": result.error or result.stderr[-1000:],
                    "missing_source_files": len(missing),
                    "missing_source_samples": missing[:20],
                }
            )
        actual_sources = max(
            (_count_java_files(Path(item.output_dir)) for item in attempts), default=0
        )
        self._write_attempt_report(
            attempt_dir,
            plan,
            batch,
            attempts,
            expected_sources,
            actual_sources,
            "partial" if actual_sources else "failed",
        )
        return self._finish_failed(
            batch,
            attempts,
            json.dumps(errors, ensure_ascii=False),
            expected=expected_sources,
        )

    def _write_attempt_report(
        self,
        attempt_dir: Path,
        plan: sqlite3.Row,
        batch: sqlite3.Row,
        attempts: Sequence[DecompileResult],
        expected_sources: int,
        actual_sources: int,
        state: str,
    ) -> None:
        payload = {
            "schema_version": PROCESSING_SCHEMA_VERSION,
            "recorded_at": _utc_now(),
            "plan_id": plan["plan_id"],
            "batch_id": batch["batch_id"],
            "release_id": plan["release_id"],
            "release_manifest_sha256": plan["release_hash"],
            "jar_relative_path": batch["jar_relative_path"],
            "artifact_sha256": batch["artifact_sha256"],
            "attempt_number": int(batch["attempt_count"]),
            "state": state,
            "expected_source_files": expected_sources,
            "actual_source_files": actual_sources,
            "tools": [asdict(item) for item in attempts],
        }
        _atomic_json(attempt_dir / "attempt.json", payload)

    @staticmethod
    def _build_input(
        jar_path: Path, input_path: Path, members: Sequence[sqlite3.Row]
    ) -> None:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = input_path.with_suffix(".tmp")
        try:
            with (
                zipfile.ZipFile(jar_path) as source,
                zipfile.ZipFile(
                    temporary, "w", compression=zipfile.ZIP_DEFLATED
                ) as target,
                warnings.catch_warnings(),
            ):
                warnings.filterwarnings(
                    "ignore",
                    message=r"Overlapped entries: .*possible zip bomb.*",
                    category=UserWarning,
                )
                target.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
                infos = source.infolist()
                written_entries: set[str] = set()
                for member in members:
                    info = infos[int(member["entry_index"])]
                    if info.filename != member["entry_name"]:
                        raise DecompilationBatchError(
                            "A ordem interna do JAR mudou depois do planejamento."
                        )
                    logical_entry = (
                        str(member["logical_name"]).replace(".", "/") + ".class"
                    )
                    if logical_entry in written_entries:
                        raise DecompilationBatchError(
                            "O lote contém variantes conflitantes da mesma classe lógica."
                        )
                    written_entries.add(logical_entry)
                    target.writestr(logical_entry, source.read(info))
            temporary.replace(input_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _finish_completed(
        self,
        batch: sqlite3.Row,
        tool: str,
        reference: str,
        attempts: Sequence[DecompileResult],
        members: Sequence[sqlite3.Row] = (),
        *,
        expected: int,
        actual: int,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._database_write_lock:
            with self.store.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for member in members:
                    connection.execute(
                        """UPDATE class_contents
                           SET state = 'completed', output_reference = ?,
                               processing_schema_version = ?, updated_at = ?
                           WHERE content_sha256 = ?""",
                        (
                            reference,
                            PROCESSING_SCHEMA_VERSION,
                            now,
                            member["content_sha256"],
                        ),
                    )
                connection.execute(
                    """UPDATE decompilation_batches
                       SET state = 'completed', tool = ?, output_reference = ?,
                           last_error = '', expected_source_files = ?,
                           actual_source_files = ?, updated_at = ? WHERE batch_id = ?""",
                    (tool, reference, expected, actual, now, batch["batch_id"]),
                )
                connection.commit()
        return {
            "batch_id": batch["batch_id"],
            "class_count": int(batch["class_count"]),
            "state": "completed",
            "tool": tool,
            "output_reference": reference,
            "expected_source_files": expected,
            "actual_source_files": actual,
            "attempts": [asdict(item) for item in attempts],
            "telemetry": _decompilation_telemetry(attempts),
        }

    def _finish_failed(
        self,
        batch: sqlite3.Row,
        attempts: Sequence[DecompileResult],
        error: str,
        *,
        expected: int = 0,
    ) -> dict[str, Any]:
        actual = max(
            (_count_java_files(Path(item.output_dir)) for item in attempts), default=0
        )
        partial = actual > 0
        state = "partial" if partial else "failed"
        with self._database_write_lock:
            with self.store.connect() as connection:
                connection.execute(
                    """UPDATE decompilation_batches
                       SET state = ?, tool = ?, last_error = ?,
                           expected_source_files = ?, actual_source_files = ?, updated_at = ?
                       WHERE batch_id = ?""",
                    (
                        state,
                        attempts[-1].tool if attempts else "",
                        error[-8000:],
                        expected,
                        actual,
                        _utc_now(),
                        batch["batch_id"],
                    ),
                )
                connection.commit()
        return {
            "batch_id": batch["batch_id"],
            "class_count": int(batch["class_count"]),
            "state": state,
            "error": error,
            "expected_source_files": expected,
            "actual_source_files": actual,
            "attempts": [asdict(item) for item in attempts],
            "telemetry": _decompilation_telemetry(attempts),
        }

    def _refresh_plan_state(self, plan_id: str) -> None:
        with self.store.connect() as connection:
            states = {
                row[0]
                for row in connection.execute(
                    "SELECT state FROM decompilation_batches WHERE plan_id = ?",
                    (plan_id,),
                )
            }
            if not states or states <= {"completed"}:
                state = "completed"
            elif "running" in states:
                state = "running"
            elif states & {"failed", "partial"} and "pending" not in states:
                state = "attention"
            else:
                state = "pending"
            connection.execute(
                """UPDATE decompilation_plans SET state = ?, updated_at = ?
                   WHERE plan_id = ?""",
                (state, _utc_now(), plan_id),
            )
            connection.commit()


def _class_family(
    logical_name: str,
    known_names: Iterable[str] = (),
) -> str:
    package, separator, simple = str(logical_name).rpartition(".")
    known = _known_name_set(known_names)
    if simple.startswith("$"):
        candidates = [
            simple[:index]
            for index, character in enumerate(simple)
            if character == "$" and index > 0
        ]
        outer = next(
            (
                candidate
                for candidate in reversed(candidates)
                if (f"{package}.{candidate}" if separator else candidate) in known
            ),
            simple,
        )
    else:
        candidates = [
            simple[:index]
            for index, character in enumerate(simple)
            if character == "$" and index > 0
        ]
        outer = next(
            (
                candidate
                for candidate in candidates
                if (f"{package}.{candidate}" if separator else candidate) in known
            ),
            simple,
        )
    return f"{package}.{outer}" if separator else outer


def _java_source_candidates(
    logical_name: str,
    known_names: Iterable[str] = (),
) -> set[str]:
    package, separator, simple = str(logical_name).rpartition(".")
    known = _known_name_set(known_names)
    candidates: list[str] = []
    for index, character in enumerate(simple):
        if character != "$" or index <= 0:
            continue
        candidate = simple[:index]
        qualified = f"{package}.{candidate}" if separator else candidate
        if qualified in known:
            candidates.append(qualified)
    candidates.append(str(logical_name))
    return {
        candidate.replace(".", "/") + suffix
        for candidate in candidates
        for suffix in DECOMPILED_SOURCE_SUFFIXES
    }


def _missing_java_sources(
    logical_names: Iterable[str],
    known_names: Iterable[str],
    actual_paths: set[str],
) -> set[str]:
    known = {str(item) for item in known_names}
    actual_keys = {_java_source_path_key(item) for item in actual_paths}
    missing: set[str] = set()
    for logical_name in {str(item) for item in logical_names}:
        candidate_paths = _java_source_candidates(logical_name, known)
        if any(_java_source_path_key(item) in actual_keys for item in candidate_paths):
            continue
        missing.add(_class_family(logical_name, known).replace(".", "/") + ".java")
    return missing


def _known_name_set(known_names: Iterable[str]) -> set[str] | frozenset[str]:
    """Reuse large namespace sets instead of copying them once per class."""

    if isinstance(known_names, (set, frozenset)):
        return known_names
    return {str(item) for item in known_names}


def _java_source_path_key(
    value: str,
    *,
    case_sensitive: bool | None = None,
) -> str:
    """Match paths using the semantics of the filesystem that stores outputs."""

    normalized = str(value).replace("\\", "/")
    if case_sensitive is None:
        case_sensitive = os.name != "nt"
    return normalized if case_sensitive else normalized.casefold()


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _source_path(root: Path, manifest: dict[str, Any]) -> Path:
    value = Path(str(manifest.get("source_dir") or ""))
    return (value if value.is_absolute() else root / value).resolve()


def _safe_child(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(parent.resolve())
    except ValueError as exc:
        raise DecompilationBatchError("Caminho de JAR fora da release.") from exc
    return resolved


def _portable_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _count_java_files(path: Path) -> int:
    return len(_java_source_paths(path))


def _java_source_paths(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file() and item.suffix.casefold() in DECOMPILED_SOURCE_SUFFIXES
    }


def _decompilation_telemetry(
    attempts: Sequence[DecompileResult],
) -> dict[str, int | bool]:
    return {
        "duration_ms": sum(max(0, int(item.duration_ms)) for item in attempts),
        "peak_rss_bytes": max(
            (max(0, int(item.peak_rss_bytes)) for item in attempts), default=0
        ),
        "cpu_user_ms": sum(max(0, int(item.cpu_user_ms)) for item in attempts),
        "cpu_kernel_ms": sum(
            max(0, int(item.cpu_kernel_ms)) for item in attempts
        ),
        "input_bytes": max(
            (max(0, int(item.input_bytes)) for item in attempts), default=0
        ),
        "output_bytes": sum(max(0, int(item.output_bytes)) for item in attempts),
        "timed_out": any(bool(item.timed_out) for item in attempts),
        "metrics_available": any(bool(item.metrics_available) for item in attempts),
        "cpu_limit_applied": any(bool(item.cpu_limit_applied) for item in attempts),
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DecompilationBatchError(
                "Já existe um decompilador em execução neste índice."
            ) from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
