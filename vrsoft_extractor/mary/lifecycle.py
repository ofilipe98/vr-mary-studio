"""Durable reconciliation of conversation trash across filesystem and SQLite."""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from pathlib import Path

from .models import RuntimeEvent, utc_now

LOGGER = logging.getLogger(__name__)


class ConversationTrash:
    def __init__(self, settings, database, sync_remote):
        self.settings = settings
        self.database = database
        self.sync_remote = sync_remote
        self.directory = settings.root / ".state" / "conversation-lifecycle"
        self.lock = threading.RLock()

    def _path(self, cid):
        if not cid or Path(cid).name != cid or cid in {".", ".."}:
            raise ValueError("Identificador de conversa inválido.")
        return self.directory / f"{cid}.json"

    def _save(self, data):
        target = self._path(data["id"])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def _paths(self, data):
        source = self.settings.resolve_path(data["workspace"])
        work_root = self.settings.work_dir.resolve()
        destination = (self.settings.root / ".trash" / "conversations" / data["id"]).resolve()
        if data["managed"] and (source == work_root or not source.is_relative_to(work_root)):
            raise ValueError("Diário de recuperação contém workspace fora da área gerenciada.")
        return source, destination

    def _pending(self, data, exc):
        LOGGER.error("Recuperação da conversa %s pendente: %s", data["id"], exc)
        try:
            self.database.add_event(RuntimeEvent(
                data["id"], "lifecycle_recovery_required",
                "A recuperação da conversa está pendente. Os arquivos foram preservados.",
                {"operation": "trash", "error": str(exc)},
            ))
        except Exception:
            LOGGER.exception("Diário preservado; banco indisponível para registrar recuperação.")

    def _reconcile(self, data):
        source, destination = self._paths(data)
        row = self.database.get_conversation(data["id"])
        if row is None:
            raise RuntimeError("Conversa do diário não encontrada; recuperação manual necessária.")
        expected = destination if data["managed"] else source
        committed = bool(row["trashed_at"] and row["archived"]
                         and self.settings.resolve_path(row["workspace"]) == expected)
        if committed:
            # A commit may have succeeded even if its acknowledgement failed.
            # Never roll the filesystem back underneath a committed DB row.
            if data["managed"] and not destination.exists():
                raise RuntimeError("Banco confirmou a lixeira, mas a pasta não foi localizada.")
        else:
            try:
                if data["managed"]:
                    if source.exists() and destination.exists():
                        raise RuntimeError("Origem e lixeira existem; nenhuma pasta foi sobrescrita.")
                    if destination.exists():
                        source.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(destination), str(source))
                    if not source.exists():
                        raise RuntimeError("Workspace não localizado para recuperação.")
            finally:
                if not data["archived"]:
                    self.sync_remote(data, "unarchive")
        self._path(data["id"]).unlink(missing_ok=True)

    def recover_all(self):
        with self.lock:
            for path in sorted(self.directory.glob("*.json")):
                data = None
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if self._path(data["id"]).resolve() != path.resolve():
                        raise ValueError("Identidade do diário inconsistente.")
                    self._reconcile(data)
                except Exception as exc:
                    if data is not None and isinstance(data, dict) and data.get("id"):
                        self._pending(data, exc)
                    else:
                        LOGGER.exception("Diário de lifecycle inválido: %s", path)

    def trash(self, row):
        with self.lock:
            cid = str(row["id"])
            if self._path(cid).exists():
                raise RuntimeError("Esta conversa possui recuperação pendente. Reinicie para tentar recuperá-la.")
            source = self.settings.resolve_path(row["workspace"])
            work_root = self.settings.work_dir.resolve()
            data = {key: row[key] for key in ("id", "workspace", "archived", "provider", "native_id", "native_id_vr")}
            data["managed"] = source.exists() and source != work_root and source.is_relative_to(work_root)
            _, destination = self._paths(data)
            # Preflight cannot overwrite an existing trash directory, including
            # one unrelated to this operation. No journal/remote action yet.
            if data["managed"] and destination.exists():
                raise FileExistsError(f"A lixeira já contém uma pasta para a conversa {cid}.")
            self._save(data)
            try:
                if not row["archived"]:
                    self.sync_remote(row, "archive")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if data["managed"]:
                    shutil.move(str(source), str(destination))
                self.database.update_conversation(
                    cid, archived=1, trashed_at=utc_now(),
                    original_workspace=self.settings.relative_path(source),
                    workspace=self.settings.relative_path(destination if data["managed"] else source),
                )
            except Exception:
                try:
                    self._reconcile(data)
                except Exception as recovery_error:
                    self._pending(data, recovery_error)
                    raise RuntimeError(
                        "A recuperação da conversa está pendente. Os arquivos foram preservados; "
                        "reinicie para tentar a recuperação novamente."
                    ) from recovery_error
                raise
            else:
                self._path(cid).unlink(missing_ok=True)
