from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import re
import uuid
from dataclasses import dataclass
from pathlib import Path


MAX_OCR_DOWNLOAD_BYTES = 100 * 1024 * 1024
OCR_USER_AGENT = "VR-Norte-Studio/1.0 (+https://github.com/UB-Mannheim/tesseract)"
GITHUB_RELEASE_API = "https://api.github.com/repos/UB-Mannheim/tesseract/releases/latest"


@dataclass
class OcrResult:
    text: str
    confidence: float
    skipped_reason: str = ""


class OcrManager:
    def __init__(self, portable_dir: Path):
        self.portable_dir = portable_dir

    @property
    def executable(self) -> Path | None:
        candidates = [
            self.portable_dir / "tesseract.exe",
            self.portable_dir / "bin" / "tesseract.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        command = shutil.which("tesseract")
        return Path(command) if command else None

    def is_ready(self) -> bool:
        executable = self.executable
        if not executable:
            return False
        tessdata = executable.parent / "tessdata"
        if not tessdata.exists():
            tessdata = self.portable_dir / "tessdata"
        try:
            return all(
                path.is_file() and path.stat().st_size >= 100_000
                for path in (
                    tessdata / "por.traineddata",
                    tessdata / "eng.traineddata",
                )
            )
        except OSError:
            return False

    def extract(self, image_path: Path) -> OcrResult:
        executable = self.executable
        if not executable:
            return OcrResult("", 0.0, "Tesseract portátil não instalado")
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            return OcrResult("", 0.0, "Dependências OCR não instaladas")

        with Image.open(image_path) as image:
            width, height = image.size
            if width < 120 or height < 60 or width * height < 20_000:
                return OcrResult("", 0.0, "Imagem pequena/ícone")
            pytesseract.pytesseract.tesseract_cmd = str(executable)
            data = pytesseract.image_to_data(
                image,
                lang="por+eng",
                config="--psm 3",
                output_type=pytesseract.Output.DICT,
            )
        words: list[str] = []
        confidences: list[float] = []
        for text, confidence in zip(data.get("text", []), data.get("conf", [])):
            value = str(text).strip()
            try:
                score = float(confidence)
            except (TypeError, ValueError):
                score = -1
            if value:
                words.append(value)
            if score >= 0:
                confidences.append(score)
        mean = sum(confidences) / len(confidences) / 100 if confidences else 0.0
        return OcrResult(" ".join(words).strip(), mean)

    def install_portable(self, progress=None) -> Path:
        report = progress or (lambda _message: None)
        self.portable_dir.mkdir(parents=True, exist_ok=True)
        report("Consultando a distribuição Windows do Tesseract…")
        listing_url = "https://digi.bib.uni-mannheim.de/tesseract/"
        try:
            listing = _read_url(listing_url).decode("utf-8", "replace")
            installer_url = latest_windows_installer_url(listing, listing_url)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError) as exc:
            report(
                "Catálogo Mannheim indisponível"
                + (" (HTTP 403)" if getattr(exc, "code", None) == 403 else "")
                + "; consultando o release oficial no GitHub…"
            )
            release = json.loads(_read_url(GITHUB_RELEASE_API).decode("utf-8"))
            installer_url = latest_github_installer_url(release)
        installer = self.portable_dir.parent / "tesseract-setup.exe"
        report(f"Baixando {Path(urllib.parse.urlsplit(installer_url).path).name}…")
        _download_file(installer_url, installer, minimum_bytes=1_000_000)
        try:
            report("Instalando o mecanismo OCR na pasta local…")
            completed = subprocess.run(
                [
                    str(installer),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    f"/DIR={self.portable_dir}",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if completed.returncode:
                raise RuntimeError(
                    "Instalador Tesseract falhou: "
                    + (completed.stderr.strip() or completed.stdout.strip())
                )
        finally:
            installer.unlink(missing_ok=True)
        tessdata = self.portable_dir / "tessdata"
        tessdata.mkdir(parents=True, exist_ok=True)
        for language in ("por", "eng"):
            target = tessdata / f"{language}.traineddata"
            if target.exists():
                continue
            report(f"Baixando idioma OCR: {language}…")
            url = (
                "https://raw.githubusercontent.com/tesseract-ocr/"
                f"tessdata_fast/main/{language}.traineddata"
            )
            _download_file(url, target, minimum_bytes=100_000)
        if not self.is_ready():
            raise RuntimeError("Tesseract foi instalado, mas por+eng não foi validado.")
        report("OCR portátil por+eng pronto.")
        return self.executable or self.portable_dir / "tesseract.exe"


def _download_file(
    url: str,
    target: Path,
    *,
    minimum_bytes: int,
    maximum_bytes: int = MAX_OCR_DOWNLOAD_BYTES,
) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RuntimeError(f"URL de download OCR insegura ou inválida: {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": OCR_USER_AGENT, "Accept": "*/*"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            with temporary.open("wb") as handle:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > maximum_bytes:
                        raise RuntimeError(
                            f"Download excede o limite de {maximum_bytes} bytes: {target.name}."
                        )
                    handle.write(chunk)
        if temporary.stat().st_size < minimum_bytes:
            raise RuntimeError(
                f"Download incompleto para {target.name}: "
                f"{temporary.stat().st_size} bytes."
            )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": OCR_USER_AGENT,
            "Accept": "application/vnd.github+json, text/html;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def latest_github_installer_url(release: dict) -> str:
    """Select the trusted Windows x64 installer from a GitHub release payload."""
    candidates: list[tuple[str, str]] = []
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if re.fullmatch(r"tesseract-ocr-w64-setup-[^/]+\.exe", name, re.IGNORECASE):
            candidates.append((name, url))
    if not candidates:
        raise RuntimeError("O release oficial não contém o instalador Windows x64.")
    _name, result = max(candidates, key=lambda item: item[0].casefold())
    parsed = urllib.parse.urlsplit(result)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or not parsed.path.startswith("/UB-Mannheim/tesseract/releases/download/")
    ):
        raise RuntimeError("O release OCR apontou para um instalador fora da origem confiável.")
    return result


def latest_windows_installer_url(listing: str, base_url: str) -> str:
    links = re.findall(
        r'href=["\']([^"\']*tesseract-ocr-w64-setup-[^"\']+\.exe)["\']',
        listing,
        flags=re.IGNORECASE,
    )
    if not links:
        raise RuntimeError("Não foi encontrado instalador Windows x64 do Tesseract.")

    def version_key(link: str) -> tuple[int, ...]:
        filename = Path(urllib.parse.urlsplit(link).path).name
        version = re.search(r"setup-([0-9][0-9.]*)", filename, re.IGNORECASE)
        value = (version.group(1) if version else "0").rstrip(".")
        return tuple(int(part) for part in value.split("."))

    result = urllib.parse.urljoin(base_url, max(set(links), key=version_key))
    base = urllib.parse.urlsplit(base_url)
    parsed = urllib.parse.urlsplit(result)
    if parsed.scheme != "https" or parsed.hostname != base.hostname:
        raise RuntimeError("O catálogo OCR apontou para um instalador fora da origem confiável.")
    return result
