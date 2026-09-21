"""Application scope must survive shared names, packages, refreshes and edits."""
import hashlib
import zipfile

import pytest

from test_code_index import _jar, _JavaSourceAdapter
from test_apps_catalog_audit import register
from test_apps_catalog_bridge import bridge, wait_until  # noqa: F401
from vrsoft_extractor.mary.application_import import preview_application_import
from vrsoft_extractor.mary.apps_catalog import AppsCatalogError, AppsCatalogStore
from vrsoft_extractor.mary.code_context import (
    application_context_warning,
    freeze_application_contexts,
    master_fallback_context,
    validate_application_contexts,
)
from vrsoft_extractor.mary.code_index import JavaCodeIndex
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.jvm_batches import DecompilationBatchExecutor, DecompilationBatchPlanner
from vrsoft_extractor.mary.jvm_toolchain import DecompileRequest, DecompileResult
from vrsoft_extractor.mary.retrieval.code_relations import caller_evidence
from vrsoft_extractor.mary.retrieval.code_retrieval import (
    read_code_source,
    retrieve_code_candidates,
)


def indexed_contexts(root):
    source = root / "incoming"
    for name in ("VRA", "VRB", "commons-util"):
        _jar(source / f"{name}.jar", name.encode())
    catalog = ErpReleaseCatalog(root, expected_jar_count=3)
    catalog.import_release("one", source)
    plan = DecompilationBatchPlanner(root, catalog=catalog).plan("one", max_classes=20)
    DecompilationBatchExecutor(root, catalog=catalog, adapters=(_JavaSourceAdapter(),)).run(plan["plan_id"], limit=10)
    index = JavaCodeIndex(root, catalog=catalog)
    index.index_plan(plan["plan_id"])
    composition = catalog.apps_store.get_package("one")["composition"]
    selections = [{k: item[k] for k in ("app_id", "version", "variant_id")} | {"package_id": "one"}
                  for item in composition]
    return index, freeze_application_contexts(root, selections)


def test_scoped_search_relations_and_browser_exclude_other_app(tmp_path):
    index, contexts = indexed_contexts(tmp_path)
    assert len(contexts) == 2
    context = contexts[1]
    assert {a["relative_path"] for a in context["artifacts"]} == {"VRB.jar", "commons-util.jar"}
    rows = index.search("Outer", release_id="one", artifacts=context["artifacts"],
                        manifest_hash=context["manifest_sha256"], limit=1)
    assert len(rows) == 1 and rows[0]["jar_relative_path"] != "VRA.jar"
    assert index.search("Outer", release_id="one", artifacts=[]) == []
    assert index.search("Outer", release_id="one", artifacts=context["artifacts"], manifest_hash="wrong") == []
    rows = index.callers("somar", release_id="one", artifacts=context["artifacts"], limit=1)
    assert len(rows) == 1 and rows[0]["jar_relative_path"] != "VRA.jar"
    assert index.callers("somar", release_id="one", artifacts=[]) == []
    evidence = caller_evidence(tmp_path, ["somar"], release_id="one", manifest_hash=context["manifest_sha256"],
                               application_context=context, max_seconds=5)
    assert evidence and all(context["label"] in item.title for item in evidence)
    sources = index.browse_application_sources(context)
    assert len(sources["sources"]) == 2
    body = index.browse_application_sources(context, source_key=sources["sources"][0]["source_key"])
    assert "public class Outer" in body["body"]
    foreign = index.browse_application_sources(contexts[0])["sources"][0]["source_key"]
    with pytest.raises(Exception, match="não pertence"):
        index.browse_application_sources(context, source_key=foreign)
    assert index.browse_application_sources(context, query="NoSuchClass")["sources"] == []


def test_invalid_empty_or_changed_context_never_falls_back(tmp_path):
    _, contexts = indexed_contexts(tmp_path)
    with pytest.raises(AppsCatalogError):
        freeze_application_contexts(tmp_path, [])
    with pytest.raises(AppsCatalogError):
        freeze_application_contexts(tmp_path, [contexts[0], contexts[0]])
    with pytest.raises(AppsCatalogError):
        freeze_application_contexts(tmp_path, [{**contexts[0], "variant_id": "wrong"}])
    validate_application_contexts(tmp_path, contexts)
    _jar(tmp_path / "incoming" / "commons-util.jar", b"changed")
    with pytest.raises(AppsCatalogError):
        validate_application_contexts(tmp_path, contexts)


