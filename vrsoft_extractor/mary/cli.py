from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .classification_audit import audit_classification
from .config import load_mary_settings
from .migration import build_manifest, migrate
from .movidesk import MovideskSync
from .portable_export import audit_portable_project, export_portable_project
from .portable_project import ensure_portable_project
from .indexer import export_catalog
from .wiki import WikiSync
from .workspace import initialize_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vr-mary", description="VR Mary Studio")
    parser.add_argument("--app-dir", default=".", help="Pasta do aplicativo e .env")
    parser.add_argument("--root", default=None, help="Raiz da base VR_Mary_V2")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Cria a estrutura e o banco local")
    migrate_parser = sub.add_parser("migrate", help="Migra conteúdo funcional permitido")
    migrate_parser.add_argument("--dry-run", action="store_true")
    wiki = sub.add_parser("sync-wiki", help="Sincroniza a VRWiki")
    wiki.add_argument("--limit", type=int)
    kb = sub.add_parser("sync-kb", help="Sincroniza o Movidesk KB")
    kb.add_argument("--limit", type=int)
    kb.add_argument("--headed", action="store_true")
    search = sub.add_parser("search", help="Pesquisa o índice local")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--module", default="")
    search.add_argument("--source", default="")
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
        help="Exporta um projeto Mary sem credenciais nem vídeos completos",
    )
    portable.add_argument("destination")
    sub.add_parser(
        "audit-portable",
        help="Verifica caminhos absolutos e arquivos sensíveis no projeto Mary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_mary_settings(args.app_dir, args.root)
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
    elif args.command == "sync-kb":
        sync = MovideskSync(settings, database, print)
        if args.headed:
            sync.login()
        stats = sync.sync(False, args.limit)
        print(json.dumps(stats.to_dict(), ensure_ascii=False))
    elif args.command == "search":
        print(
            json.dumps(
                database.search(args.query, args.limit, args.module, args.source),
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
                """SELECT module,source,status,count(*) AS total FROM documents
                   GROUP BY module,source,status ORDER BY module,source,status"""
            ).fetchall()
            reviews = connection.execute(
                "SELECT count(*) FROM classification_reviews WHERE status='pending'"
            ).fetchone()[0]
        print(
            json.dumps(
                {"root": str(settings.root), "documents": [dict(row) for row in counts], "reviews": reviews},
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
        result = export_portable_project(settings.root, Path(args.destination))
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, default=str))
    elif args.command == "audit-portable":
        result = audit_portable_project(settings.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
