from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse


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
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned[:max_length].rstrip(" .") or fallback


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


def output_base_path(downloads_dir: Path, area: str, course: str, module: str, title: str) -> Path:
    area_dir = "Biblioteca" if area == "biblioteca" else "Cursos"
    parts = [downloads_dir, Path(area_dir)]
    if area != "biblioteca":
        parts.append(Path(sanitize_filename(course or "Curso")))
    elif course:
        parts.append(Path(sanitize_filename(course)))
    if module:
        parts.append(Path(sanitize_filename(module)))
    directory = Path(*parts)
    return directory / sanitize_filename(title or "video")