def test_manual_correction_moves_only_selected_variant_and_survives_import(tmp_path):
    store = AppsCatalogStore(tmp_path)
    first, second = hashlib.sha256(b"one").hexdigest(), hashlib.sha256(b"two").hexdigest()
    register(store, "one", digest=first)
    register(store, "two", digest=second)
    store.override_version("vrapp", "1.0", "2.0", variant_id=first)
    register(store, "one", digest=first)
    register(store, "two", digest=second)
    assert [v["sha256"] for v in store.list_variants("vrapp", "1.0")] == [second]
    assert [v["sha256"] for v in store.list_variants("vrapp", "2.0")] == [first]
    assert store.get_package("one")["composition"][0]["version"] == "2.0"
    assert store.get_package("two")["composition"][0]["version"] == "1.0"


def test_preview_is_read_only_and_detects_reuse_and_variants(tmp_path):
    source = tmp_path / "source"
    _jar(source / "VRApp.jar")
    root = tmp_path / "workspace"
    preview = preview_application_import(root, str(source), single=False)
    assert not root.exists()
    assert preview["rows"][0]["status"] == "Novo aplicativo"
    catalog = ErpReleaseCatalog(root, expected_jar_count=1)
    catalog.import_release("one", source)
    assert "reutilizar" in preview_application_import(root, str(source), single=False)["rows"][0]["status"]
    _jar(source / "VRApp.jar", b"different")
    changed = preview_application_import(root, str(source), single=False)
    assert changed["rows"][0]["status"] == "Nova variante"
    assert changed["fingerprint"] != preview["fingerprint"]


@pytest.mark.qml
def test_qt_contexts_persist_multiple_apps_and_keep_unavailable_selection(bridge):  # noqa: F811
    _, contexts = indexed_contexts(bridge._settings.root)
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    for context in contexts:
        bridge.selectApplication(context["app_id"])
        bridge.selectAppVersion(context["version"])
        assert bridge.addSelectedApplicationContext()
    assert bridge.ultraApplicationContextsReady
    bridge.setCodeAnalysisEnabled(True)
    assert bridge.codeAnalysisEnabled
    bridge._load_research_config()
    assert len(bridge.ultraApplicationContexts) == 2
    assert bridge.codeAnalysisEnabled
    # An unrelated processing selection must not change the Ultra scope.
    bridge.selectApplication("")
    assert len(bridge.ultraApplicationContexts) == 2
    ErpReleaseCatalog(bridge._settings.root).apps_store.unlink_package("one")
    bridge.refreshApplicationsCatalog()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    assert len(bridge.ultraApplicationContexts) == 2
    assert not bridge.ultraApplicationContextsReady
    bridge.removeApplicationContext(contexts[0]["app_id"])
    bridge.removeApplicationContext(contexts[1]["app_id"])
    assert not bridge.codeAnalysisEnabled


@pytest.mark.qml
def test_qt_preview_cancel_and_changed_source(bridge, tmp_path):  # noqa: F811
    source = tmp_path / "source"
    _jar(source / "VRApp.jar")
    assert bridge.previewApplicationImport(str(source), False, "one")
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert bridge.applicationImportPreview["state"] == "ready"
    bridge.cancelApplicationImport()
    assert not bridge.confirmApplicationImport()
    assert not bridge.applicationsCatalog
    assert bridge.previewApplicationImport(str(source), False, "one")
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    _jar(source / "VRApp.jar", b"changed")
    assert bridge.confirmApplicationImport()
    wait_until(lambda: not bridge.releaseSnapshotRunning)
    assert "mudaram" in bridge.releaseSnapshotStatus
    assert not bridge.applicationsCatalog


def test_ultra_execution_freezes_multiple_contexts_and_labels_evidence(tmp_path, monkeypatch):
    from test_mary_vr_ultra import _orchestrator, _run_send
    import json
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "ultra")
    _, contexts = indexed_contexts(settings.root)
    calls = []
    original = JavaCodeIndex.search

    def search(self, query, **kwargs):
        calls.append(kwargs)
        return original(self, "Outer", **kwargs)

    monkeypatch.setattr(JavaCodeIndex, "search", search)
    _run_send(orchestrator, cid, events, code_analysis_enabled=True, application_contexts=contexts)
    assert calls and all(call["release_id"] == "one" and call["artifacts"] for call in calls)
    assert {tuple(a["relative_path"] for a in call["artifacts"]) for call in calls} == {
        tuple(a["relative_path"] for a in c["artifacts"]) for c in contexts}
    completed = [event for event in events if event.kind == "agent_completed"
                 and event.payload.get("worker_id") == "ultra_code"]
    assert completed and completed[-1].payload["status"] == "found"
    titles = completed[-1].payload["citations"]
    assert all(any(context["label"] in title for context in contexts) for title in titles)
    assert all(any(context["label"] in title for title in titles) for context in contexts)
    run_id = [event.payload["run_id"] for event in events if event.kind == "research_started"][-1]
    stored = json.loads(orchestrator.research_repository.get_run(run_id)["context_json"])
    assert stored["application_contexts"] == contexts


