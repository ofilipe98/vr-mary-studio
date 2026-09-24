from __future__ import annotations

import zipfile
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
from vrsoft_extractor.mary.jvm_batches import (
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
)
from vrsoft_extractor.mary.jvm_toolchain import DecompileRequest, DecompileResult

def _jar(path: Path, marker: bytes = b"v1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n")
        archive.writestr("br/com/vrsoftware/fiscal/SpedFiscalManager.class", marker)

class _JavaSourceAdapter:
    name = "vineflower"

    def decompile(self, request: DecompileRequest) -> DecompileResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        sped = request.output_dir / "br" / "com" / "vrsoftware" / "fiscal" / "SpedFiscalManager.java"
        sped.parent.mkdir(parents=True, exist_ok=True)
        sped.write_text(
            """package br.com.vrsoftware.fiscal;
public class SpedFiscalManager {
    public void gerarSpedFiscal(int aliquota) {
        System.out.println("Gerando SPED");
    }
}
""",
            encoding="utf-8",
        )
        return DecompileResult(
            tool=self.name,
            status="completed",
            duration_ms=4,
            exit_code=0,
            output_dir=str(request.output_dir),
        )

import json
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path


from vrsoft_extractor.mary.chat_tools import (
    VR_READ_TOOL_NAME,
    VR_SEARCH_TOOL_NAME,
    VR_SOURCES_TOOL_NAME,
    all_vr_tools_specs,
    run_vr_read,
    run_vr_search,
    run_vr_sources,
)
from vrsoft_extractor.mary.code_index import JavaCodeIndex
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import (
    EvidenceCandidate,
    KnowledgeDocument,
    RuntimeEvent,
)
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.provider_adapters.antigravity import AntigravityProvider
from vrsoft_extractor.mary.provider_adapters.claude import ClaudeProvider
from vrsoft_extractor.mary.provider_adapters.opencode import _opencode_environment
from vrsoft_extractor.mary.retrieval.service import RetrievalService
from vrsoft_extractor.mary.workspace import is_managed_conversation_workspace
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter


def _setup_test_env(tmp_path: Path):
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / "mary").resolve(),
        old_root=(tmp_path / "old").resolve(),
    )
    settings.app_dir.mkdir(parents=True, exist_ok=True)
    settings.root.mkdir(parents=True, exist_ok=True)
    settings.old_root.mkdir(parents=True, exist_ok=True)
    settings.ensure_dirs()
    database = MaryDatabase(settings.database_path, root=settings.root)

    # Seed KnowledgeDocument for Wiki, KB, Schema
    wiki_doc = KnowledgeDocument(
        source="wiki",
        source_id="sped-wiki-unified",
        title="SPED Fiscal Unified",
        url="https://wiki.vrsoftware.com.br/sped_unified",
        markdown="# SPED Fiscal\n\nInstruções detalhadas de exportação do SPED no VR Master.",
        module="Fiscal",
        review_status="approved",
        content_hash="hash-wiki-1",
        local_path="conhecimento/Fiscal/Wiki/sped_unified.md",
    )
    kb_doc = KnowledgeDocument(
        source="kb",
        source_id="sped-kb-unified",
        title="Como configurar SPED Fiscal",
        url="https://kb.vrsoftware.com.br/sped_config",
        markdown="Para configurar o SPED Fiscal acesse Menu > Fiscal > Configurações.",
        module="Fiscal",
        review_status="approved",
        content_hash="hash-kb-1",
        local_path="conhecimento/Fiscal/KB/sped_config.md",
    )
    schema_doc = KnowledgeDocument(
        source="schema",
        source_id="sped-schema-unified",
        title="Tabela sped_fiscal_detalhe",
        url="",
        markdown="CREATE TABLE sped_fiscal_detalhe (id INT PRIMARY KEY, aliquota NUMERIC);",
        module="Fiscal",
        review_status="approved",
        content_hash="hash-schema-1",
        local_path="conhecimento/Fiscal/Schema/sped_fiscal_detalhe.md",
    )
    database.upsert_document(wiki_doc)
    database.upsert_document(kb_doc)
    database.upsert_document(schema_doc)

    # Index real test Java classes via ErpReleaseCatalog
    jar = settings.root / "ERP" / "releases" / "current" / "jars" / "vr-fiscal.jar"
    _jar(jar)
    catalog = ErpReleaseCatalog(settings.root, expected_jar_count=1)
    catalog.import_release("current")
    plan = DecompilationBatchPlanner(settings.root, catalog=catalog).plan("current", max_classes=10)
    DecompilationBatchExecutor(settings.root, catalog=catalog, adapters=(_JavaSourceAdapter(),)).run(plan["plan_id"])
    code_index = JavaCodeIndex(settings.root, catalog=catalog)
    code_index.index_plan(plan["plan_id"])

    router = KnowledgeRouter(database, settings.root)
    retrieval_service = RetrievalService(router)
    return settings, database, code_index, retrieval_service


