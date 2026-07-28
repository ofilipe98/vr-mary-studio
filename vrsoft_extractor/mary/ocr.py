from __future__ import annotations

import shutil
import subprocess
import urllib.parse
import urllib.request
import re
from dataclasses import dataclass
from pathlib import Path


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
        return (tessdata / "por.traineddata").exists() and (
            tessdata / "eng.traineddata"
        ).exists()

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
        with urllib.request.urlopen(listing_url, timeout=60) as response:
            listing = response.read().decode("utf-8", "replace")
        installer_url = latest_windows_installer_url(listing, listing_url)
        installer = self.portable_dir.parent / "tesseract-setup.exe"
        report(f"Baixando {Path(urllib.parse.urlsplit(installer_url).path).name}…")
        urllib.request.urlretrieve(installer_url, installer)
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
            urllib.request.urlretrieve(url, target)
        try:
            installer.unlink()
        except OSError:
            pass
        if not self.is_ready():
            raise RuntimeError("Tesseract foi instalado, mas por+eng não foi validado.")
        report("OCR portátil por+eng pronto.")
        return self.executable or self.portable_dir / "tesseract.exe"


def latest_windows_installer_url(listing: str, base_url: str) -> str:
    links = re.findall(
        r'href=["\']([^"\']*tesseract-ocr-w64-setup-[^"\']+\.exe)["\']',
        listing,
        flags=re.IGNORECASE,
    )
    if not links:
        raise RuntimeError("Não foi encontrado instalador Windows x64 do Tesseract.")
    return urllib.parse.urljoin(base_url, sorted(set(links))[-1])
