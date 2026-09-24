"""Large prompt transport and cancellation before provider dispatch."""
import subprocess
import sys
import threading

import pytest

from test_mary_orchestration import FakeProvider
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.provider_adapters.opencode import OpenCodeProvider


@pytest.mark.parametrize("phase", ["context", "retrieval"])
def test_stop_during_preparation_completes_without_provider_callback(tmp_path, monkeypatch, phase):
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "data", old_root=tmp_path / "old")
    database = MaryDatabase(settings.database_path, root=settings.root)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("opencode")
    orchestrator.providers["opencode"] = provider
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    events = []

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        finished.set()
        return None

    if phase == "context":
        monkeypatch.setattr("vrsoft_extractor.mary.retrieval.code_retrieval.resolve_code_contexts", blocked)
    else:
        # VR is tool-driven: preparation in the orchestrator is only the
        # response classification, which must not block the Stop path.
        monkeypatch.setattr(orchestrator.retrieval_service, "classify", blocked)
    cid = orchestrator.new_conversation("opencode", "test", defer_provider_start=True)
    done = threading.Event()

    def callback(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()

    try:
        orchestrator.send(cid, "\n".join(f"linha {i}" for i in range(1000)), callback,
                          use_vr=True)
        assert entered.wait(5)
        orchestrator.interrupt(cid)
        assert done.wait(5), "Stop must not wait for preparation to finish"
        assert database.get_conversation(cid)["status"] == "cancelled"
        assert not provider.sent
        release.set()
        assert finished.wait(5)
        orchestrator.drain_turn_finalizations()
        assert len([e for e in events if e.kind == "turn_completed"]) == 1
        assert not provider.sent
        done.clear()
        orchestrator.send(cid, "Nova mensagem após interromper", callback, use_vr=False)
        assert done.wait(5)
        assert len(provider.sent) == 1
    finally:
        release.set()
        orchestrator.close()


def test_opencode_drains_both_pipes_while_writing_thousand_lines(tmp_path, monkeypatch):
    provider = OpenCodeProvider()
    provider.command = sys.executable
    provider._model_variants = {"test": set()}
    real_popen = subprocess.Popen
    spawned = []
    prompt = "\n".join("linha " + str(i) + " x" * 1000 for i in range(1000))
    script = (
        "import sys,json; "
        "sys.stdout.write('x'*200000+'\\n');sys.stdout.flush();"
        "sys.stderr.write('y'*200000+'\\n');sys.stderr.flush();"
        "data=sys.stdin.read();"
        "print(json.dumps({'type':'text','part':{'text':str(len(data))}}),flush=True)"
    )

    def spawn(command, **kwargs):
        proc = real_popen([sys.executable, "-c", script], **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr("vrsoft_extractor.mary.provider_adapters.opencode.subprocess.Popen", spawn)
    done, sent = threading.Event(), threading.Event()
    events, errors = [], []

    def callback(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()

    def send():
        try:
            provider.send_message("c", "", "test", "medium", tmp_path, prompt, callback)
        except Exception as exc:
            errors.append(exc)
        finally:
            sent.set()

    worker = threading.Thread(target=send, daemon=True)
    try:
        worker.start()
        assert sent.wait(10), "Prompt write deadlocked behind full output pipes"
        assert done.wait(5)
        assert not errors
        assert str(len(prompt)) in "".join(e.text for e in events if e.kind == "assistant_delta")
    finally:
        for proc in spawned:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        worker.join(5)
        provider.close()


def test_opencode_stop_during_model_discovery_never_spawns_late_process(tmp_path, monkeypatch):
    provider = OpenCodeProvider()
    provider.command = "opencode"
    entered, release = threading.Event(), threading.Event()
    errors, spawned = [], []

    def catalog():
        entered.set()
        assert release.wait(5)
        return []

    monkeypatch.setattr(provider, "_load_model_catalog", catalog)
    monkeypatch.setattr("vrsoft_extractor.mary.provider_adapters.opencode.subprocess.Popen",
                        lambda *a, **kw: spawned.append(a))

    def send():
        try:
            provider.send_message("c", "", "test", "medium", tmp_path, "text", lambda e: None)
        except Exception as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=send, daemon=True)
    try:
        worker.start()
        assert entered.wait(5)
        provider.interrupt("c")
        release.set()
        worker.join(5)
        assert not worker.is_alive()
        assert not spawned
        assert errors and "cancelada" in errors[0]
        assert not provider._starting
    finally:
        release.set()
        worker.join(5)
        provider.close()