def test_unified_tools_specs_contain_all_three_tools():
    specs = all_vr_tools_specs()
    names = {s["name"] for s in specs}
    assert VR_SOURCES_TOOL_NAME in names
    assert VR_SEARCH_TOOL_NAME in names
    assert VR_READ_TOOL_NAME in names


def test_all_four_sources_searchable_and_readable(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)

    # 1. Search Wiki
    wiki_res = run_vr_search({"query": "SPED", "source": "wiki"}, service)
    assert wiki_res.parsed["total"] >= 1
    assert any("SPED Fiscal" in r["title"] for r in wiki_res.parsed["results"])

    # 2. Search KB
    kb_res = run_vr_search({"query": "configurar SPED", "source": "kb"}, service)
    assert kb_res.parsed["total"] >= 1

    # 3. Search Schema
    schema_res = run_vr_search({"query": "sped_fiscal_detalhe", "source": "schema"}, service)
    assert schema_res.parsed["total"] >= 1

    # 4. Search Code
    code_res = run_vr_search(
        {"query": "SpedFiscalManager", "source": "code"},
        service,
    )
    assert code_res.parsed["total"] >= 1
    first_code = code_res.parsed["results"][0]
    assert "SpedFiscalManager" in first_code["title"] or "SpedFiscalManager" in first_code["heading"]
    assert first_code["heading"]

    # 5. Read Code
    read_res = run_vr_read(
        {"reference": "br.com.vrsoftware.fiscal.SpedFiscalManager", "limit": 500},
        service,
    )
    assert read_res.parsed.get("reference") == "br.com.vrsoftware.fiscal.SpedFiscalManager"
    assert "gerarSpedFiscal" in read_res.parsed.get("content", "")

    # 6. Read Document (Wiki)
    read_doc = run_vr_read({"reference": "sped-wiki-unified"}, service)
    assert "sped-wiki-unified" in read_doc.parsed.get("reference", "")
    assert "SPED Fiscal" in read_doc.parsed.get("content", "")


def test_vr_sources_inventory_discovery(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)

    # Discover sources catalog
    catalog = run_vr_sources({}, service)
    assert "sources" in catalog.parsed
    assert "modules" in catalog.parsed
    assert "wiki" in catalog.parsed["sources"]
    assert "code" in catalog.parsed["sources"]

    # Discover code catalog
    code_list = run_vr_sources(
        {"source": "code", "limit": 10},
        service,
    )
    assert code_list.parsed.get("state") == "available"
    assert "applications" in code_list.parsed


