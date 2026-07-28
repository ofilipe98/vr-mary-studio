from __future__ import annotations

import argparse
import logging
import sys

from .auth import login
from .downloader import download_inventory
from .logging_utils import setup_logging
from .scanner import scan
from .settings import ConfigError, load_settings, sensitive_values

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vrsoft-extractor",
        description="Extrator autenticado de videos VRSoft/Endoo.",
    )
    parser.add_argument("--project-dir", default=".", help="Diretorio do projeto/saidas.")
    parser.add_argument(
        "--base-url",
        default=None,
        help="URL base do portal. Padrao: https://vrsoft.endoo.com.br",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=200,
        help="Limite de paginas por area durante o scan.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Autentica e salva sessao local.")
    login_parser.add_argument("--headless", action="store_true", help="Executa sem abrir janela.")
    login_parser.add_argument("--force", action="store_true", help="Forca novo login.")

    scan_parser = subparsers.add_parser("scan", help="Gera inventario dos videos acessiveis.")
    scan_parser.add_argument("--headed", action="store_true", help="Mostra o navegador durante o scan.")
    scan_parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Salva HTML, screenshot e URLs de paginas sem video em metadata/debug.",
    )

    download_parser = subparsers.add_parser("download", help="Baixa videos do inventario.")
    download_parser.add_argument("--concurrency", type=int, default=2, help="Downloads simultaneos.")
    download_parser.add_argument("--redownload", action="store_true", help="Baixa novamente arquivos existentes.")

    run_parser = subparsers.add_parser("run", help="Executa login, scan e download.")
    run_parser.add_argument("--login-headless", action="store_true", help="Login sem janela.")
    run_parser.add_argument("--headed-scan", action="store_true", help="Mostra navegador durante scan.")
    run_parser.add_argument(
        "--diagnostic-scan",
        action="store_true",
        help="Salva diagnostico das paginas sem video durante o scan.",
    )
    run_parser.add_argument("--concurrency", type=int, default=2, help="Downloads simultaneos.")
    run_parser.add_argument("--redownload", action="store_true", help="Baixa novamente arquivos existentes.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(
        project_dir=args.project_dir,
        base_url=args.base_url,
        max_pages_per_section=args.max_pages,
    )
    log_path = setup_logging(settings.logs_dir, args.command, sensitive_values())
    LOGGER.info("Log: %s", log_path)

    try:
        if args.command == "login":
            login(settings, headless=args.headless, force=args.force)
        elif args.command == "scan":
            scan(settings, headless=not args.headed, diagnostic=args.diagnostic)
        elif args.command == "download":
            download_inventory(
                settings,
                concurrency=args.concurrency,
                redownload=args.redownload,
            )
        elif args.command == "run":
            login(settings, headless=args.login_headless)
            scan(settings, headless=not args.headed_scan, diagnostic=args.diagnostic_scan)
            download_inventory(
                settings,
                concurrency=args.concurrency,
                redownload=args.redownload,
            )
        else:
            parser.error(f"Comando desconhecido: {args.command}")
    except (ConfigError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