def test_ultra_empty_explicit_context_never_searches_package(tmp_path, monkeypatch):
    from test_mary_vr_ultra import _orchestrator, _run_send
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "ultra")
    calls = []
    monkeypatch.setattr(JavaCodeIndex, "search", lambda *args, **kwargs: calls.append(kwargs) or [])
    _run_send(orchestrator, cid, events, code_analysis_enabled=True, application_contexts=[])
    assert not calls
    assert any(event.kind == "agent_failed" and event.payload.get("worker_id") == "ultra_code" for event in events)


def test_ultra_dev_java_toggle_off_skips_code_and_keeps_documental_flow(
    tmp_path, monkeypatch
):
    from test_mary_vr_ultra import _orchestrator, _run_send
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "ultra")
    search_calls = []
    monkeypatch.setattr(
        JavaCodeIndex, "search", lambda *args, **kwargs: search_calls.append(kwargs) or []
    )

    _run_send(orchestrator, cid, events)

    assert search_calls == []
    assert not any(
        event.payload.get("worker_id") == "ultra_code" for event in events
    )
    for source in ("wiki", "kb", "schema"):
        assert any(
            event.kind == "agent_completed"
            and event.payload.get("worker_id") == f"ultra_{source}"
            for event in events
        )
    assert any(event.kind == "synthesis_started" for event in events)


def test_ultra_dev_java_unavailability_does_not_block_documental_synthesis(
    tmp_path, monkeypatch
):
    from test_mary_vr_ultra import _orchestrator, _run_send
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "ultra")

    def fail_search(*_args, **_kwargs):
        raise RuntimeError("índice indisponível")

    monkeypatch.setattr(JavaCodeIndex, "search", fail_search)

    _run_send(orchestrator, cid, events, code_analysis_enabled=True)

    assert any(
        event.kind == "agent_failed"
        and event.payload.get("worker_id") == "ultra_code"
        for event in events
    )
    for source in ("wiki", "kb", "schema"):
        assert any(
            event.kind == "agent_completed"
            and event.payload.get("worker_id") == f"ultra_{source}"
            for event in events
        )
    completed = [event for event in events if event.kind == "research_completed"][-1]
    assert completed.payload["code_agent"] == "failed"
    assistant = [
        row for row in database.messages(cid) if row["role"] == "assistant"
    ]
    assert assistant and "Resposta Ultra" in assistant[-1]["content"]


def test_ultra_dev_java_does_not_widen_selected_application_scope(
    tmp_path, monkeypatch
):
    from test_mary_vr_ultra import _orchestrator, _run_send
    settings, database, orchestrator, provider, cid, events = _orchestrator(tmp_path, "ultra")
    _, contexts = indexed_contexts(settings.root)
    selected, foreign = contexts[0], contexts[1]
    calls = []
    original = JavaCodeIndex.search

    def search(self, query, **kwargs):
        calls.append(kwargs)
        return original(self, query, **kwargs)

    monkeypatch.setattr(JavaCodeIndex, "search", search)

    _run_send(
        orchestrator,
        cid,
        events,
        code_analysis_enabled=True,
        application_contexts=[selected],
    )

    assert calls
    selected_artifacts = tuple(
        item["relative_path"] for item in selected["artifacts"]
    )
    foreign_artifacts = tuple(
        item["relative_path"] for item in foreign["artifacts"]
    )
    assert {
        tuple(item["relative_path"] for item in call["artifacts"])
        for call in calls
    } == {selected_artifacts}
    assert all(
        tuple(item["relative_path"] for item in call["artifacts"])
        != foreign_artifacts
        for call in calls
    )
    assert all(call["release_id"] == selected["package_id"] for call in calls)


