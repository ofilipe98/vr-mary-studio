"""
Research run and step persistence repository for VR Mary Studio.

Manages relational storage for research plans, stage execution steps,
retry attempts, and safe resumption of completed stages using SHA-256
hash matching across inputs, model configs, and contract versions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .ownership import process_identity

LOGGER = logging.getLogger(__name__)

CONTRACT_VERSION = "2.0.0"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def compute_step_input_hash(
    module: str,
    prompt: str,
    model_mapping: dict[str, Any],
    contract_version: str = CONTRACT_VERSION,
) -> str:
    payload = {
        "module": module,
        "prompt": prompt,
        "model": model_mapping,
        "contract_version": contract_version,
    }
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return compute_sha256(normalized)


class ResearchRepository:
    """SQLite repository for research runs, steps, and attempts."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._claims: dict[str, str] = {}
        self.ensure_schema()
        self.recover_interrupted()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        """Create tables and indices if not already present."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS research_runs (
                    run_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    contract_version TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    budget_json TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_research_runs_conv
                ON research_runs(conversation_id);

                CREATE INDEX IF NOT EXISTS idx_research_runs_hash
                ON research_runs(input_hash);

                CREATE TABLE IF NOT EXISTS research_steps (
                    step_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    stage_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    module TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    output_hash TEXT,
                    output_json TEXT,
                    error TEXT,
                    attempts_count INTEGER DEFAULT 0,
                    duration_seconds REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_research_steps_run
                ON research_steps(run_id);

                CREATE INDEX IF NOT EXISTS idx_research_steps_hash
                ON research_steps(input_hash);

                CREATE TABLE IF NOT EXISTS research_step_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    output_json TEXT,
                    error TEXT,
                    duration_seconds REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_step_attempts_step
                ON research_step_attempts(step_id);
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(research_runs)")}
            for name, definition in {
                "owner_token": "TEXT NOT NULL DEFAULT ''",
                "owner_pid": "INTEGER NOT NULL DEFAULT 0",
                "owner_birth": "TEXT NOT NULL DEFAULT ''",
                "execution_id": "INTEGER NOT NULL DEFAULT 0",
                "context_json": "TEXT NOT NULL DEFAULT '{}'",
                "publication_message_id": "INTEGER",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE research_runs ADD COLUMN {name} {definition}")

    def recover_interrupted(self) -> list[str]:
        """Only orphaned owners are recovered; startup never starts provider calls."""
        recovered = []
        with self._connect() as conn:
            for row in conn.execute("SELECT * FROM research_runs WHERE status='running'").fetchall():
                identity = process_identity(row["owner_pid"]) if row["owner_pid"] else ""
                if identity == "unknown" or (identity and identity == row["owner_birth"]):
                    continue
                changed = conn.execute(
                    "UPDATE research_runs SET status='interrupted',owner_token='',updated_at=? "
                    "WHERE run_id=? AND status='running' AND owner_token=?",
                    (utc_now_iso(), row["run_id"], row["owner_token"]),
                )
                if changed.rowcount:
                    recovered.append(row["run_id"])
                    conn.execute("UPDATE research_steps SET status='interrupted',error=? WHERE run_id=? AND status='running'",
                                 ("Processo encerrado; a conclusão remota é desconhecida. Retomada explícita necessária.", row["run_id"]))
        return recovered

    def latest_resumable(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_runs WHERE conversation_id=? AND "
                "(status IN ('partial','interrupted','cancelled','failed','rejected') "
                "OR (status='completed' AND publication_message_id IS NULL)) ORDER BY created_at DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
            return dict(row) if row else None

    def claim_resume(self, run_id: str, conversation_id: str, *, execution_id: int = 0) -> dict[str, Any]:
        """A single atomic claim prevents two executors from resuming the same run."""
        token = uuid.uuid4().hex
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE research_runs SET status='running',publication_message_id=NULL,owner_token=?,owner_pid=?,owner_birth=?,execution_id=?,updated_at=? "
                "WHERE run_id=? AND conversation_id=? AND contract_version=? AND "
                "(status IN ('partial','interrupted','cancelled','failed','rejected') OR (status='completed' AND publication_message_id IS NULL))",
                (token, os.getpid(), process_identity(), execution_id, utc_now_iso(), run_id, conversation_id, CONTRACT_VERSION),
            )
            if changed.rowcount != 1:
                raise ValueError("A investigação já está em execução, concluída ou é incompatível.")
            self._claims[run_id] = token
            return dict(conn.execute("SELECT * FROM research_runs WHERE run_id=?", (run_id,)).fetchone())

    def set_context(self, run_id: str, context: dict[str, Any], execution_id: int = 0) -> None:
        with self._connect() as conn:
            changed = conn.execute("UPDATE research_runs SET context_json=?,execution_id=? WHERE run_id=? AND owner_token=?",
                (json.dumps(context, ensure_ascii=False), execution_id, run_id, self._claims.get(run_id, "")))
            if changed.rowcount != 1:
                raise RuntimeError("A execução perdeu a propriedade da investigação.")

    def create_run(
        self,
        run_id: str,
        conversation_id: str,
        plan_dict: dict[str, Any],
        request_text: str,
        budget_dict: dict[str, Any],
        contract_version: str = CONTRACT_VERSION,
    ) -> None:
        now = utc_now_iso()
        token = uuid.uuid4().hex
        input_hash = compute_sha256(
            json.dumps(
                {"request": request_text, "plan": plan_dict, "contract": contract_version},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_runs (
                    run_id, conversation_id, status, contract_version,
                    request_text, input_hash, plan_json, budget_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    conversation_id,
                    "running",
                    contract_version,
                    request_text,
                    input_hash,
                    json.dumps(plan_dict, ensure_ascii=False),
                    json.dumps(budget_dict, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE research_runs SET owner_token=?,owner_pid=?,owner_birth=? WHERE run_id=?",
                         (token, os.getpid(), process_identity(), run_id))
        self._claims[run_id] = token

    def update_run_status(
        self,
        run_id: str,
        status: str,
        *,
        budget_snapshot: dict[str, Any] | None = None,
        result_dict: dict[str, Any] | None = None,
        owner_token: str | None = None,
    ) -> None:
        now = utc_now_iso()
        query = "UPDATE research_runs SET status = ?, updated_at = ?"
        params: list[Any] = [status, now]

        if budget_snapshot is not None:
            query += ", budget_json = ?"
            params.append(json.dumps(budget_snapshot, ensure_ascii=False))

        if result_dict is not None:
            query += ", result_json = ?"
            params.append(json.dumps(result_dict, ensure_ascii=False))

        query += " WHERE run_id = ? AND owner_token = ?"
        params.extend((run_id, owner_token if owner_token is not None else self._claims.get(run_id, "")))

        with self._connect() as conn:
            if conn.execute(query, tuple(params)).rowcount != 1:
                raise RuntimeError("A execução perdeu a propriedade da investigação.")

    def claim_token(self, run_id: str) -> str:
        return self._claims[run_id]

    def checkpoint_budget(self, run_id: str, owner_token: str, budget: dict) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE research_runs SET budget_json=?,updated_at=? WHERE run_id=? AND owner_token=? AND status='running'",
                (json.dumps(budget), utc_now_iso(), run_id, owner_token))

    def save_step_result(
        self,
        run_id: str,
        stage_id: str,
        worker_id: str,
        role: str,
        module: str,
        input_hash: str,
        status: str,
        *,
        output: dict[str, Any] | None = None,
        error: str = "",
        attempts: int = 1,
        duration_seconds: float = 0.0,
        record_attempt: bool = False,
        owner_token: str | None = None,
    ) -> str:
        step_id = f"{run_id}:{stage_id}"
        now = utc_now_iso()
        output_json = json.dumps(output, ensure_ascii=False) if output is not None else None
        output_hash = compute_sha256(output_json) if output_json else None

        with self._connect() as conn:
            owner = conn.execute("SELECT owner_token FROM research_runs WHERE run_id=?", (run_id,)).fetchone()
            if not owner or owner[0] != (owner_token if owner_token is not None else self._claims.get(run_id)):
                raise RuntimeError("Checkpoint sem propriedade da investigação.")
            conn.execute(
                """
                INSERT INTO research_steps (
                    step_id, run_id, stage_id, worker_id, role, module,
                    status, input_hash, output_hash, output_json, error,
                    attempts_count, duration_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(step_id) DO UPDATE SET
                    status = excluded.status,
                    input_hash = excluded.input_hash,
                    worker_id = excluded.worker_id,
                    role = excluded.role,
                    module = excluded.module,
                    output_hash = excluded.output_hash,
                    output_json = excluded.output_json,
                    error = excluded.error,
                    attempts_count = excluded.attempts_count,
                    duration_seconds = excluded.duration_seconds,
                    updated_at = excluded.updated_at
                """,
                (
                    step_id,
                    run_id,
                    stage_id,
                    worker_id,
                    role,
                    module,
                    status,
                    input_hash,
                    output_hash,
                    output_json,
                    error,
                    attempts,
                    duration_seconds,
                    now,
                    now,
                ),
            )
            if record_attempt:
                # Result, completion and attempt have one commit boundary.
                next_attempt = conn.execute("SELECT COALESCE(MAX(attempt_number),0)+1 FROM research_step_attempts WHERE step_id=?", (step_id,)).fetchone()[0]
                conn.execute("INSERT INTO research_step_attempts(step_id,attempt_number,status,output_json,error,duration_seconds,created_at) VALUES(?,?,?,?,?,?,?)",
                             (step_id, next_attempt, status, output_json, error, duration_seconds, now))
        return step_id

    def record_step_attempt(
        self,
        step_id: str,
        attempt_number: int,
        status: str,
        *,
        output: dict[str, Any] | None = None,
        error: str = "",
        duration_seconds: float = 0.0,
    ) -> None:
        now = utc_now_iso()
        output_json = json.dumps(output, ensure_ascii=False) if output is not None else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_step_attempts (
                    step_id, attempt_number, status, output_json, error, duration_seconds, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    attempt_number,
                    status,
                    output_json,
                    error,
                    duration_seconds,
                    now,
                ),
            )

    def find_reusable_step(
        self,
        input_hash: str,
        *,
        run_id: str = "",
        conversation_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Read a checkpoint only from the explicitly resumed run, verifying content."""
        if not run_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT s.step_id, s.stage_id, s.worker_id, s.module, s.output_json,
                       s.duration_seconds, r.contract_version, s.output_hash, r.conversation_id
                FROM research_steps s
                JOIN research_runs r ON s.run_id = r.run_id
                WHERE s.input_hash = ?
                  AND s.run_id = ? AND r.contract_version = ?
                  AND s.status IN ('completed', 'reused')
                  AND s.output_json IS NOT NULL
                ORDER BY s.updated_at DESC
                LIMIT 1
                """,
                (input_hash, run_id, CONTRACT_VERSION),
            ).fetchone()
            if row and row["output_json"]:
                if conversation_id is not None and row["conversation_id"] != conversation_id:
                    return None
                if compute_sha256(row["output_json"]) != row["output_hash"]:
                    return None
                try:
                    return {
                        "step_id": row["step_id"],
                        "stage_id": row["stage_id"],
                        "worker_id": row["worker_id"],
                        "module": row["module"],
                        "output": json.loads(row["output_json"]),
                        "duration_seconds": row["duration_seconds"],
                        "contract_version": row["contract_version"],
                    }
                except Exception:
                    return None
        return None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def get_steps_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_steps WHERE run_id = ? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_attempts_for_step(self, step_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_step_attempts WHERE step_id = ? ORDER BY attempt_number ASC",
                (step_id,),
            ).fetchall()
            return [dict(r) for r in rows]
