from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .downloader import _download_target_bases, _find_existing_download
from .models import VideoItem
from .settings import Settings


@dataclass(frozen=True)
class VideoStorageInfo:
    state: str
    path: Path | None = None
    size_bytes: int = 0

    @property
    def downloaded(self) -> bool:
        return self.path is not None


def inspect_video_storage(
    items: list[VideoItem], settings: Settings
) -> dict[str, VideoStorageInfo]:
    """Return the real on-disk state for each inventory item."""
    target_bases = _download_target_bases(items, settings)
    result: dict[str, VideoStorageInfo] = {}
    for item in items:
        path = _existing_local_path(item, settings)
        if path is None:
            target_base = target_bases.get(item.id)
            if target_base is not None:
                try:
                    path = _find_existing_download(target_base)
                except OSError:
                    path = None
        if path is not None:
            try:
                size = path.stat().st_size
            except OSError:
                path = None
                size = 0
        else:
            size = 0
        if path is not None:
            state = "Baixado"
        elif item.local_path or item.status in {"downloaded", "skipped"}:
            state = "Arquivo ausente"
        else:
            state = "Pendente"
        result[item.id] = VideoStorageInfo(state=state, path=path, size_bytes=size)
    return result


def _existing_local_path(item: VideoItem, settings: Settings) -> Path | None:
    if not item.local_path:
        return None
    path = Path(item.local_path)
    if not path.is_absolute():
        path = settings.project_dir / path
    try:
        path = path.resolve()
        return path if path.is_file() else None
    except OSError:
        return None


def format_byte_size(size_bytes: int) -> str:
    value = float(max(0, size_bytes))
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} B"
    precision = 0 if value >= 100 else 1
    return f"{value:.{precision}f} {unit}".replace(".", ",")