def test_native_read_expansion_cannot_cross_application(tmp_path):
    from vrsoft_extractor.mary.evidence_reads import _indexed_source
    from vrsoft_extractor.mary.models import EvidenceCandidate
    index, contexts = indexed_contexts(tmp_path)
    context = contexts[1]
    own_artifact = [context["artifacts"][0]]
    selected = index.search("Outer", release_id="one", artifacts=own_artifact)[0]
    seed = EvidenceCandidate(evidence_id="code:seed", source="code", source_id=selected["source_key"],
        document_id=0, chunk_id=0, title=context["label"], heading="Outer", content_type="java_decompiled",
        module="", product="", excerpt=selected["excerpt"],
        entities={"application_context": (context["context_id"],)})
    other_class = index.search("Shared", release_id="one", artifacts=own_artifact)[0]
    own_path = tmp_path / other_class["output_reference"] / other_class["source_relative_path"]
    expanded = _indexed_source(own_path, tmp_path, [seed])
    assert expanded and context["label"] in expanded.title
    assert expanded.entities["application_context"] == (context["context_id"],)
    foreign = index.search("Shared", release_id="one", artifacts=[contexts[0]["artifacts"][0]])[0]
    foreign_path = tmp_path / foreign["output_reference"] / foreign["source_relative_path"]
    assert _indexed_source(foreign_path, tmp_path, [seed]) is None


def test_four_package_origins_do_not_limit_one_application_version(tmp_path):
    source = tmp_path / "source"
    _jar(source / "VRApp.jar")
    catalog = ErpReleaseCatalog(tmp_path / "workspace", expected_jar_count=1)
    for number in range(4):
        catalog.import_release(f"package-{number}", source)
    versions = catalog.list_versions("vrapp")
    assert len(versions) == 1 and versions[0]["originCount"] == 4


@pytest.mark.qml
def test_processing_status_follows_selected_artifact(bridge):  # noqa: F811
    _, contexts = indexed_contexts(bridge._settings.root)
    bridge.refreshCodeAnalysisReleases()
    wait_until(lambda: bridge._apps_catalog_thread is None)
    for context in contexts:
        bridge.selectApplication(context["app_id"])
        bridge.selectAppVersion(context["version"])
        wait_until(lambda: not bridge._code_processing_status_loading and bridge._apps_catalog_thread is None)
        assert bridge._code_processing_relative_jars == (context["artifacts"][0]["relative_path"],)
        assert bridge.codeProcessingTotalJars == bridge.codeProcessingCoveredJars == 1


class _CentralSourceAdapter:
    """Emits Outer/Shared for every JAR and Central only for the VRMaster artifact."""

    name = "vineflower"

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        marker = ""
        with zipfile.ZipFile(request.input_path) as archive:
            for entry in archive.namelist():
                if entry.endswith("Outer.class"):
                    marker = archive.read(entry).decode("utf-8", "replace")
                    break
        output = request.output_dir / "br" / "vr"
        output.mkdir(parents=True, exist_ok=True)
        (output / "Outer.java").write_text(
            "package br.vr;\npublic class Outer { public void calcular() {} }\n",
            encoding="utf-8",
        )
        (output / "Shared.java").write_text(
            "package br.vr;\npublic record Shared(String value) {}\n",
            encoding="utf-8",
        )
        if "VRMaster" in marker:
            (output / "Central.java").write_text(
                "package br.vr;\npublic class Central { public void gerarNotaFiscal() {} }\n",
                encoding="utf-8",
            )
        return DecompileResult(
            tool=self.name,
            status="completed",
            duration_ms=4,
            exit_code=0,
            output_dir=str(request.output_dir),
        )


def indexed_contexts_with_master(root):
    source = root / "incoming"
    for name in ("VRA", "VRMaster"):
        _jar(source / f"{name}.jar", name.encode())
    catalog = ErpReleaseCatalog(root, expected_jar_count=2)
    catalog.import_release("one", source)
    plan = DecompilationBatchPlanner(root, catalog=catalog).plan("one", max_classes=20)
    DecompilationBatchExecutor(
        root, catalog=catalog, adapters=(_CentralSourceAdapter(),)
    ).run(plan["plan_id"], limit=10)
    index = JavaCodeIndex(root, catalog=catalog)
    index.index_plan(plan["plan_id"])
    composition = catalog.apps_store.get_package("one")["composition"]
    selections = [{k: item[k] for k in ("app_id", "version", "variant_id")} | {"package_id": "one"}
                  for item in composition]
    return index, freeze_application_contexts(root, selections)


def _contexts_by_app(contexts):
    return {context["app_id"]: context for context in contexts}