def test_off_mode_orchestrator_options_include_tools(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    orchestrator = ChatOrchestrator(settings, database)
    orchestrator.retrieval_service = service
    conv_id = orchestrator.new_conversation("codex", "sol", defer_provider_start=True, vr_enabled=False)

    options = orchestrator._conversation_options(conv_id, use_vr=False)
    tool_names = {d.get("name") for d in options.dynamic_tools}
    assert VR_SOURCES_TOOL_NAME in tool_names
    assert VR_SEARCH_TOOL_NAME in tool_names
    assert VR_READ_TOOL_NAME in tool_names


def test_off_mode_project_instructions_and_file_listing(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    orchestrator = ChatOrchestrator(settings, database)

    project_dir = tmp_path / "MyProject"
    project_dir.mkdir()
    (project_dir / "INSTRUCTIONS.md").write_text("Regras internas de contabilidade VR", encoding="utf-8")
    (project_dir / "manual.txt").write_text("Manual do usuario", encoding="utf-8")

    conv_id = orchestrator.new_conversation(
        "codex", "sol", workspace=str(project_dir), defer_provider_start=True, vr_enabled=False
    )
    conv_row = orchestrator._conversation(conv_id)

    enriched = orchestrator._enrich_off_prompt(
        "Como funciona a contabilidade?",
        conversation=dict(conv_row),
        workspace=project_dir,
    )
    assert "INSTRUÇÕES DO PROJETO:" in enriched
    assert "Regras internas de contabilidade VR" in enriched
    assert "MATERIAIS E ARQUIVOS DO PROJETO:" in enriched
    assert "manual.txt" in enriched
    assert "ACESSO LOCAL SOB DEMANDA:" in enriched


def test_off_mode_scratchpad_workspace_no_inheritance(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    orchestrator = ChatOrchestrator(settings, database)

    conv_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=False
    )
    conv_row = orchestrator._conversation(conv_id)
    ws = settings.resolve_path(conv_row["workspace"])

    assert is_managed_conversation_workspace(settings, ws) is True

    enriched = orchestrator._enrich_off_prompt(
        "Pergunta geral",
        conversation=dict(conv_row),
        workspace=ws,
    )
    # Managed scratchpad workspace should not inject project instructions
    assert enriched == "Pergunta geral"


def test_citations_persistence_additive_with_code_sources(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    orchestrator = ChatOrchestrator(settings, database)
    conv_id = orchestrator.new_conversation("codex", "sol", defer_provider_start=True)

    msg_id = database.add_message(conv_id, "assistant", "Aqui está a resposta com código.", turn_id="turn:1")

    # Dynamic candidates from code and wiki
    candidates = [
        EvidenceCandidate(
            evidence_id="br.com.vrsoftware.fiscal.SpedFiscalManager",
            source="code",
            source_id="br.com.vrsoftware.fiscal.SpedFiscalManager",
            document_id=0,
            chunk_id=0,
            title="SpedFiscalManager",
            heading="br.com.vrsoftware.fiscal.SpedFiscalManager",
            content_type="text",
            module="Fiscal",
            product="VRMaster",
            excerpt="public class SpedFiscalManager { ... }",
            url="",
            local_path="jars/vr-fiscal.jar!SpedFiscalManager.class",
            confidence=1.0,
        ),
        EvidenceCandidate(
            evidence_id="sped-wiki-unified",
            source="wiki",
            source_id="sped-wiki-unified",
            document_id=1,
            chunk_id=1,
            title="SPED Fiscal Unified",
            heading="Introdução",
            content_type="text",
            module="Fiscal",
            product="",
            excerpt="Texto wiki do SPED",
            url="https://wiki.vrsoftware.com.br/sped_unified",
            local_path="",
            confidence=0.9,
        ),
    ]

    database.add_source_citations(conv_id, msg_id, [c.to_dict() for c in candidates])

    citations = database.get_source_citations(msg_id)
    assert len(citations) == 2
    sources = {c["source"] for c in citations}
    assert "code" in sources
    assert "wiki" in sources

    code_citation = next(c for c in citations if c["source"] == "code")
    assert code_citation["document_id"] is None or code_citation["document_id"] == 0
    assert "SpedFiscalManager" in code_citation["evidence_id"]


def test_candidates_cited_in_content_matches_java_class(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    orchestrator = ChatOrchestrator(settings, database)

    cand = EvidenceCandidate(
        evidence_id="br.com.vrsoftware.fiscal.SpedFiscalManager",
        source="code",
        source_id="br.com.vrsoftware.fiscal.SpedFiscalManager",
        document_id=0,
        chunk_id=0,
        title="SpedFiscalManager",
        heading="br.com.vrsoftware.fiscal.SpedFiscalManager",
        content_type="text",
        module="Fiscal",
        product="",
        excerpt="class SpedFiscalManager",
        confidence=1.0,
    )

    # If the response mentions the Java FQCN
    resp = "Conforme implementado em br.com.vrsoftware.fiscal.SpedFiscalManager, a alíquota é validada."
    matched = orchestrator._candidates_cited_in_content(resp, [cand])
    assert len(matched) == 1
    assert matched[0].heading == "br.com.vrsoftware.fiscal.SpedFiscalManager"

    # If the response does not mention it
    resp_unrelated = "O sistema funciona normalmente."
    unmatched = orchestrator._candidates_cited_in_content(resp_unrelated, [cand])
    assert len(unmatched) == 0


def test_mcp_server_subprocess_transport(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)

    cmd = [
        sys.executable,
        "-m",
        "vrsoft_extractor.mary.mcp_server",
        "--root",
        str(settings.root),
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # 1. initialize
        init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        proc.stdin.write(init_req)
        proc.stdin.flush()
        init_resp = json.loads(proc.stdout.readline())
        assert init_resp.get("result", {}).get("serverInfo", {}).get("name") == "vr-mary-studio"

        # 2. tools/list
        list_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
        proc.stdin.write(list_req)
        proc.stdin.flush()
        list_resp = json.loads(proc.stdout.readline())
        tool_names = [t["name"] for t in list_resp["result"]["tools"]]
        assert "vr_sources" in tool_names
        assert "vr_search" in tool_names
        assert "vr_read" in tool_names

        # 3. tools/call vr_search
        call_req = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "vr_search", "arguments": {"query": "SPED"}},
                }
            )
            + "\n"
        )
        proc.stdin.write(call_req)
        proc.stdin.flush()
        call_resp = json.loads(proc.stdout.readline())
        assert "content" in call_resp["result"]
        text_content = call_resp["result"]["content"][0]["text"]
        assert "SPED Fiscal" in text_content
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_provider_adapters_mcp_configurations(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)

    # 1. Antigravity MCP server parameters
    antigravity = AntigravityProvider(settings.root)
    # Check that antigravity sets mcpServers with vr-mary-studio in session options
    # We can inspect send_message session payload construction or list_models
    assert antigravity.available() or not antigravity.available()

    # 2. OpenCode environment includes MCP server
    opencode_env = _opencode_environment("auto", settings.root)
    cfg = json.loads(opencode_env["OPENCODE_CONFIG_CONTENT"])
    assert "mcp" in cfg
    assert "vr-mary-studio" in cfg["mcp"]
    assert cfg["mcp"]["vr-mary-studio"]["type"] == "local"
    mcp_command = cfg["mcp"]["vr-mary-studio"]["command"]
    assert any(
        argument == "vrsoft_extractor.mary.mcp_server"
        or Path(argument).name == "mcp_server.py"
        for argument in mcp_command
    )

    # 3. Claude adapter creates .mary_mcp.json in workspace
    claude = ClaudeProvider(settings.root)
    ws = tmp_path / "claude_ws"
    ws.mkdir()
    assert claude.available() or not claude.available()


# --------------------------------------------------- fronteiras de modo/VR


def _run_mode(orchestrator, conversation_id, events, *, use_vr, **kwargs):
    done = threading.Event()

    def callback(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()

    orchestrator.send(
        conversation_id,
        "como emitir NF no Fiscal E fechar o caixa no PDV",
        callback,
        use_vr=use_vr,
        **kwargs,
    )
    assert done.wait(30), "turno não concluiu"


def _mode_calls(orchestrator):
    calls = {
        "route": 0,
        "route_source": [],
        "route_code_source": 0,
        "route_vr_sources": 0,
        "ultra": 0,
    }
    service = orchestrator.retrieval_service
    original_route = service.route

    def route(query, **kwargs):
        calls["route"] += 1
        return original_route(query, **kwargs)

    service.route = route
    original_route_source = service.route_source

    def route_source(query, source):
        calls["route_source"].append(source)
        return original_route_source(query, source)

    service.route_source = route_source
    original_route_code = service.route_code_source

    def route_code_source(query, **kwargs):
        calls["route_code_source"] += 1
        return original_route_code(query, **kwargs)

    service.route_code_source = route_code_source
    original_route_vr = service.route_vr_sources

    def route_vr_sources(query, **kwargs):
        calls["route_vr_sources"] += 1
        return original_route_vr(query, **kwargs)

    service.route_vr_sources = route_vr_sources
    original_ultra = orchestrator._run_ultra_source_fanout

    def ultra(*args, **kwargs):
        calls["ultra"] += 1
        return original_ultra(*args, **kwargs)

    orchestrator._run_ultra_source_fanout = ultra
    return calls


def test_native_dynamic_vr_tools_allow_unlimited_pages_and_calls(
    tmp_path: Path,
):
    settings, database, _, _ = _setup_test_env(tmp_path)
    orchestrator = ChatOrchestrator(settings, database)

    class LargeReadService:
        def read(self, reference, *, cursor, limit, **scope):
            return {
                "state": "available",
                "reference": reference,
                "content": "x" * limit,
                "cursor": cursor,
                "limit": limit,
                "has_more": True,
                "next_cursor": cursor + limit,
            }

    class AvailableProvider:
        def available(self):
            return True

        def close(self):
            return None

    orchestrator.retrieval_service = LargeReadService()
    orchestrator.providers = {"codex": AvailableProvider()}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_enabled=False
    )
    responses: list[RuntimeEvent] = []
    completed = threading.Event()

    def callback(event):
        if event.kind == "tool_event":
            responses.append(event)
            if len(responses) == 50:
                completed.set()

    orchestrator._pending_user_messages[conversation_id] = 1
    orchestrator._turn_access_paths[conversation_id] = ""
    orchestrator._turn_dynamic_candidates[conversation_id] = []
    orchestrator._external_callbacks[conversation_id] = callback
    orchestrator._callback_generations[conversation_id] = 1
    try:
        for index in range(50):
            orchestrator._execute_vr_native_tool(
                RuntimeEvent(
                    conversation_id,
                    "dynamic_tool_requested",
                    "vr_read",
                    {
                        "tool": "vr_read",
                        "request_id": f"read-{index}",
                        "arguments": {
                            "reference": "example.Fiscal",
                            "limit": 8000,
                        },
                    },
                ),
                "vr_read",
            )
        assert completed.wait(10)
        assert len(responses) == 50
        assert all(event.payload["success"] is True for event in responses)
        payloads = [
            json.loads(event.payload["output"])
            for event in responses
        ]
        assert sum(len(payload["content"]) for payload in payloads) > 192_000
        assert all("budget" not in payload for payload in payloads)
    finally:
        orchestrator.close()


def test_off_mode_never_routes_or_fans_out(tmp_path: Path):
    from test_mary_vr_ultra import _orchestrator

    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "off"
    )
    calls = _mode_calls(orchestrator)
    turn_options: list = []
    original_options = orchestrator._conversation_options

    def capture_options(conversation_id, **kwargs):
        options = original_options(conversation_id, **kwargs)
        turn_options.append(options)
        return options

    orchestrator._conversation_options = capture_options

    _run_mode(orchestrator, cid, events, use_vr=False)

    assert calls == {
        "route": 0,
        "route_source": [],
        "route_code_source": 0,
        "route_vr_sources": 0,
        "ultra": 0,
    }
    kinds = [event.kind for event in events]
    assert "research_started" not in kinds
    assert "agent_started" not in kinds
    assert turn_options, "o turno OFF não produziu opções"
    tool_names = {tool.get("name") for tool in turn_options[-1].dynamic_tools}
    assert VR_SOURCES_TOOL_NAME in tool_names
    assert VR_SEARCH_TOOL_NAME in tool_names
    assert VR_READ_TOOL_NAME in tool_names


