from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import unicodedata
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, TypeVar

from bs4 import BeautifulSoup
from markdownify import markdownify

from .models import KnowledgeDocument
from .paths import resolve_portable_path, to_portable_path


PersistedDocument = TypeVar("PersistedDocument")
KNOWLEDGE_MODULES = {
    "Fiscal",
    "ADM_FIN_ESTOQUE",
    "PDV",
    "Multimodulo",
    "Revisar",
}
MAX_ASSET_BYTES = 25 * 1024 * 1024


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
        anchor["href"] = urllib.parse.urljoin(base_url, str(anchor.get("href") or ""))
    image_urls: list[str] = []
    for image in soup.find_all("img", src=True):
        absolute = urllib.parse.urljoin(base_url, str(image.get("src") or ""))
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
    parsed_url = urllib.parse.urlsplit(url)
    if (
        parsed_url.scheme.casefold() not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise ValueError(f"URL de recurso insegura ou inválida: {url}")
    fetch = opener or _download_bytes
    data = fetch(url)
    if not data:
        raise ValueError(f"Recurso vazio recebido de {url}")
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError(
            f"Recurso excede o limite de {MAX_ASSET_BYTES // (1024 * 1024)} MiB: {url}"
        )
    digest = sha256_bytes(data)
    path_part = urllib.parse.urlsplit(url).path
    extension = Path(path_part).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,6}", extension):
        content_type = mimetypes.guess_type(path_part)[0] or ""
        extension = mimetypes.guess_extension(content_type) or ".bin"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{digest}{extension}"
    if not destination.exists():
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "VR-Norte-Studio/0.2 (+knowledge-sync)"},
    )
    # The URL scheme, host and credentials were validated by download_asset.
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > MAX_ASSET_BYTES:
                raise ValueError(
                    "Recurso remoto excede o limite de "
                    f"{MAX_ASSET_BYTES // (1024 * 1024)} MiB."
                )
        data = response.read(MAX_ASSET_BYTES + 1)
        if len(data) > MAX_ASSET_BYTES:
            raise ValueError(
                f"Recurso remoto excede o limite de {MAX_ASSET_BYTES // (1024 * 1024)} MiB."
            )
        return data


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
    if document.source not in {"wiki", "kb"}:
        raise ValueError(f"Fonte de conhecimento inválida: {document.source}")
    if document.module not in KNOWLEDGE_MODULES:
        raise ValueError(f"Módulo de conhecimento inválido: {document.module}")
    source_folder = "Wiki" if document.source == "wiki" else "KB"
    filename = f"{safe_slug(document.title)}--{safe_slug(document.source_id, 'id')}.md"
    if document.module in {"Fiscal", "ADM_FIN_ESTOQUE", "PDV"}:
        return root / "conhecimento" / document.module / source_folder / filename
    return root / "conhecimento" / document.module / filename


def preserve_validated_classification(
    current,
    document: KnowledgeDocument,
) -> bool:
    """Preserve a human decision and report whether changed content needs review."""

    if current is None or str(current["review_status"]) not in {"approved", "kept"}:
        return False
    current_module = str(current["module"])
    same_content = str(current["content_hash"] or "") == document.content_hash
    if same_content:
        document.module = current_module
        document.review_status = "approved"
        return False
    if current_module != document.module:
        document.module = current_module
        document.review_status = "pending"
        return True
    return False


def write_document(
    root: Path,
    document: KnowledgeDocument,
    *,
    previous_path: str | Path | None = None,
) -> Path:
    path = target_path(root, document)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.assets = [to_portable_path(root, asset) for asset in document.assets]
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(canonical_markdown(document), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    document.local_path = to_portable_path(root, path)
    if previous_path:
        remove_previous_document(root, previous_path, path)
    return path


def write_and_persist_document(
    root: Path,
    document: KnowledgeDocument,
    persist: Callable[[], PersistedDocument],
    *,
    previous_path: str | Path | None = None,
) -> PersistedDocument:
    """Write canonically and roll the file back when persistence fails."""

    target = target_path(root, document)
    previous_content = target.read_bytes() if target.is_file() else None
    write_document(root, document)
    try:
        result = persist()
    except Exception:
        try:
            if previous_content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous_content)
        except OSError:
            pass
        raise
    if previous_path:
        remove_previous_document(root, previous_path, target)
    return result


def remove_previous_document(
    root: Path,
    previous_path: str | Path,
    current_path: str | Path,
) -> None:
    previous = resolve_portable_path(root, previous_path)
    current = resolve_portable_path(root, current_path)
    knowledge_root = (root / "conhecimento").resolve()
    try:
        previous = previous.resolve(strict=False)
        if (
            previous != current.resolve(strict=False)
            and previous.is_relative_to(knowledge_root)
            and previous.is_file()
        ):
            previous.unlink()
    except OSError:
        # The new canonical file and database row are already valid. A stale
        # predecessor is safer than deleting or rolling back the new content.
        pass


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