def test_master_fallback_context_uses_same_package_only(tmp_path):
    _, contexts = indexed_contexts_with_master(tmp_path)
    by_app = _contexts_by_app(contexts)
    assert set(by_app) == {"vra", "vrmaster"}
    fallback = master_fallback_context(tmp_path, [by_app["vra"]])
    assert fallback is not None and fallback["app_id"] == "vrmaster"
    assert fallback["package_id"] == by_app["vra"]["package_id"]
    assert fallback["context_id"] == by_app["vrmaster"]["context_id"]
    assert master_fallback_context(tmp_path, [by_app["vra"], by_app["vrmaster"]]) is None
    assert master_fallback_context(tmp_path, None) is None


def test_master_fallback_context_absent_from_package(tmp_path):
    _, contexts = indexed_contexts(tmp_path)
    assert all(context["app_id"] != "vrmaster" for context in contexts)
    assert master_fallback_context(tmp_path, [contexts[0]]) is None


def test_application_context_warning_defers_master_to_fallback(tmp_path):
    _, contexts = indexed_contexts_with_master(tmp_path)
    vra = _contexts_by_app(contexts)["vra"]
    master_frame = "vrmaster.dao.notafiscal.AliquotaDAO.carregar(AliquotaDAO.java:14)"
    assert application_context_warning(master_frame, [vra]) == ""
    other_frame = "vrpdv.venda.VendaService.gerar(VendaService.java:12)"
    assert "VRPdv" in application_context_warning(other_frame, [vra])


def test_code_retrieval_uses_master_only_as_fallback(tmp_path, monkeypatch):
    _, contexts = indexed_contexts_with_master(tmp_path)
    by_app = _contexts_by_app(contexts)
    calls = []
    original = JavaCodeIndex.search

    def search(self, query, **kwargs):
        calls.append(kwargs)
        return original(self, query, **kwargs)

    monkeypatch.setattr(JavaCodeIndex, "search", search)

    candidates, _, _ = retrieve_code_candidates(
        tmp_path, "Central", application_contexts=[by_app["vra"]], master_fallback=True
    )
    assert candidates and "fallback VRMaster" in candidates[0].title
    assert candidates[0].entities.get("fallback") == ("vrmaster",)
    assert any(call.get("artifacts") == by_app["vrmaster"]["artifacts"] for call in calls)

    calls.clear()
    candidates, _, _ = retrieve_code_candidates(
        tmp_path, "Outer", application_contexts=[by_app["vra"]], master_fallback=True
    )
    assert candidates and all("fallback VRMaster" not in item.title for item in candidates)
    assert not any(call.get("artifacts") == by_app["vrmaster"]["artifacts"] for call in calls)

    calls.clear()
    candidates, _, _ = retrieve_code_candidates(
        tmp_path, "Central", application_contexts=[by_app["vra"]], master_fallback=False
    )
    assert not candidates
    assert not any(call.get("artifacts") == by_app["vrmaster"]["artifacts"] for call in calls)


def test_code_retrieval_master_mention_triggers_fallback(tmp_path, monkeypatch):
    _, contexts = indexed_contexts_with_master(tmp_path)
    by_app = _contexts_by_app(contexts)
    calls = []
    original = JavaCodeIndex.search

    def search(self, query, **kwargs):
        calls.append(kwargs)
        return original(self, query, **kwargs)

    monkeypatch.setattr(JavaCodeIndex, "search", search)
    text = "Outer vrmaster.dao.notafiscal.AliquotaDAO.carregar(AliquotaDAO.java:14)"
    candidates, _, _ = retrieve_code_candidates(
        tmp_path, text, application_contexts=[by_app["vra"]], master_fallback=True
    )
    assert any("Outer" in item.heading for item in candidates)
    assert any("fallback VRMaster" in item.title for item in candidates)
    assert any(call.get("artifacts") == by_app["vrmaster"]["artifacts"] for call in calls)


def test_read_code_source_falls_back_to_master(tmp_path):
    _, contexts = indexed_contexts_with_master(tmp_path)
    by_app = _contexts_by_app(contexts)
    payload = read_code_source(
        tmp_path, "br.vr.Central", application_contexts=[by_app["vra"]], master_fallback=True
    )
    assert payload["state"] == "available"
    assert payload["fallback"] == "vrmaster"
    assert "fallback VRMaster" in payload["title"]
    assert payload["context_id"] == by_app["vrmaster"]["context_id"]
    assert payload["qualified_name"] == "br.vr.Central"
    assert "class Central" in payload["content"]
    missing = read_code_source(
        tmp_path, "br.vr.Central", application_contexts=[by_app["vra"]], master_fallback=False
    )
    assert missing["state"] == "no_results"