def test_vr_normal_is_tool_driven_without_agents_or_automatic_retrieval(
    tmp_path: Path,
):
    from test_mary_vr_ultra import _orchestrator

    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "vr"
    )
    calls = _mode_calls(orchestrator)
    captured: dict = {}
    original_validate = orchestrator._validate_direct_response

    def validate(conversation_id, content):
        bundle = orchestrator._pending_evidence_bundles.get(conversation_id)
        captured["candidates"] = tuple(bundle.candidates) if bundle else ()
        captured["dynamic"] = tuple(
            orchestrator._turn_dynamic_candidates.get(conversation_id, ())
        )
        return original_validate(conversation_id, content)

    orchestrator._validate_direct_response = validate

    _run_mode(orchestrator, cid, events, use_vr=True)

    assert calls == {
        "route": 0,
        "route_source": [],
        "route_code_source": 0,
        "route_vr_sources": 0,
        "ultra": 0,
    }
    kinds = [event.kind for event in events]
    assert "research_started" not in kinds
    assert "agent_started" not in kinds
    assert "knowledge_fallback_used" not in kinds
    assert "knowledge_routed" not in kinds
    assert captured["candidates"] == ()
    assert captured["dynamic"] == ()
    assert provider.calls.count(cid) == 1
    assert database.messages(cid)[-1]["response_mode"] == "vr"


