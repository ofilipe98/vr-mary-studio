from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..models import RuntimeEvent, utc_now
from ..paths import to_portable_path
from ..chat_tools import validate_tool_definition
from .common import _last_insert_id


class ConversationsRepositoryMixin:
    """Conversations operations sharing MaryDatabase's state and transactions."""

    def create_conversation(
        self,
        title: str,
        provider: str,
        model: str,
        workspace: Path,
        cloned_from: str = "",
        effort: str = "medium",
        service_tier: str = "",
        approval_profile: str = "auto",
        collaboration_mode: str = "default",
        vr_enabled: bool = False,
        vr_mode: str = "",
    ) -> str:
        conversation_id = uuid.uuid4().hex
        now = utc_now()
        resolved_mode = str(vr_mode or "").strip().casefold()
        if resolved_mode not in {"off", "vr", "ultra"}:
            resolved_mode = "vr" if vr_enabled else "off"
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO conversations
                   (id,title,provider,model,effort,service_tier,approval_profile,
                    collaboration_mode,vr_enabled,vr_mode,workspace,
                    cloned_from,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    conversation_id,
                    title,
                    provider,
                    model,
                    effort,
                    service_tier,
                    approval_profile,
                    collaboration_mode,
                    int(vr_enabled),
                    resolved_mode,
                    to_portable_path(self.root, workspace) if self.root else str(workspace),
                    cloned_from,
                    now,
                    now,
                ),
            )
        return conversation_id

    def list_conversations(
        self, include_archived: bool = False, state: str = "active"
    ) -> list[sqlite3.Row]:
        with self.connect() as connection:
            if state == "trash":
                where = "trashed_at<>''"
                params: tuple[Any, ...] = ()
            elif include_archived:
                where = "trashed_at=''"
                params = ()
            elif state == "archived":
                where = "archived=1 AND trashed_at=''"
                params = ()
            elif state == "all":
                where = "trashed_at=''"
                params = ()
            else:
                where = "archived=0 AND trashed_at=''"
                params = ()
            return connection.execute(
                f"SELECT * FROM conversations WHERE {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()

    def get_conversation(self, conversation_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()

    def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        allowed = {
            "title", "provider", "model", "effort", "native_id", "native_id_vr",
            "status", "archived",
            "service_tier", "approval_profile", "collaboration_mode", "trashed_at",
            "workspace", "original_workspace", "vr_enabled", "vr_mode",
            "context_used_tokens", "context_window_tokens", "total_processed_tokens",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if self.root:
            for key in ("workspace", "original_workspace"):
                if key in values:
                    values[key] = to_portable_path(self.root, values[key])
        if not values:
            return
        values["updated_at"] = utc_now()
        columns = ", ".join(f"{key}=?" for key in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE conversations SET {columns} WHERE id=?",
                [*values.values(), conversation_id],
            )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        turn_id: str = "",
        edited_from_message_id: int | None = None,
        response_mode: str = "",
        provider_message_id: str = "",
        execution_ordinal: int = 0,
        message_status: str = "",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO messages
                   (conversation_id,role,content,provider_message_id,turn_id,
                    edited_from_message_id,response_mode,execution_ordinal,message_status,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    conversation_id,
                    role,
                    content,
                    provider_message_id,
                    turn_id,
                    edited_from_message_id,
                    response_mode,
                    execution_ordinal,
                    message_status,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (utc_now(), conversation_id),
            )
            return _last_insert_id(cursor)

    def upsert_assistant_message(
        self,
        conversation_id: str,
        content: str,
        *,
        turn_id: str = "",
        response_mode: str = "",
        provider_message_id: str = "",
        execution_ordinal: int = 0,
        message_status: str = "completed",
        execution_id: int = 0,
        message_phase: str = "",
        start_event_id: int = 0,
        research_run_id: str = "",
        research_citations: list[dict[str, Any]] | None = None,
    ) -> int:
        """Insert or update an assistant message identified by ordinal."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            def publish_research(message_id: int) -> int:
                if not research_run_id:
                    return message_id
                updated = connection.execute(
                    "UPDATE research_runs SET publication_message_id=? WHERE run_id=? AND conversation_id=? AND execution_id=?",
                    (message_id, research_run_id, conversation_id, execution_id),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("Publicação sem propriedade da investigação.")
                connection.execute("DELETE FROM source_citations WHERE message_id=?", (message_id,))
                connection.executemany(
                    "INSERT INTO source_citations(conversation_id,document_id,message_id,excerpt) VALUES(?,?,?,?)",
                    [(conversation_id, int(c["document_id"]), message_id, str(c.get("excerpt") or "")[:4000])
                     for c in research_citations or [] if int(c.get("document_id") or 0) > 0],
                )
                return message_id

            if research_run_id:
                published = connection.execute("SELECT publication_message_id FROM research_runs WHERE run_id=? AND conversation_id=? AND execution_id=?",
                    (research_run_id, conversation_id, execution_id)).fetchone()
                if published and published[0]:
                    return int(published[0])
            if execution_ordinal > 0:
                existing = connection.execute(
                    """SELECT id FROM messages
                       WHERE conversation_id=? AND role='assistant'
                         AND execution_ordinal=? AND execution_id=?""",
                    (conversation_id, execution_ordinal, execution_id),
                ).fetchone()
                if existing:
                    connection.execute(
                        """UPDATE messages SET content=?,message_status=?,
                           turn_id=CASE WHEN ?<>'' THEN ? ELSE turn_id END,
                           message_phase=?,response_mode=?
                           WHERE id=?""",
                        (content, message_status, turn_id, turn_id, message_phase,
                         response_mode, existing["id"]),
                    )
                    return publish_research(int(existing["id"]))
            cursor = connection.execute(
                """INSERT INTO messages
                   (conversation_id,role,content,provider_message_id,turn_id,
                    edited_from_message_id,response_mode,execution_ordinal,message_status,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    conversation_id,
                    "assistant",
                    content,
                    provider_message_id,
                    turn_id,
                    None,
                    response_mode,
                    execution_ordinal,
                    message_status,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (utc_now(), conversation_id),
            )
            message_id = _last_insert_id(cursor)
            connection.execute(
                "UPDATE messages SET execution_id=?,message_phase=?,start_event_id=? WHERE id=?",
                (execution_id, message_phase, start_event_id, message_id),
            )
            return publish_research(message_id)

    def add_source_citations(
        self,
        conversation_id: str,
        message_id: int,
        citations: list[dict[str, Any]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM source_citations WHERE message_id=?", (message_id,)
            )
            connection.executemany(
                """INSERT INTO source_citations
                   (conversation_id,document_id,message_id,excerpt)
                   VALUES(?,?,?,?)""",
                [
                    (
                        conversation_id,
                        int(item.get("document_id") or 0) or None,
                        message_id,
                        str(item.get("excerpt") or "")[:4000],
                    )
                    for item in citations
                    if int(item.get("document_id") or 0) > 0
                ],
            )

    def add_message_skills(
        self,
        conversation_id: str,
        message_id: int,
        skills: list[dict[str, Any]],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if not skills:
            return
        now = utc_now()
        sql = """INSERT INTO message_skills
               (conversation_id, message_id, skill_id, name_snapshot, provider_instance_id, scope, path_reference, created_at)
               VALUES(?,?,?,?,?,?,?,?)"""
        params = [
            (
                conversation_id,
                message_id,
                str(s.get("id") or s.get("skillId") or ""),
                str(s.get("name") or s.get("skill_name") or s.get("nameSnapshot") or ""),
                str(s.get("provider") or s.get("providerInstanceId") or ""),
                str(s.get("scope") or "project"),
                str(s.get("path") or s.get("pathReference") or ""),
                now,
            )
            for s in skills
            if s.get("id") or s.get("name") or s.get("skillId") or s.get("nameSnapshot")
        ]
        if connection is not None:
            connection.executemany(sql, params)
        else:
            with self.connect() as conn:
                conn.executemany(sql, params)

    def get_message_skills(self, message_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT skill_id, name_snapshot, provider_instance_id, scope, path_reference, created_at
                   FROM message_skills WHERE message_id=? ORDER BY id""",
                (message_id,),
            ).fetchall()
            return [
                {
                    "skillId": row["skill_id"],
                    "skill_id": row["skill_id"],
                    "id": row["skill_id"],
                    "nameSnapshot": row["name_snapshot"],
                    "skill_name": row["name_snapshot"],
                    "name": row["name_snapshot"],
                    "providerInstanceId": row["provider_instance_id"],
                    "provider": row["provider_instance_id"],
                    "scope": row["scope"],
                    "pathReference": row["path_reference"],
                    "path": row["path_reference"],
                    "createdAt": row["created_at"],
                }
                for row in rows
            ]

    def get_conversation_message_skills(self, conversation_id: str) -> dict[int, list[dict[str, Any]]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT message_id, skill_id, name_snapshot, provider_instance_id, scope, path_reference, created_at
                   FROM message_skills WHERE conversation_id=? ORDER BY id""",
                (conversation_id,),
            ).fetchall()
            result: dict[int, list[dict[str, Any]]] = {}
            for row in rows:
                mid = int(row["message_id"])
                if mid not in result:
                    result[mid] = []
                result[mid].append({
                    "skillId": row["skill_id"],
                    "skill_id": row["skill_id"],
                    "id": row["skill_id"],
                    "nameSnapshot": row["name_snapshot"],
                    "skill_name": row["name_snapshot"],
                    "name": row["name_snapshot"],
                    "providerInstanceId": row["provider_instance_id"],
                    "provider": row["provider_instance_id"],
                    "scope": row["scope"],
                    "pathReference": row["path_reference"],
                    "path": row["path_reference"],
                    "createdAt": row["created_at"],
                })
            return result

    def begin_user_turn(self, conversation_id: str, content: str, skills: list[dict[str, Any]] | None = None) -> int:
        """Atomically claim an idle active conversation and persist its user turn."""

        now = utc_now()
        with self.connect() as connection:
            claimed = connection.execute(
                """UPDATE conversations SET status='running',updated_at=?
                   WHERE id=? AND status<>'running' AND archived=0 AND trashed_at=''""",
                (now, conversation_id),
            )
            if claimed.rowcount != 1:
                row = connection.execute(
                    "SELECT status,archived,trashed_at FROM conversations WHERE id=?",
                    (conversation_id,),
                ).fetchone()
                if not row:
                    raise KeyError(conversation_id)
                if str(row["status"] or "idle") == "running":
                    raise RuntimeError(
                        "JÃ¡ existe uma resposta em andamento nesta conversa."
                    )
                raise RuntimeError("A conversa nÃ£o estÃ¡ ativa para receber mensagens.")
            cursor = connection.execute(
                """INSERT INTO messages
                   (conversation_id,role,content,turn_id,edited_from_message_id,created_at)
                   VALUES(?,'user',?,'',NULL,?)""",
                (conversation_id, content, now),
            )
            message_id = _last_insert_id(cursor)
            connection.execute("UPDATE conversations SET active_execution_id=? WHERE id=?", (message_id, conversation_id))
            if skills:
                self.add_message_skills(conversation_id, message_id, skills, connection=connection)
            return message_id

    def finish_user_turn(self, conversation_id: str, execution_id: int, status: str) -> bool:
        """A late finalizer must not release a newly admitted execution."""
        with self.connect() as connection:
            changed = connection.execute(
                "UPDATE conversations SET status=?,updated_at=? WHERE id=? AND active_execution_id IN (0,?)",
                (status, utc_now(), conversation_id, execution_id),
            )
            return changed.rowcount == 1

    def abort_user_turn(self, conversation_id: str, message_id: int) -> None:
        """Undo a turn that failed before an asynchronous provider run started."""

        with self.connect() as connection:
            connection.execute(
                """DELETE FROM messages
                   WHERE id=? AND conversation_id=? AND role='user' AND turn_id=''""",
                (message_id, conversation_id),
            )
            connection.execute(
                """UPDATE conversations SET status='idle',updated_at=?
                   WHERE id=? AND status='running'""",
                (utc_now(), conversation_id),
            )

    def recover_interrupted_conversations(self) -> list[str]:
        """Mark turns that have no runtime owner after application startup."""

        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            live_conversations = set()
            columns = {row[1] for row in connection.execute("PRAGMA table_info(research_runs)")}
            if {"owner_pid", "owner_birth"}.issubset(columns):
                from ..execution.ownership import process_identity
                for run in connection.execute(
                    "SELECT conversation_id,owner_pid,owner_birth FROM research_runs WHERE status='running'"
                ):
                    identity = process_identity(run["owner_pid"]) if run["owner_pid"] else ""
                    if identity and (identity == "unknown" or identity == run["owner_birth"]):
                        live_conversations.add(run["conversation_id"])
            conversation_ids = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM conversations WHERE status='running'"
                ).fetchall()
                if row["id"] not in live_conversations
            ]
            if conversation_ids:
                placeholders = ",".join("?" for _ in conversation_ids)
                connection.execute(
                    f"""UPDATE conversations SET status='interrupted',updated_at=?
                        WHERE id IN ({placeholders})""",
                    (now, *conversation_ids),
                )
                connection.executemany(
                    """INSERT INTO runtime_events
                       (conversation_id,kind,text,payload_json,created_at)
                       VALUES(?,'turn_recovered',?,'{}',?)""",
                    [
                        (
                            conversation_id,
                            "ExecuÃ§Ã£o anterior interrompida pelo encerramento da aplicaÃ§Ã£o.",
                            now,
                        )
                        for conversation_id in conversation_ids
                    ],
                )
            return conversation_ids

    def messages(self, conversation_id: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY id",
                (conversation_id,),
            ).fetchall()

    def update_message_turn(self, message_id: int, turn_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE messages SET turn_id=? WHERE id=?", (turn_id, message_id)
            )

    def messages_through(self, conversation_id: str, message_id: int) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """SELECT * FROM messages
                   WHERE conversation_id=? AND id<=? ORDER BY id""",
                (conversation_id, message_id),
            ).fetchall()

    def save_approval(self, approval_id: str, conversation_id: str, request: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO approvals
                   (id,conversation_id,request_json,decision,created_at,decided_at)
                   VALUES(?,?,?,'',?,'')""",
                (approval_id, conversation_id, json.dumps(request, ensure_ascii=False), utc_now()),
            )

    def decide_approval(self, approval_id: str, decision: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE approvals SET decision=?,decided_at=? WHERE id=?",
                (decision, utc_now(), approval_id),
            )

    def create_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        executable: str,
        arguments: list[str] | None = None,
        timeout_seconds: int = 60,
        safety: str = "side_effecting",
        tool_id: str = "",
    ) -> str:
        validate_tool_definition(
            name, description, input_schema, executable, arguments or []
        )
        identifier = tool_id or uuid.uuid4().hex
        now = utc_now()
        timeout = min(300, max(1, int(timeout_seconds)))
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO tool_definitions
                   (id,name,description,input_schema_json,executable,arguments_json,
                    timeout_seconds,safety,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, name, description,
                    json.dumps(input_schema, ensure_ascii=False), executable,
                    json.dumps(arguments or [], ensure_ascii=False), timeout,
                    safety if safety in {"read_only", "side_effecting"} else "side_effecting",
                    now, now,
                ),
            )
        return identifier

    def update_tool(self, tool_id: str, **fields: Any) -> None:
        current = next(
            (tool for tool in self.list_tools() if str(tool["id"]) == str(tool_id)),
            None,
        )
        if not current:
            raise KeyError(tool_id)
        candidate = {**current, **fields}
        validate_tool_definition(
            str(candidate["name"]),
            str(candidate["description"]),
            candidate["input_schema"],
            str(candidate["executable"]),
            list(candidate["arguments"]),
        )
        mapping = {
            "name": "name", "description": "description", "executable": "executable",
            "timeout_seconds": "timeout_seconds", "safety": "safety", "enabled": "enabled",
            "input_schema": "input_schema_json", "arguments": "arguments_json",
        }
        values: dict[str, Any] = {}
        for key, column in mapping.items():
            if key not in fields:
                continue
            value = fields[key]
            if key in {"input_schema", "arguments"}:
                value = json.dumps(value, ensure_ascii=False)
            elif key == "timeout_seconds":
                value = min(300, max(1, int(value)))
            elif key == "safety" and value not in {"read_only", "side_effecting"}:
                value = "side_effecting"
            values[column] = value
        if not values:
            return
        values["updated_at"] = utc_now()
        columns = ",".join(f"{column}=?" for column in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE tool_definitions SET {columns} WHERE id=?",
                [*values.values(), tool_id],
            )

    def delete_tool(self, tool_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM conversation_tools WHERE tool_kind='dynamic' AND tool_id=?",
                (tool_id,),
            )
            connection.execute("DELETE FROM tool_definitions WHERE id=?", (tool_id,))

    def list_tools(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tool_definitions"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY name COLLATE NOCASE"
        with self.connect() as connection:
            rows = connection.execute(sql).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["input_schema"] = json.loads(item.pop("input_schema_json") or "{}")
            item["arguments"] = json.loads(item.pop("arguments_json") or "[]")
            result.append(item)
        return result

    def set_conversation_tools(
        self,
        conversation_id: str,
        dynamic_ids: list[str],
        mcp_tools: list[dict[str, str]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM conversation_tools WHERE conversation_id=?", (conversation_id,)
            )
            connection.executemany(
                """INSERT INTO conversation_tools
                   (conversation_id,tool_kind,tool_id) VALUES(?,'dynamic',?)""",
                [(conversation_id, tool_id) for tool_id in dict.fromkeys(dynamic_ids)],
            )
            connection.executemany(
                """INSERT INTO conversation_tools
                   (conversation_id,tool_kind,server_name,tool_name)
                   VALUES(?,'mcp',?,?)""",
                [
                    (conversation_id, item.get("server", ""), item.get("tool", ""))
                    for item in mcp_tools
                    if item.get("server") and item.get("tool")
                ],
            )

    def conversation_tools(self, conversation_id: str) -> dict[str, list[Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_tools WHERE conversation_id=?",
                (conversation_id,),
            ).fetchall()
        return {
            "dynamic": [str(row["tool_id"]) for row in rows if row["tool_kind"] == "dynamic"],
            "mcp": [
                {"server": str(row["server_name"]), "tool": str(row["tool_name"])}
                for row in rows if row["tool_kind"] == "mcp"
            ],
        }

    def latest_event(self, conversation_id: str, kind: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                """SELECT * FROM runtime_events
                   WHERE conversation_id=? AND kind=? ORDER BY id DESC LIMIT 1""",
                (conversation_id, kind),
            ).fetchone()

    def orchestration_events_after(
        self, conversation_id: str, event_id: int
    ) -> list[sqlite3.Row]:
        kinds = (
            "intent_analysis_started",
            "intent_analysis_completed",
            "response_contract_created",
            "agent_started",
            "agent_completed",
            "agent_failed",
            "agent_usage",
            "parallel_group_started",
            "parallel_group_completed",
            "evidence_merge_completed",
            "evidence_validation_completed",
            "critic_completed",
            "validation_started",
            "validation_completed",
            "refinement_requested",
            "refinement_started",
            "refinement_completed",
            "revision_started",
            "synthesis_started",
            "synthesis_completed",
            "final_validation_started",
            "final_validation_completed",
            "response_rewrite_started",
            "response_rewrite_completed",
            "orchestration_completed",
            "orchestration_cancelled",
        )
        placeholders = ",".join("?" for _kind in kinds)
        with self.connect() as connection:
            return connection.execute(
                f"""SELECT * FROM runtime_events
                    WHERE conversation_id=? AND id>? AND kind IN ({placeholders})
                    ORDER BY id""",
                (conversation_id, int(event_id), *kinds),
            ).fetchall()

    def latest_turn_events(self, conversation_id: str) -> list[sqlite3.Row]:
        """Return the persisted events that belong to the latest chat turn.

        Response planning can be emitted before the provider's ``turn_started``
        event, so the previous terminal event is the reliable boundary.
        """

        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM runtime_events
                   WHERE conversation_id=? ORDER BY id DESC LIMIT 1000""",
                (conversation_id,),
            ).fetchall()
        ordered = list(reversed(rows))
        if not ordered:
            return []
        terminal_indexes = [
            index
            for index, row in enumerate(ordered)
            if str(row["kind"] or "")
            in {"turn_completed", "orchestration_cancelled", "turn_recovered"}
        ]
        if not terminal_indexes:
            return ordered
        latest_terminal = terminal_indexes[-1]
        has_events_after_latest = latest_terminal < len(ordered) - 1
        boundary_index = (
            latest_terminal
            if has_events_after_latest
            else (terminal_indexes[-2] if len(terminal_indexes) > 1 else -1)
        )
        return ordered[boundary_index + 1 :]

    def purge_conversation(self, conversation_id: str) -> None:
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_runs'").fetchone():
                connection.execute("DELETE FROM research_step_attempts WHERE step_id IN (SELECT s.step_id FROM research_steps s JOIN research_runs r ON r.run_id=s.run_id WHERE r.conversation_id=?)", (conversation_id,))
                connection.execute("DELETE FROM research_steps WHERE run_id IN (SELECT run_id FROM research_runs WHERE conversation_id=?)", (conversation_id,))
                connection.execute("DELETE FROM research_runs WHERE conversation_id=?", (conversation_id,))
            for table in (
                "source_citations", "artifacts", "approvals", "runtime_events",
                "conversation_tools", "messages",
            ):
                connection.execute(f"DELETE FROM {table} WHERE conversation_id=?", (conversation_id,))
            connection.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    def add_event(self, event: RuntimeEvent) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO runtime_events
                   (conversation_id,kind,text,payload_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    event.conversation_id,
                    event.kind,
                    event.text,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at,
                ),
            )
            return _last_insert_id(cursor)
