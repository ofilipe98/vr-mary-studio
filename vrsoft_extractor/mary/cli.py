from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .classification_audit import audit_classification
from .classpath import ClasspathAnalyzer, ClasspathError, ClasspathPolicyStore
from .code_analysis_benchmark import (
    CodeAnalysisBenchmarkError,
    apply_blind_review,
    audit_benchmark_intake,
    benchmark_template,
    build_benchmark_intake_manifest,
    build_blind_review_packet,
    execute_benchmark_suite,
    load_benchmark_intake_manifest,
    load_benchmark_suite,
    preflight_benchmark_suite,
)
from .code_coverage import CodeCoverageError, ErpCodeCoverage
from .code_index import JavaCodeIndex
from .config import load_vr_settings
from .endoo_wiki import EndooWikiSync
from .erp_releases import ErpReleaseCatalog, ErpReleaseError
from .migration import build_manifest, migrate
from .movidesk import MovideskSync
from .portable_export import audit_portable_project, export_portable_project
from .portable_project import ensure_portable_project
from .indexer import export_catalog
from .jvm_batches import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_CLASSES,
    DecompilationBatchError,
    DecompilationBatchExecutor,
    DecompilationBatchPlanner,
    DecompilationBatchStore,
)
from .jvm_toolchain import JvmToolchain
from .wiki import WikiSync
from .schema_sync import SchemaSync
from .workspace import initialize_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vr-studio", description="VR Norte Studio")
    parser.add_argument("--app-dir", default=".", help="Pasta do aplicativo e .env")
    parser.add_argument("--root", default=None, help="Raiz da base VR")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Cria a estrutura e o banco local")
    migrate_parser = sub.add_parser("migrate", help="Migra conteúdo funcional permitido")
    migrate_parser.add_argument("--dry-run", action="store_true")
    wiki = sub.add_parser("sync-wiki", help="Sincroniza a VRWiki")
    wiki.add_argument("--limit", type=int)
    endoo_wiki = sub.add_parser(
        "sync-endoo-wiki", help="Sincroniza a Wiki autenticada do Endoo"
    )
    endoo_wiki.add_argument("--limit", type=int)
    endoo_wiki.add_argument(
        "--headed", action="store_true", help="Abre o login Endoo antes de sincronizar"
    )
    all_wikis = sub.add_parser(
        "sync-wikis", help="Sincroniza VRWiki e Wiki Endoo"
    )
    all_wikis.add_argument("--limit", type=int)
    all_wikis.add_argument("--headed-endoo", action="store_true")
    kb = sub.add_parser("sync-kb", help="Sincroniza o Movidesk KB")
    kb.add_argument("--limit", type=int)
    kb.add_argument("--headed", action="store_true")
    sub.add_parser("sync-schema", help="Indexa tabelas e relações do SchemaVR local")
    reindex = sub.add_parser(
        "reindex-knowledge",
        help="Gera chunks pesquisáveis para documentos existentes",
    )
    reindex.add_argument("--limit", type=int, default=0)
    search = sub.add_parser("search", help="Pesquisa o índice local")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--module", default="")
    search.add_argument("--source", default="")
    search.add_argument("--origin", default="")
    audit = sub.add_parser(
        "audit-classification",
        help="Simula a classificação atual sem alterar documentos",
    )
    audit.add_argument("--limit", type=int)
    audit.add_argument(
        "--examples",
        type=int,
        default=25,
        help="Quantidade máxima de exemplos divergentes",
    )
    audit.add_argument(
        "--queue-review",
        action="store_true",
        help="Atualiza a fila de revisão sem alterar o módulo atual",
    )
    sub.add_parser("status", help="Mostra estatísticas da base")
    sub.add_parser(
        "prepare-codex",
        help="Prepara a base atual para ser aberta diretamente no Codex",
    )
    portable = sub.add_parser(
        "export-portable",
        help="Exporta um projeto VR sem credenciais nem vídeos completos",
    )
    portable.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        help="Fonte documental que nao deve entrar no pacote (opcao repetivel)",
    )
    portable.add_argument(
        "--include-endoo",
        action="store_true",
        help="Inclui explicitamente o conteudo autenticado da Wiki Endoo",
    )
    portable.add_argument("destination")
    sub.add_parser(
        "audit-portable",
        help="Verifica caminhos absolutos e arquivos sensíveis no projeto VR",
    )
    erp_import = sub.add_parser(
        "import-erp-release",
        help="Inventaria e registra os JARs de uma release do ERP",
    )
    erp_import.add_argument("release_id")
    erp_import.add_argument(
        "--path",
        default=None,
        help="Pasta dos JARs; padrão: ERP/releases/<release>/jars",
    )
    erp_import.add_argument("--expected-jars", type=int, default=46)
    erp_status = sub.add_parser(
        "status-erp-release",
        help="Verifica o frescor de uma ou de todas as releases indexadas",
    )
    erp_status.add_argument("release_id", nargs="?", default="")
    erp_status.add_argument(
        "--full-hash",
        action="store_true",
        help="Recalcula SHA-256 de todos os JARs em vez da verificação rápida",
    )
    erp_classes = sub.add_parser(
        "inspect-erp-classes",
        help="Mede bytecode e duplicidades antes da decompilação",
    )
    erp_classes.add_argument("release_id")
    erp_classes.add_argument(
        "--jar",
        action="append",
        default=[],
        help="Caminho relativo de um JAR; pode ser repetido. Sem opção, usa todos.",
    )
    classpath_inspect = sub.add_parser(
        "inspect-erp-classpath",
        help="Indexa duplicatas e a variante efetiva selecionada pelo runtime Java",
    )
    classpath_inspect.add_argument("release_id")
    classpath_inspect.add_argument("--jar", action="append", default=[])
    classpath_status = sub.add_parser(
        "status-erp-classpath",
        help="Mostra análise, perfis e estado de resolução do classpath",
    )
    classpath_status.add_argument("release_id")
    classpath_status.add_argument("--profile", default="")
    classpath_set = sub.add_parser(
        "set-erp-classpath",
        help="Grava uma ordem de JARs explícita para um perfil da release",
    )
    classpath_set.add_argument("release_id")
    classpath_set.add_argument("profile_id")
    classpath_set.add_argument(
        "--jar",
        action="append",
        default=[],
        help="JAR na ordem do classpath; repita na ordem efetiva",
    )
    classpath_set.add_argument(
        "--complete",
        action="store_true",
        help="Declara que a ordem informada representa o classpath completo do perfil",
    )
    classpath_set.add_argument(
        "--approve",
        action="store_true",
        help="Confirma explicitamente a gravação da política",
    )
    erp_remove = sub.add_parser(
        "remove-erp-release-index",
        help="Remove apenas o índice gerado de uma release",
    )
    erp_remove.add_argument("release_id")
    erp_remove.add_argument(
        "--approve",
        action="store_true",
        help="Confirma explicitamente a remoção do índice regenerável",
    )
    sub.add_parser(
        "doctor-code-analysis",
        help="Verifica Java 17 isolado, Vineflower e CFR sem alterar o sistema",
    )
    batch_plan = sub.add_parser(
        "plan-erp-decompilation",
        help="Planeja lotes determinísticos e retomáveis para decompilar uma release",
    )
    batch_plan.add_argument("release_id")
    batch_plan.add_argument(
        "--jar",
        action="append",
        default=[],
        help="Caminho relativo de um JAR; pode ser repetido. Sem opção, usa todos.",
    )
    batch_plan.add_argument("--max-classes", type=int, default=DEFAULT_MAX_CLASSES)
    batch_plan.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    batch_run = sub.add_parser(
        "run-erp-decompilation",
        help="Executa serialmente os próximos lotes pendentes de um plano",
    )
    batch_run.add_argument("plan_id")
    batch_run.add_argument("--limit", type=int, default=1)
    batch_run.add_argument("--heap-mb", type=int, default=2048)
    batch_run.add_argument("--timeout", type=int, default=300)
    batch_status = sub.add_parser(
        "status-erp-decompilation",
        help="Mostra o progresso de um ou de todos os planos de decompilação",
    )
    batch_status.add_argument("plan_id", nargs="?", default="")
    batch_retry = sub.add_parser(
        "retry-erp-decompilation",
        help="Reenfileira explicitamente um lote com falha ou saída parcial",
    )
    batch_retry.add_argument("batch_id")
    code_index = sub.add_parser(
        "index-erp-code",
        help="Indexa fontes Java aprovados de um plano de decompilação",
    )
    code_index.add_argument("plan_id")
    code_search = sub.add_parser(
        "search-erp-code",
        help="Pesquisa classes, símbolos, relações e conteúdo Java indexado",
    )
    code_search.add_argument("query")
    code_search.add_argument("--release", default="")
    code_search.add_argument("--profile", default="")
    code_search.add_argument("--limit", type=int, default=10)
    code_status = sub.add_parser(
        "status-erp-code",
        help="Mostra cobertura do índice pesquisável de código",
    )
    code_status.add_argument("release_id", nargs="?", default="")
    coverage_status = sub.add_parser(
        "status-erp-code-coverage",
        help="Mostra progresso e capacidade para cobrir os JARs de uma release",
    )
    coverage_status.add_argument("release_id")
    coverage_advance = sub.add_parser(
        "advance-erp-code-coverage",
        help="Planeja, decompila e indexa incrementalmente os próximos JARs",
    )
    coverage_advance.add_argument("release_id")
    coverage_advance.add_argument("--jar", action="append", default=[])
    coverage_advance.add_argument("--jars-per-plan", type=int, default=1)
    coverage_advance.add_argument("--limit", type=int, default=1)
    coverage_advance.add_argument("--max-classes", type=int, default=DEFAULT_MAX_CLASSES)
    coverage_advance.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    coverage_advance.add_argument("--heap-mb", type=int, default=2048)
    coverage_advance.add_argument("--timeout", type=int, default=300)
    coverage_advance.add_argument(
        "--approve-processing",
        action="store_true",
        help="Confirma consumo de CPU, disco e execução dos decompiladores",
    )
    code_callers = sub.add_parser(
        "callers-erp-code",
        help="Lista chamadas sintáticas a um método ou construtor indexado",
    )
    code_callers.add_argument("target")
    code_callers.add_argument("--release", default="")
    code_callers.add_argument("--profile", default="")
    code_callers.add_argument("--limit", type=int, default=50)
    benchmark_template_parser = sub.add_parser(
        "benchmark-code-analysis-template",
        help="Mostra o modelo JSON para casos anonimizados de análise de código",
    )
    benchmark_template_parser.add_argument(
        "--output",
        default="",
        help="Grava o modelo em UTF-8 sem sobrescrever um arquivo existente",
    )
    benchmark = sub.add_parser(
        "benchmark-code-analysis",
        help="Executa casos VR Ultra pareados com o Agente de Código off/on",
    )
    benchmark.add_argument("cases", help="Arquivo JSON com chamados anonimizados")
    benchmark.add_argument("--provider", default="codex")
    benchmark.add_argument("--model", default="")
    benchmark.add_argument("--effort", default="medium")
    benchmark.add_argument("--timeout", type=int, default=600)
    benchmark.add_argument("--max-cases", type=int, default=0)
    benchmark.add_argument(
        "--intake-manifest",
        default="",
        help="Manifesto congelado da suíte anonimizada",
    )
    benchmark.add_argument(
        "--approve-model-usage",
        action="store_true",
        help="Confirma o custo de duas execuções VR Ultra por caso",
    )
    benchmark_preflight = sub.add_parser(
        "preflight-code-analysis",
        help="Valida casos, cobertura e símbolos sem chamar modelos",
    )
    benchmark_preflight.add_argument("cases")
    benchmark_preflight.add_argument("--intake-manifest", default="")
    intake_audit = sub.add_parser(
        "audit-code-analysis-cases",
        help="Audita seleção, evidência e dados sensíveis sem chamar modelos",
    )
    intake_audit.add_argument("cases")
    intake_freeze = sub.add_parser(
        "freeze-code-analysis-cases",
        help="Congela uma suíte aprovada em manifesto SHA-256",
    )
    intake_freeze.add_argument("cases")
    intake_freeze.add_argument("--output", required=True)
    review_prepare = sub.add_parser(
        "prepare-code-analysis-review",
        help="Cria pacote cego A/B e chave separada a partir de um benchmark",
    )
    review_prepare.add_argument("report")
    review_prepare.add_argument("--output", required=True)
    review_prepare.add_argument("--key-output", required=True)
    review_finalize = sub.add_parser(
        "finalize-code-analysis-review",
        help="Aplica notas A/B usando a chave e consolida a revisão humana",
    )
    review_finalize.add_argument("report")
    review_finalize.add_argument("review")
    review_finalize.add_argument("key")
    review_finalize.add_argument("--output", required=True)
    return parser