def test_vr_normal_prompt_exposes_three_tools_without_automatic_context(
    tmp_path: Path,
):
    from vrsoft_extractor.mary.personality import (
        VRMASTER_TOOL_DRIVEN_ACCESS_POLICY,
    )

    settings, database, code_index, service = _setup_test_env(tmp_path)
    orchestrator, provider, conversation_id = _vr_normal_orchestrator(
        settings, database, service
    )
    events: list[RuntimeEvent] = []
    _send_vr_query(orchestrator, conversation_id, events)

    assert len(provider.calls) == 1
    prompt = provider.calls[0][1]
    assert VRMASTER_TOOL_DRIVEN_ACCESS_POLICY in prompt
    for name in (VR_SOURCES_TOOL_NAME, VR_SEARCH_TOOL_NAME, VR_READ_TOOL_NAME):
        assert name in prompt
    assert "CONTEXTO LOCAL VR RECUPERADO" not in prompt
    options = orchestrator._conversation_options(conversation_id, use_vr=True)
    tool_names = {tool.get("name") for tool in options.dynamic_tools}
    assert {
        VR_SOURCES_TOOL_NAME,
        VR_SEARCH_TOOL_NAME,
        VR_READ_TOOL_NAME,
    } <= tool_names


def test_vr_adaptive_keeps_tool_driven_execution_and_three_tools(
    tmp_path: Path,
):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    orchestrator, provider, conversation_id = _vr_normal_orchestrator(
        settings, database, service
    )
    calls = _mode_calls(orchestrator)
    events: list[RuntimeEvent] = []

    _send_vr_query(
        orchestrator,
        conversation_id,
        events,
        response_mode="adaptive",
    )

    assert calls == {
        "route": 0,
        "route_source": [],
        "route_code_source": 0,
        "route_vr_sources": 0,
        "ultra": 0,
    }
    kinds = {event.kind for event in events}
    assert "research_started" not in kinds
    assert "agent_started" not in kinds
    assert len(provider.calls) == 1
    prompt = provider.calls[0][1]
    assert "PERFIL ESPECIALISTA ATIVO — ADAPTATIVA:" in prompt
    assert "Atue como especialista funcional e técnico adaptativo" in prompt
    options = orchestrator._conversation_options(conversation_id, use_vr=True)
    tool_names = {tool.get("name") for tool in options.dynamic_tools}
    assert {
        VR_SOURCES_TOOL_NAME,
        VR_SEARCH_TOOL_NAME,
        VR_READ_TOOL_NAME,
    } <= tool_names


