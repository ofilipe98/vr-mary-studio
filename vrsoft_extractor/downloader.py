from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .cookies import write_netscape_cookie_file
from .inventory import load_inventory, save_inventory
from .models import VideoItem
from .runtime import find_ffmpeg
from .settings import ConfigError, Settings, ensure_runtime_dirs
from .utils import output_base_path

LOGGER = logging.getLogger(__name__)


PROTECTED_ERROR_TERMS = (
    "drm",
    "encrypted",
    "unsupported url",
    "private video",
    "forbidden",
    "403",
    "401",
)


def download_inventory(
    settings: Settings,
    *,
    concurrency: int = 2,
    redownload: bool = False,
) -> list[VideoItem]:
    ensure_runtime_dirs(settings)
    inventory_exists = settings.inventory_json_path.exists()
    items = load_inventory(settings.inventory_json_path)
    if not items:
        if inventory_exists:
            raise ConfigError(
                f"Inventario vazio em {settings.inventory_json_path}. Execute Scan ou Diagnostico Scan primeiro."
            )
        raise ConfigError(
            f"Nenhum inventario encontrado em {settings.inventory_json_path}. Execute scan primeiro."
        )
    if settings.storage_state_path.exists():
        write_netscape_cookie_file(settings.storage_state_path, settings.cookiefile_path)

    candidates = [
        item
        for item in items
        if item.media_url and item.status not in {"downloaded", "protected"}
    ]
    if not candidates:
        LOGGER.info("Nenhum video pendente para baixar")
        return items

    by_id = {item.id: item for item in items}
    target_bases = _download_target_bases(items, settings)
    workers = max(1, int(concurrency))
    LOGGER.info("Baixando %s videos com concorrencia %s", len(candidates), workers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_one,
                item,
                settings,
                redownload,
                target_bases.get(item.id),
            ): item.id
            for item in candidates
        }
        for future in as_completed(futures):
            item_id = futures[future]
            try:
                by_id[item_id] = future.result()
            except Exception as exc:
                failed = by_id[item_id]
                failed.status = "failed"
                failed.error = str(exc)
                by_id[item_id] = failed
                LOGGER.exception("Falha inesperada ao baixar %s: %s", failed.lesson_title, exc)

    updated = list(by_id.values())
    save_inventory(updated, settings.inventory_json_path, settings.inventory_csv_path)
    return updated


def _download_one(
    item: VideoItem,
    settings: Settings,
    redownload: bool,
    target_base: Path | None = None,
) -> VideoItem:
    try:
        import yt_dlp
    except ImportError as exc:
        raise ConfigError("yt-dlp nao esta instalado. Execute: python -m pip install -e .") from exc

    target_base = target_base or _base_path_for_item(item, settings)
    target_base.parent.mkdir(parents=True, exist_ok=True)

    if not redownload:
        existing = _find_existing_download(target_base)
        if existing:
            item.status = "skipped"
            item.local_path = str(existing)
            item.error = ""
            LOGGER.info("Ja existe, pulando: %s", existing)
            return item

    outtmpl = str(target_base) + ".%(ext)s"
    options = {
        "outtmpl": {"default": outtmpl},
        "noplaylist": True,
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "http_headers": {
            "Referer": item.page_url,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
        },
    }
    if settings.cookiefile_path.exists():
        options["cookiefile"] = str(settings.cookiefile_path)
    ffmpeg_location = find_ffmpeg()
    if ffmpeg_location:
        options["ffmpeg_location"] = ffmpeg_location

    LOGGER.info("Baixando: %s", item.lesson_title)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(item.media_url, download=True)
            downloaded_path = _extract_downloaded_path(info, ydl)
    except Exception as exc:
        message = str(exc)
        item.status = "protected" if _looks_protected(message) else "failed"
        item.error = message
        LOGGER.warning("Falha ao baixar %s: %s", item.lesson_title, message)
        return item

    item.status = "downloaded"
    item.local_path = str(downloaded_path) if downloaded_path else str(target_base)
    item.error = ""
    return item


def _find_existing_download(target_base: Path) -> Path | None:
    ignored_suffixes = {".part", ".ytdl", ".json", ".description", ".srt", ".vtt"}
    for path in target_base.parent.glob(target_base.name + ".*"):
        if path.suffix.lower() not in ignored_suffixes and path.is_file():
            return path
    return None


def _extract_downloaded_path(info: dict | None, ydl) -> Path | None:
    if not info:
        return None
    requested = info.get("requested_downloads") or []
    for row in requested:
        filepath = row.get("filepath")
        if filepath:
            return Path(filepath)
    try:
        return Path(ydl.prepare_filename(info))
    except Exception:
        return None


def _looks_protected(message: str) -> bool:
    lower = message.lower()
    return any(term in lower for term in PROTECTED_ERROR_TERMS)


def organize_downloads(settings: Settings) -> dict[str, int]:
    """Move known downloads into the classified hierarchy without overwriting."""
    items = load_inventory(settings.inventory_json_path)
    downloads_root = settings.downloads_dir.resolve()
    moved = 0
    collisions = 0
    missing = 0
    unchanged = 0
    target_bases = _download_target_bases(items, settings)
    for item in items:
        if item.status not in {"downloaded", "skipped"} or not item.local_path:
            continue
        source = Path(item.local_path)
        if not source.is_absolute():
            source = settings.project_dir / source
        try:
            source = source.resolve()
        except OSError:
            missing += 1
            continue
        if not source.exists() or not source.is_file():
            missing += 1
            continue
        if not source.is_relative_to(downloads_root):
            LOGGER.warning("Arquivo fora de downloads preservado: %s", source)
            unchanged += 1
            continue
        target_base = target_bases.get(item.id) or _base_path_for_item(item, settings)
        target = target_base.with_suffix(source.suffix).resolve()
        if not target.is_relative_to(downloads_root):
            LOGGER.warning("Destino inseguro rejeitado: %s", target)
            unchanged += 1
            continue
        if target == source:
            unchanged += 1
            continue
        if target.exists():
            collisions += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        item.local_path = str(target)
        moved += 1
    save_inventory(items, settings.inventory_json_path, settings.inventory_csv_path)
    return {
        "moved": moved,
        "collisions": collisions,
        "missing": missing,
        "unchanged": unchanged,
    }


def _base_path_for_item(item: VideoItem, settings: Settings) -> Path:
    return output_base_path(
        settings.downloads_dir,
        item.area,
        item.course,
        item.module,
        item.lesson_title,
        business_module=item.business_module or "Revisar",
        folder_path=item.folder_path,
    )


def _download_target_bases(
    items: list[VideoItem], settings: Settings
) -> dict[str, Path]:
    grouped: dict[str, list[tuple[VideoItem, Path]]] = {}
    for item in items:
        base = _base_path_for_item(item, settings)
        grouped.setdefault(str(base).casefold(), []).append((item, base))
    result: dict[str, Path] = {}
    for group in grouped.values():
        ordered = sorted(
            group,
            key=lambda pair: (
                pair[0].source_order,
                pair[0].source_task_id,
                pair[0].source_file_id,
                pair[0].id,
            ),
        )
        for index, (item, base) in enumerate(ordered):
            if index == 0:
                result[item.id] = base
                continue
            identifier = (
                item.source_task_id
                or item.source_file_id
                or item.id[:8]
                or str(index + 1)
            )
            result[item.id] = base.with_name(f"{base.name} - {identifier}")
    return result
