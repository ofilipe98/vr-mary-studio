"""Exercise returned evidence and scope, rather than tool registration alone."""
from dataclasses import replace
import json
import subprocess
import threading
from pathlib import Path

import pytest

from test_application_contexts import indexed_contexts, indexed_contexts_with_master
from test_unified_access_modes import _setup_test_env
from vrsoft_extractor.mary.chat_tools import run_vr_read, run_vr_search, run_vr_sources
from vrsoft_extractor.mary.models import KnowledgeDocument
from vrsoft_extractor.mary.provider_adapters.base import _opencode_environment
from vrsoft_extractor.mary.retrieval.code_retrieval import (
    check_code_availability,
    list_code_sources,
    read_code_source,
)
from vrsoft_extractor.mary.knowledge_access import create_scope, publish_scope, close_scope, mcp_command
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.models import RuntimeEvent
from test_mary_orchestration import FakeProvider
from vrsoft_extractor.mary.provider_adapters.codex import CodexProvider


def test_java_search_reference_can_be_read(tmp_path):
    _, _, _, service = _setup_test_env(tmp_path)
    hit = run_vr_search({"query": "SpedFiscalManager", "source": "code"}, service).parsed["results"][0]
    page = run_vr_read({"reference": hit.get("reference", hit["evidence_id"])}, service).parsed
    assert "gerarSpedFiscal" in page.get("content", "")


def test_code_availability_reports_indexed_release_without_selection(tmp_path):
    indexed_contexts(tmp_path)
    result = check_code_availability(tmp_path, application_contexts=None)
    assert result["state"] == "available", result


def test_java_read_rejects_foreign_artifact_and_empty_scope(tmp_path):
    index, contexts = indexed_contexts(tmp_path)
    foreign = index.browse_application_sources(contexts[0])["sources"][0]["source_key"]
    for selection in ([contexts[1]], []):
        result = read_code_source(tmp_path, foreign, application_contexts=selection)
        assert not result.get("content"), result
        assert result["state"] != "available"


def test_java_catalog_pages_do_not_skip_classes(tmp_path):
    _, contexts = indexed_contexts(tmp_path)
    ctx = contexts[1]
    page = list_code_sources(tmp_path, context_id=ctx["context_id"], application_contexts=[ctx], limit=1)
    assert len(page["sources"]) == 1 and page["has_more"]
    following = list_code_sources(tmp_path, context_id=ctx["context_id"], application_contexts=[ctx], limit=1, offset=page["next_cursor"])
    assert following["sources"][0] != page["sources"][0]


def test_default_search_includes_java(tmp_path):
    _, _, _, service = _setup_test_env(tmp_path)
    result = run_vr_search({"query": "SpedFiscalManager"}, service).parsed
    assert any(hit["source"] == "code" for hit in result["results"])


def test_document_inventory_is_readable_and_review_filtered(tmp_path):
    _, db, _, service = _setup_test_env(tmp_path)
    original = service.resolve_document("wiki:sped-wiki-unified")
    db.upsert_document(replace(original, source_id="unreviewed", review_status="pending", markdown="PRIVATE_PENDING_MARKER"))
    result = run_vr_sources({"source": "wiki", "limit": 1}, service).parsed
    assert len(result.get("results", [])) == 1
    page = run_vr_read({"reference": result["results"][0]["reference"]}, service).parsed
    assert "SPED" in page["content"]
    denied = run_vr_read({"reference": "wiki:unreviewed"}, service).parsed
    assert "PRIVATE_PENDING_MARKER" not in json.dumps(denied)


def test_document_search_cursor_advances(tmp_path):
    _, db, _, service = _setup_test_env(tmp_path)
    for i in range(15):
        db.upsert_document(KnowledgeDocument(source="wiki", source_id=f"paging-{i:02d}", url="", title=f"PaginationMarker {i:02d}", markdown="PaginationMarker exclusive", module="Fiscal", review_status="approved", content_hash=str(i)))
    seen = set()
    cursor = 0
    for _ in range(20):
        result = run_vr_search({"query": "PaginationMarker", "source": "wiki", "limit": 2, "cursor": cursor}, service).parsed
        refs = {r.get("reference", r["evidence_id"]) for r in result["results"]}
        assert not refs.intersection(seen)
        seen.update(refs)
        if not result.get("has_more"):
            break
        cursor = result["next_cursor"]
    assert len(seen) == 15


@pytest.mark.parametrize("profile", ["full_access", "auto", "research_readonly"])
def test_opencode_registers_mcp_in_every_profile(tmp_path, profile):
    config = json.loads(_opencode_environment(profile, tmp_path)["OPENCODE_CONFIG_CONTENT"])
    assert "vr-mary-studio" in config.get("mcp", {})