def _read_json_object(path: str | Path, label: str) -> dict[str, object]:
    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodeAnalysisBenchmarkError(
            f"Não foi possível ler {label}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise CodeAnalysisBenchmarkError(f"{label} precisa ser um objeto JSON.")
    return payload


def _write_new_json(path: str | Path, payload: dict[str, object]) -> Path:
    output = Path(path).resolve()
    if output.exists():
        raise CodeAnalysisBenchmarkError(f"O arquivo já existe: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "benchmark-code-analysis-template":
        rendered = json.dumps(benchmark_template(), ensure_ascii=False, indent=2)
        if args.output:
            output = Path(args.output).resolve()
            if output.exists():
                print(
                    json.dumps(
                        {"error": f"O arquivo já existe: {output}"},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 2
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + "\n", encoding="utf-8")
            except OSError as exc:
                print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
                return 2
            print(json.dumps({"output": str(output)}, ensure_ascii=False, indent=2))
        else:
            print(rendered)
        return 0
    if args.command == "audit-code-analysis-cases":
        try:
            suite = load_benchmark_suite(args.cases)
            audit = audit_benchmark_intake(suite)
        except CodeAnalysisBenchmarkError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0 if audit["ready"] else 2
    if args.command == "freeze-code-analysis-cases":
        try:
            suite = load_benchmark_suite(args.cases)
            manifest = build_benchmark_intake_manifest(suite)
            output = _write_new_json(args.output, manifest)
        except (CodeAnalysisBenchmarkError, OSError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(
            json.dumps(
                {
                    "output": str(output),
                    "suite_fingerprint": manifest["suite_fingerprint"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "prepare-code-analysis-review":
        try:
            report = _read_json_object(args.report, "o relatório")
            packet, key = build_blind_review_packet(report)
            output = Path(args.output).resolve()
            key_output = Path(args.key_output).resolve()
            if output == key_output:
                raise CodeAnalysisBenchmarkError(
                    "Pacote e chave precisam ser gravados em arquivos diferentes."
                )
            if output.exists() or key_output.exists():
                existing = output if output.exists() else key_output
                raise CodeAnalysisBenchmarkError(f"O arquivo já existe: {existing}")
            written_packet = _write_new_json(output, packet)
            written_key = _write_new_json(key_output, key)
        except (CodeAnalysisBenchmarkError, OSError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(
            json.dumps(
                {"review": str(written_packet), "key": str(written_key)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "finalize-code-analysis-review":
        try:
            report = _read_json_object(args.report, "o relatório")
            packet = _read_json_object(args.review, "o pacote de revisão")
            key = _read_json_object(args.key, "a chave de revisão")
            reviewed = apply_blind_review(report, packet, key)
            output = _write_new_json(args.output, reviewed)
        except (CodeAnalysisBenchmarkError, OSError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps({"output": str(output)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "benchmark-code-analysis" and not args.approve_model_usage:
        print(
            json.dumps(
                {
                    "error": (
                        "O benchmark faz duas execuções VR Ultra por caso. "
                        "Repita com --approve-model-usage após revisar custo e dados."
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    if args.command == "advance-erp-code-coverage" and not args.approve_processing:
        print(
            json.dumps(
                {
                    "error": (
                        "O avanço executa decompiladores e grava o índice. Repita com "
                        "--approve-processing após revisar capacidade e release."
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    settings = load_vr_settings(args.app_dir, args.root)
    database = initialize_workspace(settings)
    if args.command == "init":
        print(settings.root)
    elif args.command == "migrate":
        if args.dry_run:
            print(
                json.dumps(
                    [item.__dict__ for item in build_manifest(settings)],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(migrate(settings), ensure_ascii=False))
    elif args.command == "sync-wiki":
        stats = WikiSync(settings, database, print).sync(args.limit)
        print(json.dumps(stats.to_dict(), ensure_ascii=False))
    elif args.command == "sync-endoo-wiki":
        sync = EndooWikiSync(settings, database, print)
        if args.headed:
            sync.login()
        stats = sync.sync(args.limit)
        print(json.dumps(stats.to_dict(), ensure_ascii=False))
    elif args.command == "sync-wikis":
        public_stats = WikiSync(settings, database, print).sync(args.limit)
        sync = EndooWikiSync(settings, database, print)
        if args.headed_endoo:
            sync.login()
        endoo_stats = sync.sync(args.limit)
        print(
            json.dumps(
                {
                    "vrwiki": public_stats.to_dict(),
                    "endoo": endoo_stats.to_dict(),
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "sync-kb":
        sync = MovideskSync(settings, database, print)
        if args.headed:
            sync.login()
        stats = sync.sync(False, args.limit)
        print(json.dumps(stats.to_dict(), ensure_ascii=False))
    elif args.command == "sync-schema":
        stats = SchemaSync(settings, database, print).sync()
        print(json.dumps(stats.to_dict(), ensure_ascii=False))
    elif args.command == "reindex-knowledge":
        print(json.dumps({"documents": database.backfill_knowledge_chunks(args.limit)}))
    elif args.command == "search":
        print(
            json.dumps(
                database.search(
                    args.query,
                    args.limit,
                    args.module,
                    args.source,
                    source_origin=args.origin,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "audit-classification":
        print(
            json.dumps(
                audit_classification(
                    database,
                    args.limit,
                    args.examples,
                    args.queue_review,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "status":
        with database.connect() as connection:
            counts = connection.execute(
                """SELECT module,source,source_origin,status,count(*) AS total
                   FROM documents
                   GROUP BY module,source,source_origin,status
                   ORDER BY module,source,source_origin,status"""
            ).fetchall()
            reviews = connection.execute(
                "SELECT count(*) FROM classification_reviews WHERE status='pending'"
            ).fetchone()[0]
        print(
            json.dumps(
                {
                    "root": str(settings.root),
                    "documents": [dict(row) for row in counts],
                    "reviews": reviews,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "prepare-codex":
        result = ensure_portable_project(settings.root)
        export_catalog(database, settings.index_dir)
        print(
            json.dumps(
                {
                    "root": str(result.root),
                    "written": result.written,
                    "preserved": result.preserved,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "export-portable":
        result = export_portable_project(
            settings.root,
            Path(args.destination),
            exclude_sources=args.exclude_source,
            exclude_origins=() if args.include_endoo else ("endoo",),
        )
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, default=str))
    elif args.command == "audit-portable":
        result = audit_portable_project(settings.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 2
    elif args.command == "import-erp-release":
        catalog = ErpReleaseCatalog(settings.root, args.expected_jars)
        try:
            result = catalog.import_release(args.release_id, args.path)
        except ErpReleaseError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["state"] == "ready" else 2
    elif args.command == "status-erp-release":
        catalog = ErpReleaseCatalog(settings.root)
        try:
            result = (
                catalog.status(args.release_id, full_hash=args.full_hash)
                if args.release_id
                else catalog.list_statuses(full_hash=args.full_hash)
            )
        except ErpReleaseError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict):
            return 0 if (
                result.get("state") == "ready"
                and result.get("freshness") == "fresh"
            ) else 2
        return 0 if all(
            item.get("state") == "ready" and item.get("freshness") == "fresh"
            for item in result
        ) else 2
    elif args.command == "inspect-erp-classes":
        catalog = ErpReleaseCatalog(settings.root)
        try:
            result = catalog.inspect_class_metrics(args.release_id, args.jar)
        except ErpReleaseError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["errors"] else 2
    elif args.command == "inspect-erp-classpath":
        try:
            result = ClasspathAnalyzer(settings.root).analyze(
                args.release_id, args.jar
            )
        except (ClasspathError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["errors"] else 2
    elif args.command == "status-erp-classpath":
        try:
            result = ClasspathPolicyStore(settings.root).status(
                args.release_id, args.profile
            )
        except (ClasspathError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "set-erp-classpath":
        try:
            result = ClasspathPolicyStore(settings.root).set_profile(
                args.release_id,
                args.profile_id,
                args.jar,
                complete=args.complete,
                approved=args.approve,
            )
        except (ClasspathError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "remove-erp-release-index":
        catalog = ErpReleaseCatalog(settings.root)
        try:
            result = catalog.remove_index(args.release_id, approved=args.approve)
        except ErpReleaseError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "doctor-code-analysis":
        result = JvmToolchain(settings.root).doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 2
    elif args.command == "plan-erp-decompilation":
        try:
            result = DecompilationBatchPlanner(settings.root).plan(
                args.release_id,
                args.jar,
                max_classes=args.max_classes,
                max_bytes=args.max_bytes,
            )
        except (DecompilationBatchError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "run-erp-decompilation":
        try:
            result = DecompilationBatchExecutor(settings.root).run(
                args.plan_id,
                limit=args.limit,
                max_heap_mb=args.heap_mb,
                timeout_seconds=args.timeout,
            )
        except (DecompilationBatchError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if all(
            item.get("state") == "completed" for item in result["executed"]
        ) else 2
    elif args.command == "status-erp-decompilation":
        try:
            result = DecompilationBatchStore(settings.root).status(args.plan_id)
        except DecompilationBatchError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "retry-erp-decompilation":
        try:
            result = DecompilationBatchExecutor(settings.root).retry(args.batch_id)
        except DecompilationBatchError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "index-erp-code":
        try:
            result = JavaCodeIndex(settings.root).index_plan(args.plan_id)
        except (DecompilationBatchError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["errors"] else 2
    elif args.command == "search-erp-code":
        try:
            result = JavaCodeIndex(settings.root).search(
                args.query,
                release_id=args.release,
                classpath_profile=args.profile,
                limit=args.limit,
            )
        except (ClasspathError, DecompilationBatchError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "status-erp-code":
        result = JavaCodeIndex(settings.root).status(args.release_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "status-erp-code-coverage":
        try:
            result = ErpCodeCoverage(settings.root).status(args.release_id)
        except (CodeCoverageError, DecompilationBatchError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "advance-erp-code-coverage":
        try:
            result = ErpCodeCoverage(settings.root).advance(
                args.release_id,
                approved=args.approve_processing,
                relative_jars=args.jar,
                jars_per_plan=args.jars_per_plan,
                batch_limit=args.limit,
                max_classes=args.max_classes,
                max_bytes=args.max_bytes,
                max_heap_mb=args.heap_mb,
                timeout_seconds=args.timeout,
            )
        except (CodeCoverageError, DecompilationBatchError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if all(
            item.get("state") == "completed" for item in result["executed"]
        ) else 2
    elif args.command == "callers-erp-code":
        try:
            result = JavaCodeIndex(settings.root).callers(
                args.target,
                release_id=args.release,
                classpath_profile=args.profile,
                limit=args.limit,
            )
        except (ClasspathError, DecompilationBatchError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "preflight-code-analysis":
        try:
            suite = load_benchmark_suite(args.cases)
            intake_manifest = (
                load_benchmark_intake_manifest(args.intake_manifest)
                if args.intake_manifest
                else None
            )
            result = preflight_benchmark_suite(
                suite, settings.root, intake_manifest=intake_manifest
            )
        except (CodeAnalysisBenchmarkError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 2
    elif args.command == "benchmark-code-analysis":
        try:
            result = execute_benchmark_suite(
                settings,
                database,
                args.cases,
                provider=args.provider,
                model=args.model,
                effort=args.effort,
                timeout_seconds=args.timeout,
                max_cases=args.max_cases,
                intake_manifest_path=args.intake_manifest or None,
            )
        except (CodeAnalysisBenchmarkError, ErpReleaseError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(
            json.dumps(
                {
                    "benchmark_id": result["benchmark_id"],
                    "suite_id": result["suite_id"],
                    "release_id": result["release_id"],
                    "case_count": result["case_count"],
                    "summary": result["summary"],
                    "report_path": result["report_path"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
