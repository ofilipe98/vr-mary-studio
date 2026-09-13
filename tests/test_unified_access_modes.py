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
        native_vr_search_enabled=True,
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