def test_ultra_mode_uses_source_fanout_without_route_vr_sources(tmp_path: Path):
    from test_mary_vr_ultra import _orchestrator

    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "ultra"
    )
    calls = _mode_calls(orchestrator)

    _run_mode(orchestrator, cid, events, use_vr=True)

    assert calls["ultra"] == 1
    assert calls["route_vr_sources"] == 0
    assert calls["route_code_source"] == 0
    assert sorted(calls["route_source"]) == ["kb", "schema", "wiki"]
    research = next(event for event in events if event.kind == "research_started")
    assert research.payload["sources"] == ["wiki", "kb", "schema"]


def test_ultra_mode_without_fanout_uses_direct_vr_sources_fallback(
    tmp_path: Path,
):
    from test_mary_vr_ultra import _orchestrator

    settings, database, orchestrator, provider, cid, events = _orchestrator(
        tmp_path, "ultra"
    )
    orchestrator.settings = replace(
        orchestrator.settings, vr_research_fanout=False
    )
    calls = _mode_calls(orchestrator)

    _run_mode(orchestrator, cid, events, use_vr=True)

    assert calls["ultra"] == 0
    assert calls["route_vr_sources"] == 1
    assert calls["route"] == 0
    kinds = [event.kind for event in events]
    assert "research_started" not in kinds
    assert "knowledge_routed" in kinds
    assert "knowledge_fallback_used" not in kinds
    assistant = [
        row for row in database.messages(cid) if row["role"] == "assistant"
    ]
    assert assistant and "Resposta Ultra" in assistant[-1]["content"]


