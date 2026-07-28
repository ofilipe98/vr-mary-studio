from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup
from markdownify import markdownify

from .models import KnowledgeDocument


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def safe_slug(value: str, fallback: str = "documento", max_length: int = 100) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_text).strip("-._").lower()
    return (slug or fallback)[:max_length].rstrip("-._")


def html_to_markdown(html: str, base_url: str = "") -> tuple[str, list[str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    for element in soup.select("script, style, noscript, iframe, form, button"):
        element.decompose()
    for anchor in soup.find_all("a", href=True):
        anchor["href"] = urllib.parse.urljoin(base_url, anchor["href"])
    image_urls: list[str] = []
    for image in soup.find_all("img", src=True):
        absolute = urllib.parse.urljoin(base_url, image["src"])
        image["src"] = absolute
        image_urls.append(absolute)
    markdown = markdownify(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=["span"],
    )
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return markdown, list(dict.fromkeys(image_urls))


def download_asset(
    url: str,
    destination_dir: Path,
    *,
    opener: Callable[[str], bytes] | None = None,
) -> Path:
    fetch = opener or _download_bytes
    data = fetch(url)
    digest = sha256_bytes(data)
    path_part = urllib.parse.urlsplit(url).path
    extension = Path(path_part).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,6}", extension):
        content_type = mimetypes.guess_type(path_part)[0] or ""
        extension = mimetypes.guess_extension(content_type) or ".bin"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{digest}{extension}"
    if not destination.exists():
        destination.write_bytes(data)
    return destination


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "VR-Mary-Studio/0.2 (+knowledge-sync)"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def replace_asset_urls(markdown: str, replacements: dict[str, str]) -> str:
    for remote, local in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        markdown = markdown.replace(remote, local.replace("\\", "/"))
    return markdown


def canonical_markdown(document: KnowledgeDocument) -> str:
    front_matter = {
        "source": document.source,
        "source_id": document.source_id,
        "title": document.title,
        "url": _strip_sensitive_query(document.url),
        "module": document.module,
        "classification_confidence": round(document.classification_confidence, 4),
        "review_status": document.review_status,
        "status": document.status,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "synced_at": document.synced_at,
        "revision": document.revision,
        "content_hash": document.content_hash,
        "category": document.category,
        "product": document.product,
        "assets": document.assets,
    }
    yaml_lines = ["---"]
    for key, value in front_matter.items():
        if isinstance(value, list):
            yaml_lines.append(f"{key}:")
            yaml_lines.extend(f'  - "{item}"' for item in value)
        elif isinstance(value, (float, int)):
            yaml_lines.append(f"{key}: {value}")
        else:
            yaml_lines.append(
                f"{key}: {json.dumps(str(value), ensure_ascii=False)}"
            )
    yaml_lines.append("---")
    body = document.markdown.strip()
    if document.ocr_text.strip():
        body += (
            "\n\n## Texto reconhecido nas imagens\n\n"
            "> Conteúdo gerado automaticamente por OCR; valide na imagem original.\n\n"
            + document.ocr_text.strip()
        )
    body += (
        "\n\n## Procedência\n\n"
        f"- Fonte: {document.source.upper()}\n"
        f"- URL: {_strip_sensitive_query(document.url)}\n"
        f"- Sincronizado em: {document.synced_at}\n"
    )
    return "\n".join(yaml_lines) + "\n\n" + body.strip() + "\n"


def target_path(root: Path, document: KnowledgeDocument) -> Path:
    source_folder = "Wiki" if document.source == "wiki" else "KB"
    filename = f"{safe_slug(document.title)}--{safe_slug(document.source_id, 'id')}.md"
    if document.module in {"Fiscal", "ADM_FIN_ESTOQUE", "PDV"}:
        return root / "conhecimento" / document.module / source_folder / filename
    return root / "conhecimento" / document.module / filename


def write_document(root: Path, document: KnowledgeDocument) -> Path:
    path = target_path(root, document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_markdown(document), encoding="utf-8")
    document.local_path = str(path)
    return path


def _strip_sensitive_query(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    safe_keys = {"title", "id", "article", "page"}
    safe_pairs = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() in safe_keys
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe_pairs), "")
    )
