"""Exercise the ChatBridge knowledge package flow across export and import."""
from __future__ import annotations

import hashlib
import threading
import time

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.content import sha256_text, write_document
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.bridges import knowledgetransfer
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.models import KnowledgeDocument

pytestmark = pytest.mark.qml


def wait_until(predicate):
    deadline = time.monotonic() + 6
    while not predicate():
        QApplication.processEvents()
        assert time.monotonic() < deadline, "Qt task did not complete"
        time.sleep(0.005)


@pytest.fixture
def bridge(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(
        app_dir=tmp_path, root=tmp_path / "workspace", old_root=tmp_path / "old"
    )
    db = MaryDatabase(
        settings.database_path, root=settings.root, backup_portable_migration=False
    )
    chat = ChatBridge(
        settings, db, QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    )
    wait_until(lambda: chat._apps_catalog_thread is None)
    yield chat
    chat.close()
    app.processEvents()


def _seed(
    bridge: ChatBridge,
    *,
    source: str = "wiki",
    origin: str = "vrwiki",
    source_id: str = "1",
    title: str = "Documento Um",
    module: str = "Fiscal",
    review_status: str = "approved",
    markdown: str = "# Seção\n\nconteúdo",
    asset_bytes: bytes | None = None,
) -> str:
    assets: list[str] = []
    if asset_bytes is not None:
        digest = hashlib.sha256(asset_bytes).hexdigest()
        relative = (
            f"assets/wiki/{digest}.png"
            if origin == "vrwiki"
            else f"assets/wiki/endoo/{digest}.png"
            if origin == "endoo"
            else f"assets/kb/{digest}.png"
        )
        target = bridge._settings.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(asset_bytes)
        assets.append(relative)
    document = KnowledgeDocument(
        source=source,
        source_origin=origin,
        source_id=source_id,
        title=title,
        url=f"https://example.test/{source_id}",
        markdown=markdown,
        module=module,
        classification_confidence=0.8,
        review_status=review_status,
        content_hash=sha256_text("\n".join([title, markdown])),
        synced_at="2026-01-01T00:00:00+00:00",
        assets=assets,
    )
    write_document(bridge._settings.root, document)
    bridge._database.upsert_document(document)
    return relative if assets else ""


def test_knowledge_slots_and_properties_are_exposed(bridge):
    for signature in (
        "refreshKnowledgeTransferSummary()",
        "exportKnowledgePackage(bool,bool,bool,QString)",
        "exportKnowledgePackage(bool,bool,bool,QString,QString)",
        "detectKnowledgePackageArchive(QString)",
        "importKnowledgePackageArchive(QString,QString)",
    ):
        assert bridge.metaObject().indexOfMethod(signature) >= 0, signature
    for name in (
        "knowledgeTransferRunning",
        "knowledgeTransferOperation",
        "knowledgeTransferProgress",
        "knowledgeTransferProcessed",
        "knowledgeTransferTotal",
        "knowledgeTransferSources",
    ):
        assert bridge.property(name) is not None, name


def test_knowledge_transfer_sources_summary_counts_documents_and_assets(bridge):
    _seed(bridge, source_id="1", asset_bytes=b"imagem")
    _seed(bridge, source_id="2", title="Documento Dois")

    bridge.refreshKnowledgeTransferSummary()

    items = bridge.knowledgeTransferSources
    vrwiki = next(item for item in items if item["value"] == "wiki/vrwiki")
    endoo = next(item for item in items if item["value"] == "wiki/endoo")
    kb = next(item for item in items if item["value"] == "kb/movidesk")
    assert vrwiki["documents"] == 2
    assert vrwiki["assets"] == 1
    assert vrwiki["available"] is True
    assert endoo["documents"] == 0
    assert kb["documents"] == 0


def test_detect_dialog_cancel_does_not_change_state(bridge, monkeypatch):
    before_status = bridge.releaseSnapshotStatus
    monkeypatch.setattr(
        knowledgetransfer.QFileDialog, "getOpenFileName", lambda *args: ("", "")
    )

    result = bridge.detectKnowledgePackageArchive("")

    assert result == {"is_valid": False, "knowledge_package": True, "canceled": True}
    assert bridge.releaseSnapshotRunning is False
    assert bridge.knowledgeTransferRunning is False
    assert bridge.releaseSnapshotStatus == before_status


def test_export_save_dialog_cancel_is_silent(bridge, monkeypatch):
    before_status = bridge.releaseSnapshotStatus
    monkeypatch.setattr(
        knowledgetransfer.QFileDialog, "getSaveFileName", lambda *args: ("", "")
    )

    result = bridge.exportKnowledgePackage(True, False, True, "Todos", "")

    assert result == {"success": False, "canceled": True}
    assert bridge.releaseSnapshotRunning is False
    assert bridge.knowledgeTransferRunning is False
    assert bridge.releaseSnapshotStatus == before_status


def test_export_requires_at_least_one_origin(bridge, tmp_path):
    result = bridge.exportKnowledgePackage(False, False, False, "", str(tmp_path / "x.zip"))
    assert result["success"] is False
    assert "origem" in result["error"].casefold()
    assert bridge.knowledgeTransferRunning is False


def test_export_runs_off_qt_thread_rejects_overlap_and_emits_signal(
    bridge, tmp_path, monkeypatch
):
    entered, release, heartbeat = (threading.Event() for _ in range(3))
    worker_threads: list[int] = []
    exported: list[dict] = []
    bridge.knowledgePackageExported.connect(lambda result: exported.append(dict(result)))

    def blocked(*args, progress=None, **kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        release.wait(5)
        return {
            "success": True,
            "destination": str(tmp_path / "pacote.zip"),
            "package_id": "knowledge-test",
            "document_count": 3,
            "asset_count": 2,
            "missing_asset_count": 0,
            "file_count": 5,
            "total_bytes": 123,
        }

    monkeypatch.setattr(knowledgetransfer, "export_knowledge_package", blocked)
    try:
        assert bridge.exportKnowledgePackage(
            True, False, True, "Todos", str(tmp_path / "pacote.zip")
        )["pending"]
        assert entered.wait(2)
        assert bridge.releaseSnapshotRunning is True
        assert bridge.knowledgeTransferRunning is True
        assert bridge.knowledgeTransferOperation == "export_knowledge"
        assert bridge.exportKnowledgePackage(True, False, True, "", "")["busy"]
        assert bridge.importKnowledgePackageArchive("x.zip")["busy"]
        QTimer.singleShot(0, heartbeat.set)
        wait_until(heartbeat.is_set)
        assert worker_threads != [threading.get_ident()]
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert bridge.knowledgeTransferRunning is False
    assert len(exported) == 1
    assert exported[0]["document_count"] == 3
    assert "Conhecimento exportado com sucesso" in bridge.releaseSnapshotStatus


def test_export_reports_progress_through_poll_timer(bridge, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked(*args, progress=None, **kwargs):
        entered.set()
        progress({"current": 0, "total": 2000})
        progress({"current": 250, "total": 2000})
        release.wait(5)
        progress({"current": 2000, "total": 2000})
        return {
            "success": True,
            "destination": str(tmp_path / "pacote.zip"),
            "package_id": "knowledge-test",
            "document_count": 2000,
            "asset_count": 0,
            "missing_asset_count": 0,
            "file_count": 2000,
            "total_bytes": 1,
        }

    monkeypatch.setattr(knowledgetransfer, "export_knowledge_package", blocked)
    try:
        assert bridge.exportKnowledgePackage(
            True, False, True, "", str(tmp_path / "pacote.zip")
        )["pending"]
        assert entered.wait(2)
        wait_until(lambda: bridge.knowledgeTransferProgress == 12.5)
        assert bridge.knowledgeTransferRunning is True
        assert bridge.knowledgeTransferProcessed == 250
        assert bridge.knowledgeTransferTotal == 2000
        assert bridge.releaseSnapshotStatus.startswith("Exportando conhecimento")
    finally:
        release.set()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert bridge.knowledgeTransferRunning is False
    assert "2.000 documentos" in bridge.releaseSnapshotStatus


def test_export_failure_emits_failure_signal(bridge, tmp_path, monkeypatch):
    failures: list[str] = []
    bridge.knowledgeTransferFailed.connect(lambda message: failures.append(message))

    def explode(*args, **kwargs):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(knowledgetransfer, "export_knowledge_package", explode)
    assert bridge.exportKnowledgePackage(
        True, False, True, "", str(tmp_path / "pacote.zip")
    )["pending"]

    wait_until(lambda: not bridge.knowledgeTransferRunning)
    assert failures == ["falha simulada"]
    assert "Não foi possível exportar o conhecimento" in bridge.releaseSnapshotStatus


def test_bridge_export_and_import_round_trip(bridge, tmp_path):
    _seed(bridge, source_id="1", asset_bytes=b"imagem")
    destination = tmp_path / "pacote.zip"

    exported: list[dict] = []
    imported: list[dict] = []
    detections: list[dict] = []
    bridge.knowledgePackageExported.connect(lambda result: exported.append(dict(result)))
    bridge.knowledgePackageImported.connect(lambda result: imported.append(dict(result)))
    bridge.knowledgePackageDetected.connect(lambda result: detections.append(dict(result)))

    assert bridge.exportKnowledgePackage(True, False, True, "Todos", str(destination))["pending"]
    wait_until(lambda: not bridge.knowledgeTransferRunning)
    assert len(exported) == 1
    assert exported[0]["document_count"] == 1

    assert bridge.detectKnowledgePackageArchive(str(destination))["pending"]
    wait_until(lambda: not bridge.knowledgeTransferRunning)
    assert len(detections) == 1
    assert detections[0]["is_valid"] is True
    assert detections[0]["document_count"] == 1

    assert bridge.importKnowledgePackageArchive(str(destination), "merge")["pending"]
    wait_until(lambda: not bridge.knowledgeTransferRunning)
    assert len(imported) == 1
    assert imported[0]["unchanged"] == 1
    assert imported[0]["error_count"] == 0
    assert "Importação de conhecimento concluída" in bridge.releaseSnapshotStatus


def test_detect_invalid_package_emits_result_without_dialog(bridge, tmp_path):
    broken = tmp_path / "quebrado.zip"
    broken.write_bytes(b"not-a-zip")
    detections: list[dict] = []
    bridge.knowledgePackageDetected.connect(lambda result: detections.append(dict(result)))

    assert bridge.detectKnowledgePackageArchive(str(broken))["pending"]

    wait_until(lambda: not bridge.knowledgeTransferRunning)
    assert len(detections) == 1
    assert detections[0]["is_valid"] is False
    assert detections[0]["knowledge_package"] is True
    assert detections[0]["error"]
