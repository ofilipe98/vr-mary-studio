from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MEDIA_EXTENSIONS = (".mp4", ".m4v", ".webm", ".mov")
HLS_EXTENSIONS = (".m3u8",)
EMBED_HOST_PARTS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "player.vimeo.com",
    "wistia.com",
    "wistia.net",
    "panda.video",
    "pandavideo.com",
    "hotmart.com",
    "voe.sx",
    "streamable.com",
)


def sanitize_filename(value: str, fallback: str = "sem-titulo", max_length: int = 120) -> str:
    cleaned = unicodedata.normalize("NFC", value or "")
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned[:max_length].rstrip(" .") or fallback


def media_stem(value: str) -> str:
    """Return a display title without a media extension added by the source."""
    normalized = unicodedata.normalize("NFC", value or "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    suffix = Path(normalized).suffix.lower()
    if suffix in {*MEDIA_EXTENSIONS, ".mkv", ".avi"}:
        normalized = normalized[: -len(suffix)].rstrip(" .")
    return normalized or "video"


def resource_identity(url: str) -> str:
    """Stable URL identity that ignores expiring query strings and fragments."""
    clean, _fragment = urldefrag(url or "")
    parsed = urlparse(clean)
    if not parsed.scheme:
        return clean.rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", "", ""))


def classify_media_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    if path.endswith(HLS_EXTENSIONS):
        return "hls"
    if path.endswith(MEDIA_EXTENSIONS):
        return "mp4"
    if any(part in host for part in EMBED_HOST_PARTS):
        return "embed"
    if "player" in host or "/player" in path or "/embed" in path:
        return "embed"
    return "unknown"


def is_media_url(url: str) -> bool:
    return classify_media_url(url) != "unknown"


def absolutize_url(url: str, base_url: str) -> str:
    return urljoin(base_url, url)


def stable_id(*parts: str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update((part or "").encode("utf-8", errors="ignore"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def is_same_site(url: str, base_url: str) -> bool:
    parsed = urlparse(url)
    base = urlparse(base_url)
    return parsed.scheme in {"http", "https"} and parsed.netloc == base.netloc


def looks_like_html_page(url: str) -> bool:
    path = urlparse(url).path.lower()
    blocked_ext = (
        ".7z",
        ".avi",
        ".css",
        ".csv",
        ".doc",
        ".docx",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".pdf",
        ".png",
        ".rar",
        ".svg",
        ".webm",
        ".xls",
        ".xlsx",
        ".zip",
    )
    return not path.endswith(blocked_ext)


def output_base_path(
    downloads_dir: Path,
    area: str,
    course: str,
    module: str,
    title: str,
    *,
    business_module: str = "",
    folder_path: list[str] | tuple[str, ...] | None = None,
) -> Path:
    area_dir = "Biblioteca" if area == "biblioteca" else "Cursos"
    parts = [downloads_dir, Path(area_dir)]
    if business_module:
        parts.append(Path(sanitize_filename(business_module, "Revisar")))
    hierarchy = [part for part in (folder_path or []) if str(part).strip()]
    if not hierarchy:
        if area != "biblioteca":
            hierarchy.append(course or "Curso")
        elif course:
            hierarchy.append(course)
        if module:
            hierarchy.append(module)
    parts.extend(Path(sanitize_filename(str(part))) for part in hierarchy)
    directory = Path(*parts)
    return directory / sanitize_filename(media_stem(title))
