from __future__ import annotations

import argparse
import json
import sys

from .config import load_mary_settings
from .migration import build_manifest, migrate
from .movidesk import MovideskSync
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
    sub.add_parser("status", help="Mostra estatísticas da base")
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
        stats = MovideskSync(settings, database, print).sync(args.headed, args.limit)
        print(json.dumps(stats.to_dict(), ensure_ascii=False))
    elif args.command == "search":
        print(
            json.dumps(
                database.search(args.query, args.limit, args.module, args.source),
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
