"""Behavioral regressions found while reviewing the completed T3 chats."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_apps_catalog_bridge import bridge  # noqa: F401
from scripts import batch_decompile as batch
from vrsoft_extractor.mary.code_processing_hardware import detect_code_processing_hardware
from vrsoft_extractor.mary.jvm_toolchain import DecompileResult
from vrsoft_extractor.mary.models import RuntimeEvent


@pytest.mark.qml
def test_approvals_with_same_request_id_keep_conversation_identity(bridge, monkeypatch):  # noqa: F811
    delivered = []
    shown = []
    monkeypatch.setattr(bridge._orchestrator, "approve", lambda *args: delivered.append(args))
    bridge.approvalRequested.connect(shown.append)
    for cid in ("first", "second"):
        bridge._on_runtime_event(RuntimeEvent(cid, "approval_requested", payload={"request_id": "1"}))
    assert len(bridge._pending_approvals) == 2
    bridge.decideApproval(True, False)
    assert delivered[0][:2] == ("first", "1")
    assert shown[-1]["conversation_id"] == "second"
    bridge.decideApproval(False, False)
    assert delivered[1][:2] == ("second", "1")
    assert not bridge._approval_request


@pytest.mark.qml
def test_finishing_conversation_releases_its_approval(bridge):  # noqa: F811
    shown = []
    bridge.approvalRequested.connect(shown.append)
    for cid in ("first", "second"):
        bridge._on_runtime_event(RuntimeEvent(cid, "approval_requested", payload={"request_id": cid}))
    bridge._on_runtime_event(RuntimeEvent("first", "turn_completed"))
    assert shown[-1]["conversation_id"] == "second"
    bridge._on_runtime_event(RuntimeEvent("second", "turn_completed"))
    assert shown[-1] == {}


@pytest.mark.qml
def test_out_of_order_status_does_not_discard_current_result(bridge):  # noqa: F811
    bridge._code_analysis_release = "current"
    bridge._code_processing_status_generation = 200
    bridge._code_processing_status_loading = True
    # An obsolete worker finishes after the current worker.
    bridge._code_processing_status_results.put((200, "current", None, None, "current error"))
    bridge._code_processing_status_results.put((199, "current", None, None, "obsolete error"))
    bridge._poll_code_processing_status()
    assert not bridge._code_processing_status_loading
    assert "current error" in bridge.codeProcessingStatus


@pytest.mark.qml
def test_idle_cancel_uses_selected_release_and_jar(bridge, monkeypatch):  # noqa: F811
    from vrsoft_extractor.mary.jvm_batches import DecompilationBatchStore
    from vrsoft_extractor.mary.code_processing_audit import CodeProcessingAudit

    cancelled, recorded = [], []
    monkeypatch.setattr(DecompilationBatchStore, "cancel_active_plans",
                        lambda self, release_id, **kwargs: cancelled.append((release_id, kwargs)))
    monkeypatch.setattr(CodeProcessingAudit, "record",
                        lambda self, event, **kwargs: recorded.append(kwargs))
    monkeypatch.setattr(bridge, "_refresh_code_analysis_releases", lambda: None)
    monkeypatch.setattr(bridge, "refreshApplicationsCatalog", lambda: None)
    bridge._code_processing_release = "previous"
    bridge._code_processing_manifest_hash = "previous-hash"
    bridge._code_processing_run_id = "previous-run"
    bridge._code_analysis_release = "selected"
    bridge._code_processing_relative_jars = ("App.jar",)
    bridge.cancelCodeProcessing()
    assert cancelled == [("selected", {"relative_jars": ("App.jar",)})]
    assert recorded[0]["manifest_sha256"] != "previous-hash"
    assert recorded[0]["run_id"] != "previous-run"


class _Adapter:
    def __init__(self, name, state, emit_source):
        self.name, self.state, self.emit_source = name, state, emit_source

    def status(self):
        return SimpleNamespace(available=True)

    def decompile(self, request):
        request.output_dir.mkdir(parents=True, exist_ok=True)
        if self.emit_source:
            (request.output_dir / "Partial.java").write_text("class Partial {}")
        return DecompileResult(tool=self.name, status=self.state, duration_ms=1,
                               exit_code=0 if self.state == "completed" else 1,
                               output_dir=str(request.output_dir), error="failed" if self.state != "completed" else "")


def test_failed_and_empty_fallback_cannot_reuse_partial_sources(tmp_path):
    jar = tmp_path / "App.jar"
    jar.write_bytes(b"jar")
    tools = SimpleNamespace(adapters=lambda: [_Adapter("vineflower", "failed", True),
                                            _Adapter("cfr", "completed", False)])
    result = batch.decompile_single_jar(jar, tmp_path / "out", tools)
    assert result.status == "failed"
    assert result.error


def test_same_named_jars_and_existing_output_remain_separate(tmp_path):
    existing = tmp_path / "out/App/Old.java"
    existing.parent.mkdir(parents=True)
    existing.write_text("old user source")
    tools = SimpleNamespace(adapters=lambda: [_Adapter("vineflower", "completed", True)])
    outputs = []
    for directory in ("v1", "v2"):
        jar = tmp_path / directory / "App.jar"
        jar.parent.mkdir()
        jar.write_bytes(directory.encode())
        outputs.append(batch.decompile_single_jar(jar, tmp_path / "out", tools).output_dir)
    assert outputs[0] != outputs[1]
    assert existing.read_text() == "old user source"


def test_batch_global_cpu_limit_is_not_jvm_count(tmp_path, monkeypatch):
    hardware = detect_code_processing_hardware(logical_cpu_count=16, total_memory_mb=16384, available_memory_mb=12000)
    monkeypatch.setattr(batch, "detect_code_processing_hardware", lambda: hardware)
    preferences = SimpleNamespace(value=lambda key: {"code_processing/max_heap_mb": 4096,
                                                     "code_processing/max_cpu_cores": 16}.get(key))
    config = batch.load_global_decompile_config(preferences)
    assert config["max_workers"] == 2
    assert config["max_cpu_cores"] == 16
    captured = []
    monkeypatch.setattr(batch, "JvmToolchain", lambda root: SimpleNamespace(doctor=lambda: {"ready": True}))

    def decompile(jar, out, toolchain, **kwargs):
        captured.append(kwargs)
        return batch.JarDecompileResult(jar, jar.name, out, "completed", "fake", 1, 1)

    monkeypatch.setattr(batch, "decompile_single_jar", decompile)
    result = batch.decompile_jars([Path(f"App{i}.jar") for i in range(4)], tmp_path / "out",
                                 max_workers=16, max_cpu_cores=16, heap_mb=4096)
    assert result["succeeded"] == 4
    assert all(c["max_cpu_cores"] == 8 for c in captured)


def test_cancel_output_selection_does_not_start_decompiling(monkeypatch):
    monkeypatch.setattr(batch, "select_jars_dialog", lambda _: [Path("App.jar")])
    monkeypatch.setattr(batch, "select_output_dir_dialog", lambda _: None)
    monkeypatch.setattr(batch, "decompile_jars", lambda **kwargs: pytest.fail("cancelled operation ran"))
    assert batch.batch_decompile_interactive() is None


@pytest.mark.qml
def test_approval_dialog_stays_open_for_next_queued_request(bridge, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QObject
    from PySide6.QtTest import QTest
    from vrsoft_extractor.mary.frontend.app import create_engine
    from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
    from vrsoft_extractor.mary.frontend.studio import StudioBridge

    monkeypatch.setattr(bridge, "refreshModels", lambda: None)
    monkeypatch.setattr(bridge._orchestrator, "approve", lambda *args: None)
    frontend = FrontendBridge(bridge._settings, bridge._preferences, initial_page="Chat VR")
    studio = StudioBridge(bridge._settings, bridge._database, bridge._preferences)
    engine = create_engine(frontend, bridge, studio)
    window = engine.rootObjects()[0]
    try:
        QTest.qWait(100)
        for cid in ("first", "second"):
            bridge._on_runtime_event(RuntimeEvent(cid, "approval_requested", payload={"request_id": "1"}))
        QTest.qWait(100)
        dialog = window.findChild(QObject, "chatApprovalDialog")
        assert dialog.property("opened")
        window.findChild(QObject, "chatApproveOnce").click()
        QTest.qWait(100)
        assert bridge._approval_request["conversation_id"] == "second"
        assert dialog.property("opened")
        bridge._on_runtime_event(RuntimeEvent("second", "turn_completed"))
        QTest.qWait(100)
        assert not dialog.property("opened")
        assert not engine._qml_warnings
    finally:
        window.close()
        studio.close()
