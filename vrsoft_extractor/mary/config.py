from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..settings import load_dotenv_file
from .paths import resolve_portable_path, to_portable_path


DEFAULT_MARY_ROOT = Path("MaryProject")
LEGACY_MARY_ROOT = Path(r"D:\Codex\Projetos\VR_Mary_V2")
LEGACY_OLD_ROOT = Path(r"D:\Codex\VR")
DEFAULT_WIKI_API = "https://wiki.vrsoft.com.br/wiki/api.php"
DEFAULT_WIKI_BASE = "https://wiki.vrsoft.com.br/wiki/"
DEFAULT_KB_URL = "https://vrsoftware.movidesk.com/kb"


@dataclass(frozen=True)
class MarySettings:
    app_dir: Path
    root: Path
    old_root: Path
    wiki_api: str = DEFAULT_WIKI_API
    wiki_base: str = DEFAULT_WIKI_BASE
    kb_url: str = DEFAULT_KB_URL
    sync_interval_minutes: int = 120
    default_effort: str = "medium"

    @property
    def state_dir(self) -> Path:
        return self.root / ".state"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "conhecimento"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def index_dir(self) -> Path:
        return self.root / "indice"

    @property
    def database_path(self) -> Path:
        return self.index_dir / "conhecimento.sqlite"

    @property
    def work_dir(self) -> Path:
        return self.root / "TrabalhoMary"

    @property
    def videos_dir(self) -> Path:
        return self.root / "videos"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def tesseract_dir(self) -> Path:
        return self.root / "tools" / "tesseract"

    @property
    def movidesk_state_path(self) -> Path:
        return self.state_dir / "movidesk.json"

    def relative_path(self, value: str | Path | None) -> str:
        return to_portable_path(self.root, value)

    def resolve_path(self, value: str | Path | None) -> Path:
        return resolve_portable_path(self.root, value)

    def ensure_dirs(self) -> None:
        directories = [
            self.state_dir,
            self.assets_dir / "wiki",
            self.assets_dir / "kb",
            self.index_dir,
            self.work_dir,
            self.videos_dir,
            self.logs_dir,
            self.tesseract_dir,
        ]
        for module in ("Fiscal", "ADM_FIN_ESTOQUE", "PDV"):
            directories.extend(
                [self.knowledge_dir / module / "Wiki", self.knowledge_dir / module / "KB"]
            )
        directories.extend(
            [self.knowledge_dir / "Multimodulo", self.knowledge_dir / "Revisar"]
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


def load_mary_settings(
    app_dir: str | Path | None = None,
    root: str | Path | None = None,
    old_root: str | Path | None = None,
) -> MarySettings:
    app = Path(app_dir or Path.cwd()).resolve()
    load_dotenv_file(app / ".env")
    configured_root = _discover_root(app, root or os.environ.get("MARY_ROOT"))
    configured_old_root = old_root or os.environ.get("MARY_OLD_ROOT")
    if configured_old_root:
        old_path = _resolve_from_app(app, configured_old_root)
    elif LEGACY_OLD_ROOT.exists():
        old_path = LEGACY_OLD_ROOT.resolve()
    else:
        old_path = configured_root / "legacy-source"
    try:
        interval = int(os.environ.get("MARY_SYNC_INTERVAL_MINUTES", "120"))
    except ValueError:
        interval = 120
    return MarySettings(
        app_dir=app,
        root=configured_root,
        old_root=old_path,
        wiki_api=os.environ.get("MARY_WIKI_API", DEFAULT_WIKI_API).rstrip("/"),
        wiki_base=os.environ.get("MARY_WIKI_BASE", DEFAULT_WIKI_BASE),
        kb_url=os.environ.get("MARY_KB_URL", DEFAULT_KB_URL).rstrip("/"),
        sync_interval_minutes=max(15, interval),
        default_effort=os.environ.get("MARY_DEFAULT_EFFORT", "medium").strip().lower()
        or "medium",
    )


def _discover_root(app: Path, configured: str | Path | None) -> Path:
    if configured:
        return _resolve_from_app(app, configured)
    candidates = (
        app / "MaryProject",
        app.parent / "MaryProject",
        app,
        LEGACY_MARY_ROOT,
    )
    for candidate in candidates:
        if _looks_like_mary_root(candidate):
            return candidate.resolve()
    return (app / DEFAULT_MARY_ROOT).resolve()


def _resolve_from_app(app: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else app / path).resolve()


def _looks_like_mary_root(path: Path) -> bool:
    return path.is_dir() and (
        (path / "conhecimento").is_dir()
        or (path / "indice" / "conhecimento.sqlite").is_file()
        or (path / "agentes" / "AGENTS.md").is_file()
    )