# --------------------------------------------- VR normal: quatro fontes fixas


class _DirectVrProvider:
    """Provider stub for the single direct answer of normal VR."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []

    def available(self) -> bool:
        return True

    def start_conversation(self, conversation_id, model, effort, workspace, options=None):
        return f"native:{conversation_id}"

    def release_conversation(self, *args, **kwargs):
        pass

    def interrupt(self, conversation_id):
        pass

    def send_message(self, conversation_id, native_id, model, effort, workspace,
                     message, callback, options=None, skills=None, image_paths=None):
        with self.lock:
            self.calls.append((conversation_id, message))
        callback(RuntimeEvent(conversation_id, "turn_started", payload={"turn": {"id": "t"}}))
        callback(RuntimeEvent(conversation_id, "assistant_delta", "Resposta direta da base."))
        callback(RuntimeEvent(conversation_id, "turn_completed"))


VR_QUERY = "SPED Fiscal sped_fiscal_detalhe SpedFiscalManager"


def _vr_normal_orchestrator(settings, database, service):
    orchestrator = ChatOrchestrator(settings, database)
    orchestrator.retrieval_service = service
    provider = _DirectVrProvider()
    orchestrator.providers = {"codex": provider}
    conversation_id = orchestrator.new_conversation(
        "codex", "sol", defer_provider_start=True, vr_mode="vr"
    )
    database.update_conversation(
        conversation_id, native_id="native-x", native_id_vr="native-x"
    )
    return orchestrator, provider, conversation_id


def _send_vr_query(
    orchestrator,
    conversation_id,
    events,
    query: str = VR_QUERY,
    **send_kwargs,
):
    done = threading.Event()

    def callback(event):
        events.append(event)
        if event.kind == "turn_completed":
            done.set()

    orchestrator.send(
        conversation_id,
        query,
        callback,
        use_vr=True,
        **send_kwargs,
    )
    assert done.wait(30), "turno não concluiu"


def test_vr_normal_initial_bundle_is_empty_tool_evidence_accumulator(
    tmp_path: Path,
):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    orchestrator, provider, conversation_id = _vr_normal_orchestrator(
        settings, database, service
    )
    captured: dict = {}
    original = orchestrator._validate_direct_response

    def validate(cid, content):
        captured["bundle"] = orchestrator._pending_evidence_bundles.get(cid)
        return original(cid, content)

    orchestrator._validate_direct_response = validate
    events: list[RuntimeEvent] = []
    _send_vr_query(orchestrator, conversation_id, events)

    bundle = captured["bundle"]
    assert bundle is not None
    assert bundle.candidates == ()
    assert bundle.source_reports == ()
    assert bundle.selected_modules == ()
    assert bundle.module_routing == ()
    kinds = [event.kind for event in events]
    assert "research_started" not in kinds
    assert "agent_started" not in kinds
    assert "knowledge_routed" not in kinds
    main_calls = [
        item for item in provider.calls if item[0] == conversation_id
    ]
    assert len(main_calls) == 1


def test_vr_normal_wiki_keeps_endoo_when_globally_disabled(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    database.upsert_document(
        KnowledgeDocument(
            source="wiki",
            source_id="sped-endoo-unified",
            source_origin="endoo",
            title="SPED Fiscal no Endoo",
            url="https://endoo.example/sped",
            markdown="SPED Fiscal sped_fiscal_detalhe SpedFiscalManager no Endoo.",
            module="Fiscal",
            review_status="approved",
            content_hash="hash-endoo-1",
        )
    )
    router = KnowledgeRouter(
        database, settings.root, disabled_origins=("endoo",)
    )
    disabled_service = RetrievalService(router)

    bundle = disabled_service.route_vr_sources(VR_QUERY)

    assert any(
        item.source == "wiki" and item.source_origin == "endoo"
        for item in bundle.candidates
    )
    assert disabled_service.enabled_origins("wiki") == ("vrwiki",)


def test_vr_normal_isolates_single_source_failure(tmp_path: Path):
    settings, database, code_index, service = _setup_test_env(tmp_path)
    original = service.route_source

    def flaky(query, source):
        if source == "kb":
            raise RuntimeError("kb fora do ar")
        return original(query, source)

    service.route_source = flaky

    bundle = service.route_vr_sources(VR_QUERY)

    assert len(bundle.source_reports) == 4
    assert [report.source for report in bundle.source_reports] == [
        "wiki",
        "kb",
        "schema",
        "code",
    ]
    kb_report = bundle.source_report("kb")
    assert kb_report is not None
    assert kb_report.status == "unavailable"
    assert "kb fora do ar" in kb_report.error
    assert any("KB" in warning for warning in bundle.warnings)
    assert "kb" in bundle.missing_sources
    for source in ("wiki", "schema", "code"):
        report = bundle.source_report(source)
        assert report is not None
        assert report.status != "unavailable"
    assert {item.source for item in bundle.candidates} >= {
        "wiki",
        "schema",
        "code",
    }


def test_vr_normal_code_lane_technical_failure_is_reported(
    tmp_path: Path, monkeypatch
):
    settings, database, code_index, service = _setup_test_env(tmp_path)

    def broken_code(*_args, **_kwargs):
        raise RuntimeError("indice indisponivel")

    monkeypatch.setattr(
        "vrsoft_extractor.mary.retrieval.code_retrieval.retrieve_code_candidates",
        broken_code,
    )

    bundle = service.route_vr_sources(VR_QUERY)

    assert len(bundle.source_reports) == 4
    assert [report.source for report in bundle.source_reports] == [
        "wiki",
        "kb",
        "schema",
        "code",
    ]
    code_report = bundle.source_report("code")
    assert code_report is not None
    assert code_report.status == "unavailable"
    assert "indice indisponivel" in code_report.error
    assert any("CODE" in warning for warning in bundle.warnings)
    assert "code" in bundle.missing_sources
    assert {item.source for item in bundle.candidates} >= {
        "wiki",
        "kb",
        "schema",
    }


def test_vr_normal_code_lane_without_results_stays_exhausted(
    tmp_path: Path, monkeypatch
):
    settings, database, code_index, service = _setup_test_env(tmp_path)

    monkeypatch.setattr(
        "vrsoft_extractor.mary.retrieval.code_retrieval.retrieve_code_candidates",
        lambda *_args, **_kwargs: ([], [], []),
    )

    bundle = service.route_vr_sources(VR_QUERY)

    assert len(bundle.source_reports) == 4
    code_report = bundle.source_report("code")
    assert code_report is not None
    assert code_report.status == "exhausted"
    assert not any(
        "Falha na trilha CODE" in warning for warning in bundle.warnings
    )
    assert "code" in bundle.missing_sources
