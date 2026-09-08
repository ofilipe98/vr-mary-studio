"""Adversarial and positive acceptance cases from the 2026-09-04 audit."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_mary_vr_ultra as ultra
from vrsoft_extractor.endoo_client import EndooReadClient, EndooError, EndooPermissionDenied
from vrsoft_extractor.mary.models import RuntimeEvent, EvidenceBundle, EvidenceCandidate, QueryProfile
from vrsoft_extractor.mary.providers import CodexProvider
from vrsoft_extractor.mary.research_fanout import parse_researcher_output
from vrsoft_extractor.mary.supervision import (
    FinalDraft, ResponseContract, validate_fanout_draft,
)


class AssetResponse:
    def __init__(self, status=200, location=""):
        self.status = status
        self.headers = {"location": location}
        self.disposed = False

    def body(self):
        return b"synthetic asset"

    def dispose(self):
        self.disposed = True


def asset_client(responses):
    client = object.__new__(EndooReadClient)
    client.api_url = "https://api.iendo.us/api"
    client.headers = {"authorization": "Bearer FAKE", "x-user-id": "synthetic", "referer": "private"}
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)

    client.page = SimpleNamespace(request=SimpleNamespace(get=get))
    client._playwright = SimpleNamespace(request=SimpleNamespace(
        new_context=lambda: SimpleNamespace(get=get, dispose=lambda: None),
    ))
    return client, calls


@pytest.mark.parametrize("url,authenticated", [
    ("https://api.iendo.us/api/image.png", True),
    ("https://API.IENDO.US:443/api/image.png", True),
    ("https://api.iendo.us:444/image.png", False),
    ("https://assets.iendo.us/image.png", False),
    ("https://audit-example.b-cdn.net/image.png", False),
])
def test_asset_authentication_is_scoped_to_exact_api_origin(url, authenticated):
    response = AssetResponse()
    client, calls = asset_client([response])
    assert client.get_bytes(url) == b"synthetic asset"
    assert bool(calls[0][1]["headers"]) is authenticated
    assert calls[0][1]["max_redirects"] == 0
    assert response.disposed


def test_asset_redirect_rechecks_origin_and_drops_api_headers():
    redirect = AssetResponse(302, "https://audit-example.b-cdn.net/image.png")
    final = AssetResponse()
    client, calls = asset_client([redirect, final])
    client.get_bytes("https://api.iendo.us/api/image")
    assert calls[0][1]["headers"]["authorization"] == "Bearer FAKE"
    assert calls[1][1]["headers"] == {}
    assert redirect.disposed and final.disposed


@pytest.mark.parametrize("location", ["https://outside.example/image", "http://api.iendo.us/image", "https://user:pass@api.iendo.us/image"])
def test_asset_redirect_to_unsafe_destination_is_not_requested(location):
    redirect = AssetResponse(302, location)
    client, calls = asset_client([redirect])
    with pytest.raises(EndooPermissionDenied):
        client.get_bytes("https://api.iendo.us/api/image")
    assert len(calls) == 1 and redirect.disposed


def test_asset_redirect_loop_is_bounded():
    responses = [AssetResponse(302, "/loop") for _ in range(6)]
    originals = list(responses)
    client, calls = asset_client(responses)
    with pytest.raises(EndooError, match="limite"):
        client.get_bytes("https://api.iendo.us/api/image")
    assert len(calls) == 6 and all(r.disposed for r in originals)


def test_api_redirect_is_not_followed_with_credentials():
    client, calls = asset_client([AssetResponse(302, "https://outside.example")])
    with pytest.raises(EndooError, match="302"):
        client.get_json("/wiki/articles")
    assert calls[0][1]["max_redirects"] == 0


@pytest.fixture
def session(tmp_path):
    values = ultra._orchestrator(tmp_path, "ultra")
    yield values
    values[2].drain_turn_finalizations()
    values[2]._turn_finalizer_executor.shutdown(wait=True)


class WireProvider(ultra._UltraFakeProvider):
    def __init__(self):
        super().__init__()
        self.wire = CodexProvider()
        self.ready = threading.Event()
        self.callbacks = []

    def send_message(self, conversation_id, native_id, model, effort, workspace,
                     message, callback, options=None, skills=None, image_paths=None):
        self.wire._native_to_local[native_id] = conversation_id
        self.wire._callbacks[conversation_id] = callback
        self.wire._active_turns[conversation_id] = ""
        self.callbacks.append(callback)
        self.ready.set()

    def notify(self, method, turn="", text=""):
        params = {"threadId": "native-x"}
        if turn:
            params["turnId"] = turn
        if method in {"turn/started", "turn/completed"}:
            params["turn"] = {"id": turn}
        else:
            params.update(itemId=turn + "-item", delta=text)
        self.wire._handle_server_message({"method": method, "params": params})


@pytest.mark.parametrize("pending_start", [True, False])
def test_late_turn_events_do_not_corrupt_or_finish_current_turn(session, pending_start):
    _, db, orch, _, cid, events = session
    provider = WireProvider()
    orch.providers = {"codex": provider}
    orch.send(cid, "first", events.append, use_vr=False)
    assert provider.ready.wait(5)
    provider.notify("turn/started", "t1")
    provider.notify("item/agentMessage/delta", "t1", "FIRST_OK")
    provider.notify("turn/completed", "t1")
    orch.drain_turn_finalizations()
    provider.ready.clear()
    orch.send(cid, "second", events.append, use_vr=False)
    assert provider.ready.wait(5)
    if not pending_start:
        provider.notify("turn/started", "t2")
    provider.notify("turn/started", "t1")
    provider.notify("item/agentMessage/delta", "t1", "OLD_DATA")
    provider.notify("turn/completed", "t1")
    # An old provider closure must also be harmless without a turn ID.
    provider.callbacks[0](RuntimeEvent(cid, "assistant_delta", "OLD_CLOSURE"))
    provider.callbacks[0](RuntimeEvent(cid, "turn_completed"))
    assert db.get_conversation(cid)["status"] == "running"
    assert cid in provider.wire._callbacks
    if pending_start:
        provider.notify("turn/started", "t2")
    provider.notify("item/agentMessage/delta", "t2", "SECOND_OK")
    provider.notify("turn/completed", "t2")
    orch.drain_turn_finalizations()
    answers = [(r["content"], r["turn_id"]) for r in db.messages(cid) if r["role"] == "assistant"]
    assert answers == [("FIRST_OK", "t1"), ("SECOND_OK", "t2")]
    assert db.get_conversation(cid)["status"] == "idle"


def test_notifications_without_turn_id_remain_compatible(session):
    _, db, orch, _, cid, events = session
    provider = WireProvider()
    orch.providers = {"codex": provider}
    orch.send(cid, "first", events.append, use_vr=False)
    assert provider.ready.wait(5)
    provider.notify("turn/started")
    provider.notify("item/agentMessage/delta", text="LEGACY_OK")
    provider.notify("turn/completed")
    orch.drain_turn_finalizations()
    assert db.messages(cid)[-1]["content"] == "LEGACY_OK"


@pytest.mark.parametrize("fast_completion", [False, True])
def test_codex_uses_rpc_turn_identity_without_reviving_completed_turn(tmp_path, monkeypatch, fast_completion):
    provider = CodexProvider()
    provider._native_to_local["native"] = "conversation"
    monkeypatch.setattr(provider, "_ensure_started", lambda: None)
    events = []

    def rpc(*args, **kwargs):
        if fast_completion:
            provider._handle_server_message({"method": "turn/completed", "params": {
                "threadId": "native", "turn": {"id": "new"}}})
        return {"turn": {"id": "new"}}

    monkeypatch.setattr(provider, "_rpc", rpc)
    provider.send_message("conversation", "native", "m", "medium", tmp_path, "q", events.append)
    if fast_completion:
        assert "conversation" not in provider._active_turns
        assert "conversation" not in provider._callbacks
    else:
        assert provider._active_turns["conversation"] == "new"
        provider._handle_server_message({"method": "turn/completed", "params": {
            "threadId": "native", "turn": {"id": "old"}}})
        assert "conversation" in provider._callbacks and not events


def test_codex_reconnect_does_not_reaccept_failed_turn():
    provider = CodexProvider()
    provider._native_to_local["native"] = "conversation"
    provider._active_turns["conversation"] = "old"
    provider._callbacks["conversation"] = lambda event: None
    provider._fail_active_turns("synthetic disconnect")
    events = []
    provider._callbacks["conversation"] = events.append
    provider._active_turns["conversation"] = ""
    provider._handle_server_message({"method": "turn/started", "params": {
        "threadId": "native", "turn": {"id": "old"}}})
    assert not events and provider._active_turns["conversation"] == ""


@pytest.mark.parametrize("status,success", [("found", True), ("exhausted", True), ("unavailable", False)])
def test_researcher_status_and_unsupported_claims_are_not_promoted(status, success):
    result = parse_researcher_output(json.dumps({"source_status": status, "findings": [
        {"claim": "UNSUPPORTED", "kind": "fact", "confidence": .99, "evidence_ids": ["unknown"]}
    ]}), worker_id="w", worker_name="W", module="Fiscal", allowed_evidence_ids=("known",))
    assert result.succeeded is success
    assert result.report.source_report.status == status
    if status == "found":
        claim = result.report.findings[0]
        assert claim.kind == "hypothesis" and claim.confidence <= .35 and not claim.evidence_ids
    else:
        assert not result.report.findings and result.report.missing_information


def test_ultra_rejects_persistently_unsupported_final_answer(session, monkeypatch):
    _, db, orch, _, cid, events = session
    monkeypatch.setattr(ultra, "SYNTHESIS", json.dumps({
        "answer_markdown": "UNSUPPORTED_FINAL", "used_evidence_ids": []}))
    ultra._run_send(orch, cid, events)
    answer = db.messages(cid)[-1]["content"]
    assert "UNSUPPORTED_FINAL" not in answer
    assert "Não consegui produzir" in answer


def test_ultra_explicit_insufficiency_uses_controlled_message(session, monkeypatch):
    _, db, orch, _, cid, events = session
    monkeypatch.setattr(ultra, "SYNTHESIS", json.dumps({
        "answer_markdown": "UNSUPPORTED_PROSE", "used_evidence_ids": [],
        "answer_status": "insufficient_evidence"}))
    ultra._run_send(orch, cid, events)
    answer = db.messages(cid)[-1]["content"]
    assert "UNSUPPORTED_PROSE" not in answer and "lacunas" in answer


def test_ultra_rewrite_cannot_bypass_missing_steps_with_valid_source(session):
    _, db, orch, _, cid, events = session
    ultra._run_send(orch, cid, events, response_mode="implementation")
    assert "Não consegui produzir" in db.messages(cid)[-1]["content"]


def test_ultra_synthesis_and_rewrite_receive_original_sources(session, monkeypatch):
    _, db, orch, _, cid, events = session
    marker = "PRIMARY_ONLY_F2C9"
    with db.connect() as con:
        con.execute("UPDATE knowledge_chunks SET content=content || ?", (" " + marker,))
    prompts = []

    class Capture(ultra._UltraFakeProvider):
        def send_message(self, *args, **kwargs):
            prompts.append((args[0], args[5]))
            return super().send_message(*args, **kwargs)

    orch.providers = {"codex": Capture()}
    monkeypatch.setattr(ultra, "SYNTHESIS", json.dumps({"answer_markdown": "incomplete", "used_evidence_ids": []}))
    ultra._run_send(orch, cid, events)
    main = [prompt for local, prompt in prompts if local == cid]
    assert len(main) == 2
    assert all(marker in prompt and "wiki:nf-fiscal:1" in prompt for prompt in main)
    assert all("url" in prompt and "source_origin" in prompt for prompt in main)


def test_valid_envelope_citation_does_not_require_url_in_markdown(session):
    _, db, orch, _, cid, events = session
    ultra._run_send(orch, cid, events)
    answer = db.messages(cid)[-1]["content"]
    assert "Resposta Ultra" in answer and "https://wiki.example/nf" in answer
    with db.connect() as con:
        assert con.execute("SELECT count(*) FROM source_citations WHERE conversation_id=?", (cid,)).fetchone()[0] > 0


def test_final_gate_keeps_content_requirements_with_valid_citation():
    bundle = EvidenceBundle(QueryProfile(query="q", intents={}), candidates=(EvidenceCandidate(
        "known", "wiki", "s", 1, 1, "Title", "H", "section", "Fiscal", "", "Evidence"),))
    contract = ResponseContract("guidance", "user", "low", "high", minimum_steps=3, minimum_words=40)
    violations = validate_fanout_draft(FinalDraft("Too short", ("known",)), contract, bundle)
    assert {v.code for v in violations} >= {"missing_steps", "too_short"}
    assert "missing_sources" not in {v.code for v in violations}


@pytest.mark.parametrize("already_archived", [False, True])
def test_trash_move_failure_compensates_only_its_own_archive(session, monkeypatch, already_archived):
    _, db, orch, _, cid, _ = session
    db.update_conversation(cid, archived=int(already_archived))
    actions = []
    monkeypatch.setattr(orch, "_sync_codex_lifecycle", lambda row, action: actions.append(action) or True)
    monkeypatch.setattr(orch, "_compensate_codex_lifecycle", lambda row, action: actions.append(action))

    def fail_move(*args):
        raise PermissionError("synthetic lock")

    monkeypatch.setattr("vrsoft_extractor.mary.orchestrator.shutil.move", fail_move)
    with pytest.raises(PermissionError):
        orch.trash(cid)
    assert actions == ([] if already_archived else ["archive", "unarchive"])
    assert bool(db.get_conversation(cid)["archived"]) is already_archived
    assert not db.get_conversation(cid)["trashed_at"]


def test_trash_database_failure_restores_workspace_and_remote_state(session, monkeypatch):
    settings, db, orch, _, cid, _ = session
    source = settings.resolve_path(db.get_conversation(cid)["workspace"])
    (source / "keep.txt").write_text("preserve", encoding="utf-8")
    actions = []
    monkeypatch.setattr(orch, "_sync_codex_lifecycle", lambda row, action: actions.append(action) or True)
    monkeypatch.setattr(orch, "_compensate_codex_lifecycle", lambda row, action: actions.append(action))

    def fail_update(*args, **kwargs):
        raise RuntimeError("synthetic database failure")

    monkeypatch.setattr(db, "update_conversation", fail_update)
    with pytest.raises(RuntimeError, match="database"):
        orch.trash(cid)
    assert (source / "keep.txt").read_text(encoding="utf-8") == "preserve"
    assert actions == ["archive", "unarchive"]


def test_trash_directory_creation_failure_is_compensated(session, monkeypatch):
    settings, db, orch, _, cid, _ = session
    actions = []
    monkeypatch.setattr(orch, "_sync_codex_lifecycle", lambda row, action: actions.append(action) or True)
    monkeypatch.setattr(orch, "_compensate_codex_lifecycle", lambda row, action: actions.append(action))
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == settings.root / ".trash" / "conversations":
            raise PermissionError("synthetic directory failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    with pytest.raises(PermissionError):
        orch.trash(cid)
    assert actions == ["archive", "unarchive"]
    assert not db.get_conversation(cid)["trashed_at"]


def test_failed_remote_compensation_is_persisted_for_recovery(session, monkeypatch):
    _, db, orch, _, cid, _ = session

    def fail_remote(*args):
        raise RuntimeError("synthetic provider unavailable")

    monkeypatch.setattr(orch, "_sync_codex_lifecycle", fail_remote)
    orch._compensate_codex_lifecycle(db.get_conversation(cid), "unarchive")
    with db.connect() as con:
        row = con.execute("SELECT payload_json FROM runtime_events WHERE conversation_id=? AND kind='lifecycle_recovery_required'", (cid,)).fetchone()
    assert row and json.loads(row[0])["operation"] == "unarchive"
