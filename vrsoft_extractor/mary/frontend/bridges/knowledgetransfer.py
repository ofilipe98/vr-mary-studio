from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog

from ...knowledge_transfer import (
    KNOWLEDGE_ORIGINS,
    detect_knowledge_package_archive,
    export_knowledge_package,
    import_knowledge_package_archive,
    origin_label,
)


class KnowledgeTransferDomain:
    """Knowledge package operations using the facade as state and thread owner."""

    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        return getattr(self._owner, name)

    def __setattr__(self, name, value):
        setattr(self._owner, name, value)

    def refreshKnowledgeTransferSummary(self) -> None:  # noqa: N802
        self._knowledge_transfer_sources = self._load_knowledge_transfer_sources()
        self.stateChanged.emit()

    def _load_knowledge_transfer_sources(self) -> list[dict[str, Any]]:
        counts: dict[tuple[str, str], list[int]] = {}
        try:
            with self._database.connect() as connection:
                rows = connection.execute(
                    """SELECT source,source_origin,
                              count(*) AS documents,
                              coalesce(sum(json_array_length(assets_json)),0) AS assets
                         FROM documents
                        WHERE status='active'
                          AND source IN ('wiki','kb')
                          AND trim(source_origin)<>''
                        GROUP BY source,source_origin"""
                ).fetchall()
            for row in rows:
                counts[(str(row["source"]), str(row["source_origin"]))] = [
                    int(row["documents"] or 0),
                    int(row["assets"] or 0),
                ]
        except Exception:
            counts = {}
            try:
                with self._database.connect() as connection:
                    rows = connection.execute(
                        """SELECT source,source_origin,assets_json
                             FROM documents
                            WHERE status='active'
                              AND source IN ('wiki','kb')
                              AND trim(source_origin)<>''"""
                    ).fetchall()
                for row in rows:
                    stats = counts.setdefault(
                        (str(row["source"]), str(row["source_origin"])), [0, 0]
                    )
                    stats[0] += 1
                    try:
                        stats[1] += len(json.loads(row["assets_json"] or "[]"))
                    except (TypeError, ValueError):
                        continue
            except Exception:
                counts = {}
        items: list[dict[str, Any]] = []
        for source, source_origin in KNOWLEDGE_ORIGINS:
            documents, assets = counts.get((source, source_origin), [0, 0])
            items.append({
                "value": f"{source}/{source_origin}",
                "label": origin_label(source, source_origin),
                "source": source,
                "source_origin": source_origin,
                "documents": documents,
                "assets": assets,
                "available": documents > 0,
            })
        return items

    def exportKnowledgePackage(  # noqa: N802
        self,
        include_vrwiki: bool,
        include_endoo: bool,
        include_kb: bool,
        module: str = "",
        destination_file: str = "",
    ) -> dict[str, Any]:
        if (
            self._closed
            or self._release_snapshot_running
            or self._code_processing_running
        ):
            return {"success": False, "busy": True}
        origins: list[tuple[str, str]] = []
        if include_vrwiki:
            origins.append(("wiki", "vrwiki"))
        if include_endoo:
            origins.append(("wiki", "endoo"))
        if include_kb:
            origins.append(("kb", "movidesk"))
        if not origins:
            return {
                "success": False,
                "error": "Selecione pelo menos uma origem para exportar.",
            }
        module_filter = str(module or "").strip()
        if module_filter in {"Todos", "Todas"}:
            module_filter = ""
        target_file = str(destination_file or "").strip()
        if not target_file:
            suggested = str(
                Path.home() / f"vr-conhecimento-{datetime.now():%Y-%m-%d}.zip"
            )
            target_file, _selected_filter = QFileDialog.getSaveFileName(
                None,
                "Exportar pacote de conhecimento",
                suggested,
                "Pacote de conhecimento VRStudio (*.zip)",
            )
            if not target_file:
                return {"success": False, "canceled": True}
        workspace = self._settings.root
        self._start_knowledge_transfer_task(
            "export_knowledge",
            lambda progress=None: export_knowledge_package(
                workspace,
                target_file,
                origins=origins,
                module=module_filter,
                progress=progress,
            ),
        )
        return {"pending": True}

    def detectKnowledgePackageArchive(self, archive_path: str = "") -> dict[str, Any]:  # noqa: N802
        if (
            self._closed
            or self._release_snapshot_running
            or self._code_processing_running
        ):
            return {"is_valid": False, "knowledge_package": True, "busy": True}
        target = str(archive_path or "").strip()
        if not target:
            selected, _selected_filter = QFileDialog.getOpenFileName(
                None,
                "Importar pacote de conhecimento",
                str(Path.home()),
                "Pacote de conhecimento VRStudio (*.zip)",
            )
            if not selected:
                return {
                    "is_valid": False,
                    "knowledge_package": True,
                    "canceled": True,
                }
            target = selected
        database = self._database
        self._start_knowledge_transfer_task(
            "detect_knowledge",
            lambda: detect_knowledge_package_archive(target, database=database),
        )
        return {"pending": True}

    def importKnowledgePackageArchive(  # noqa: N802
        self, archive_path: str, mode: str = "merge"
    ) -> dict[str, Any]:
        if (
            self._closed
            or self._release_snapshot_running
            or self._code_processing_running
        ):
            return {"success": False, "busy": True}
        target = str(archive_path or "").strip()
        if not target:
            return {
                "success": False,
                "error": "Selecione o pacote de conhecimento a importar.",
            }
        selected_mode = str(mode or "merge").strip().casefold()
        if selected_mode not in {"merge", "restore"}:
            return {"success": False, "error": "Modo de importação inválido."}
        workspace = self._settings.root
        database = self._database
        self._start_knowledge_transfer_task(
            "import_knowledge",
            lambda progress=None: import_knowledge_package_archive(
                workspace,
                target,
                mode=selected_mode,
                database=database,
                progress=progress,
            ),
        )
        return {"pending": True}

    def _apply_knowledge_transfer_progress(self, current: Any, total: Any) -> None:
        total_value = max(0, int(total or 0))
        current_value = max(0, int(current or 0))
        exporting = self._knowledge_transfer_operation == "export_knowledge"
        label = "Exportando conhecimento" if exporting else "Importando conhecimento"
        if total_value:
            current_value = min(current_value, total_value)
            percent = round(100.0 * current_value / total_value, 1)
            self._release_snapshot_status = (
                f"{label} — {current_value:,}/{total_value:,} itens"
            ).replace(",", ".")
        else:
            percent = 0.0
            self._release_snapshot_status = f"{label}…"
        self._knowledge_transfer_progress = percent
        self._knowledge_transfer_processed = current_value
        self._knowledge_transfer_total = total_value

    def _start_knowledge_transfer_task(self, operation: str, task: Any) -> None:
        workspace = self._settings.root
        results = self._release_snapshot_results
        signal = self._releaseSnapshotReady
        self._release_snapshot_running = True
        self._knowledge_transfer_operation = operation
        self._knowledge_transfer_running = True
        self._knowledge_transfer_progress = 0.0
        self._knowledge_transfer_processed = 0
        self._knowledge_transfer_total = 0
        self._release_snapshot_status = {
            "export_knowledge": "Exportando conhecimento (Wiki, Endoo e KB)…",
            "detect_knowledge": "Verificando pacote de conhecimento…",
            "import_knowledge": "Importando conhecimento (Wiki, Endoo e KB)…",
        }[operation]

        def progress_cb(event: dict[str, Any]) -> None:
            results.put({
                "event": "progress",
                "operation": operation,
                "workspace": workspace,
                **dict(event),
            })

        def worker() -> None:
            result = {"operation": operation, "workspace": workspace}
            try:
                if operation in {"export_knowledge", "import_knowledge"}:
                    result.update(ok=True, result=task(progress_cb))
                else:
                    result.update(ok=True, result=task())
            except Exception as exc:
                result.update(ok=False, error=str(exc))
            results.put(result)
            if not self._closed:
                signal.emit()

        self._package_operation_thread = threading.Thread(target=worker, daemon=False)
        self._release_snapshot_poll_timer.start()
        self._package_operation_thread.start()
        self.stateChanged.emit()