def test_mcp_real_process_obeys_frozen_scope_and_reads_returned_reference(tmp_path):
    index, contexts = indexed_contexts(tmp_path / "mary")
    scope_path = create_scope()
    publish_scope(scope_path, {"application_contexts": [contexts[0]]})
    denied_key = index.browse_application_sources(contexts[1])["sources"][0]["source_key"]
    allowed_key = index.browse_application_sources(contexts[0])["sources"][0]["source_key"]
    requests = [{"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": {
        "name": "vr_read", "arguments": {"reference": "code:" + key}}}
        for number, key in enumerate((denied_key, allowed_key), 1)]
    try:
        result = subprocess.run(mcp_command(tmp_path / "mary", scope_path),
            cwd=tmp_path, input="\n".join(json.dumps(r) for r in requests) + "\n",
            text=True, encoding="utf-8", capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        payloads = [json.loads(r["result"]["content"][0]["text"]) for r in replies]
        assert not payloads[0].get("content")
        assert "class Outer" in payloads[1]["content"]
        assert payloads[1]["context_id"] == contexts[0]["context_id"]
    finally:
        close_scope(scope_path)


@pytest.mark.parametrize("mode", ["off", "vr", "ultra"])
def test_turn_freezes_ui_selection_in_all_modes(tmp_path, mode):
    settings, database, _, _ = _setup_test_env(tmp_path)
    _, contexts = indexed_contexts(settings.root / "isolated")
    # Use the isolated code catalogue with the same real Mary database.
    settings = replace(settings, root=settings.root / "isolated")
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex", final_text="Resposta local")
    orchestrator.providers["codex"] = provider
    captured = []
    original_send = provider.send_message
    from vrsoft_extractor.mary.knowledge_access import load_scope
    def send(*args, **kwargs):
        captured.append(load_scope(args[7].knowledge_context_path))
        return original_send(*args, **kwargs)
    provider.send_message = send
    cid = orchestrator.new_conversation("codex", "sol", defer_provider_start=True, vr_enabled=mode != "off")
    done = threading.Event()
    selections = [{k: contexts[0][k] for k in ("app_id", "version", "variant_id", "package_id")}]
    try:
        orchestrator.send(cid, "Outer", lambda event: done.set() if event.kind == "turn_completed" else None,
            use_vr=mode != "off", vr_mode=mode, application_contexts=selections)
        assert done.wait(20)
        assert captured and captured[0]["application_contexts"] == [contexts[0]]
        assert captured[0]["master_fallback"] == (mode != "off")
        if mode == "vr":
            # Tool-driven VR: the frozen selection is not injected as context;
            # the model reaches it through the knowledge tools.
            assert "Contrato de acesso tool-driven" in provider.sent[0]["message"]
            assert "class Outer" not in provider.sent[0]["message"]
            hits = orchestrator.retrieval_service.search(
                "Outer",
                source="code",
                application_contexts=selections,
                master_fallback=True,
            )["results"]
            assert any("class Outer" in hit.get("excerpt", "") for hit in hits)
    finally:
        orchestrator.close()


def test_master_fallback_reaches_vr_tools_only_when_needed(tmp_path):
    settings, database, _, _ = _setup_test_env(tmp_path)
    _, contexts = indexed_contexts_with_master(settings.root / "isolated")
    settings = replace(settings, root=settings.root / "isolated")
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex", final_text="Resposta local")
    orchestrator.providers["codex"] = provider
    captured = []
    original_send = provider.send_message
    from vrsoft_extractor.mary.knowledge_access import load_scope
    def send(*args, **kwargs):
        captured.append(load_scope(args[7].knowledge_context_path))
        return original_send(*args, **kwargs)
    provider.send_message = send
    cid = orchestrator.new_conversation("codex", "sol", defer_provider_start=True, vr_enabled=True)
    vra = next(context for context in contexts if context["app_id"] == "vra")
    selections = [{k: vra[k] for k in ("app_id", "version", "variant_id", "package_id")}]
    try:
        done = threading.Event()
        orchestrator.send(cid, "Central", lambda event: done.set() if event.kind == "turn_completed" else None,
            use_vr=True, vr_mode="vr", application_contexts=selections)
        assert done.wait(20)
        message = provider.sent[0]["message"]
        # No automatic retrieval: the fallback is reached through vr_search.
        assert "Contrato de acesso tool-driven" in message
        assert "class Central" not in message
        hits = orchestrator.retrieval_service.search(
            "Central",
            source="code",
            application_contexts=selections,
            master_fallback=True,
        )["results"]
        assert any("fallback VRMaster" in hit.get("title", "") for hit in hits)
        assert any("class Central" in hit.get("excerpt", "") for hit in hits)
        # The persisted scope stays the user selection; VRMaster is only a fallback.
        assert captured and captured[0]["application_contexts"] == [vra]
        assert captured[0]["master_fallback"] is True
    finally:
        orchestrator.close()


def test_mismatched_stack_trace_falls_back_to_available_release(tmp_path):
    settings, database, _, _ = _setup_test_env(tmp_path)
    _, contexts = indexed_contexts(settings.root / "isolated")
    settings = replace(settings, root=settings.root / "isolated")
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex", final_text="Resposta local")
    orchestrator.providers["codex"] = provider
    captured = []
    original_send = provider.send_message
    from vrsoft_extractor.mary.knowledge_access import load_scope
    def send(*args, **kwargs):
        captured.append(load_scope(args[7].knowledge_context_path))
        return original_send(*args, **kwargs)
    provider.send_message = send
    cid = orchestrator.new_conversation("codex", "sol", defer_provider_start=True, vr_enabled=True)
    done = threading.Event()
    selections = [{k: contexts[0][k] for k in ("app_id", "version", "variant_id", "package_id")}]
    try:
        orchestrator.send(
            cid,
            "vratacarejo.service.notasaida.NotaSaidaFiscalService.calcular(NotaSaidaFiscalService.java:374)",
            lambda event: done.set() if event.kind == "turn_completed" else None,
            use_vr=True,
            vr_mode="vr",
            application_contexts=selections,
        )
        assert done.wait(20)
        assert captured and captured[0]["application_contexts"] is None
    finally:
        orchestrator.close()


def test_off_tool_output_drives_answer_and_rejected_send_preserves_scope(tmp_path):
    settings, database, _, _ = _setup_test_env(tmp_path)
    orchestrator = ChatOrchestrator(settings, database)
    started, done = threading.Event(), threading.Event()
    class ToolProvider(FakeProvider, CodexProvider):
        def send_message(self, cid, native, model, effort, workspace, message, callback, options=None, *args):
            self.callback, self.cid = callback, cid
            started.set()
        def respond_dynamic_tool(self, request_id, content_items, success=True):
            assert success
            payload = json.loads(content_items[0]["text"])
            self.answer = payload["content"]
            self.callback(RuntimeEvent(self.cid, "assistant_delta", self.answer))
            self.callback(RuntimeEvent(self.cid, "turn_completed"))
    provider = ToolProvider("codex")
    orchestrator.providers["codex"] = provider
    cid = orchestrator.new_conversation("codex", "sol", defer_provider_start=True, vr_enabled=False)
    try:
        orchestrator.send(cid, "Leia a classe", lambda e: done.set() if e.kind == "turn_completed" else None, use_vr=False)
        assert started.wait(10)
        path = orchestrator._turn_access_paths[cid]
        with pytest.raises(Exception):
            orchestrator.send(cid, "Rejeitar", lambda e: None, use_vr=False, application_contexts=[])
        assert orchestrator._turn_access_paths[cid] == path
        assert orchestrator._turn_application_contexts[cid] is None
        provider.callback(RuntimeEvent(cid, "dynamic_tool_requested", "vr_read", {
            "tool": "vr_read", "request_id": "read-code", "arguments": {
                "reference": "br.com.vrsoftware.fiscal.SpedFiscalManager"}}))
        assert done.wait(10)
        assert "gerarSpedFiscal" in provider.answer
        assert not Path(path).exists()
    finally:
        orchestrator.close()


def test_project_sources_are_paged_and_cannot_cross_projects(tmp_path):
    _, _, _, service = _setup_test_env(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "shared.txt").write_text("FIRST_PROJECT_ONLY", encoding="utf-8")
    (second / "shared.txt").write_text("SECOND_PROJECT_ONLY", encoding="utf-8")
    listing = run_vr_sources({"source": "project"}, service, project_workspace=str(first)).parsed
    ref = listing["results"][0]["reference"]
    for project, marker in ((first, "FIRST_PROJECT_ONLY"), (second, "SECOND_PROJECT_ONLY")):
        result = run_vr_read({"reference": ref}, service, project_workspace=str(project)).parsed
        assert result["content"] == marker
    result = run_vr_read({"reference": "project:../second/shared.txt"}, service, project_workspace=str(first)).parsed
    assert not result.get("content")


def test_initialization_preserves_saved_approval_profile(tmp_path):
    _, database, _, _ = _setup_test_env(tmp_path)
    cid = database.create_conversation("codex", "sol", "medium", str(tmp_path))
    database.update_conversation(cid, approval_profile="auto")
    type(database)(database.path, root=database.root)
    assert database.get_conversation(cid)["approval_profile"] == "auto"


def test_evidence_budget_retains_each_source_and_full_identifiers(tmp_path):
    _, _, _, service = _setup_test_env(tmp_path)
    from vrsoft_extractor.mary.knowledge_access import bounded_candidates
    code = service.search("SpedFiscalManager", source="code")["results"][0]
    from vrsoft_extractor.mary.knowledge_access import result_candidates
    original = result_candidates({"results": [code]})[0]
    inputs = [replace(original, evidence_id=f"code:{i}", excerpt="x" * 24000) for i in range(20)]
    inputs += [replace(original, source=source, evidence_id=source, excerpt="y" * 24000) for source in ("wiki", "kb", "schema")]
    compact = bounded_candidates(inputs)
    assert {c.source for c in compact} == {"wiki", "kb", "schema", "code"}
    assert len(json.dumps([c.to_dict() for c in compact], ensure_ascii=False)) <= 32000


def test_citation_title_does_not_claim_unused_document(tmp_path):
    settings, database, _, service = _setup_test_env(tmp_path)
    from vrsoft_extractor.mary.knowledge_access import result_candidates
    candidates = result_candidates(service.search("SPED", source="wiki"))
    orchestrator = ChatOrchestrator(settings, database)
    try:
        assert not orchestrator._candidates_cited_in_content(candidates[0].title, candidates)
        assert orchestrator._candidates_cited_in_content(candidates[0].url, candidates) == candidates
    finally:
        orchestrator.close()


def test_java_citation_persists_identity_and_hash_metadata(tmp_path):
    _, database, _, service = _setup_test_env(tmp_path)
    from vrsoft_extractor.mary.knowledge_access import result_candidates
    hit = service.search("SpedFiscalManager", source="code")["results"][0]
    candidate = result_candidates(service.read(hit["reference"]))[0]
    cid = database.create_conversation("codex", "sol", "medium", str(tmp_path))
    mid = database.add_message(cid, "assistant", candidate.title)
    database.add_source_citations(cid, mid, [candidate.to_dict()])
    citation = database.get_source_citations(mid)[0]
    assert citation["document_id"] is None
    assert citation["evidence_id"] == candidate.evidence_id
    metadata = json.loads(citation["metadata_json"])
    assert metadata["source_sha256"] == list(candidate.entities["source_sha256"])
    assert metadata["release_manifest_sha256"] == list(candidate.entities["release_manifest_sha256"])


def test_cancelled_mcp_scope_is_unusable(tmp_path):
    _, _, _, _ = _setup_test_env(tmp_path)
    from vrsoft_extractor.mary.knowledge_access import invalidate_scope
    path = create_scope()
    publish_scope(path, {"application_contexts": []})
    invalidate_scope(path)
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "vr_read", "arguments": {"reference": "wiki:sped-wiki-unified"}}}
    try:
        result = subprocess.run(mcp_command(tmp_path / "mary", path), cwd=tmp_path,
            input=json.dumps(request) + "\n", capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert json.loads(result.stdout)["result"]["isError"]
        assert "exporta" not in result.stdout
    finally:
        close_scope(path)


def test_legacy_codex_session_gets_tools_without_losing_local_history(tmp_path):
    settings, database, _, _ = _setup_test_env(tmp_path)
    orchestrator = ChatOrchestrator(settings, database)
    provider = FakeProvider("codex")
    orchestrator.providers["codex"] = provider
    cid = orchestrator.new_conversation("codex", "sol", defer_provider_start=True, vr_enabled=True)
    database.update_conversation(cid, native_id_vr="legacy-thread")
    database.add_message(cid, "user", "HISTORY_MUST_SURVIVE")
    done = threading.Event()
    try:
        orchestrator.send(cid, "Continue", lambda e: done.set() if e.kind == "turn_completed" else None, use_vr=True)
        assert done.wait(10)
        assert provider.starts == [cid]
        assert "HISTORY_MUST_SURVIVE" in provider.sent[0]["message"]
        assert {t["name"] for t in provider.start_options[0].dynamic_tools} >= {"vr_search", "vr_sources", "vr_read"}
        row = database.get_conversation(cid)
        assert row["native_id_vr"] == row["native_tools_id_vr"] != "legacy-thread"
        assert any(m["content"] == "HISTORY_MUST_SURVIVE" for m in database.messages(cid))
    finally:
        orchestrator.close()
