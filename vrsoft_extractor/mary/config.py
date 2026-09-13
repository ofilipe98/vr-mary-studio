from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..settings import (
    ConfigError,
    DEFAULT_BASE_URL,
    load_dotenv_file,
    update_dotenv_file,
    validated_http_url,
)
from .paths import resolve_portable_path, to_portable_path


DEFAULT_VR_ROOT = Path("VRProject")
LEGACY_MARY_ROOT = Path(r"D:\Codex\Projetos\VR_Mary_V2")
LEGACY_OLD_ROOT = Path(r"D:\Codex\VR")
DEFAULT_WIKI_API = "https://wiki.vrsoft.com.br/wiki/api.php"
DEFAULT_WIKI_BASE = "https://wiki.vrsoft.com.br/wiki/"
DEFAULT_KB_URL = "https://vrsoftware.movidesk.com/kb"
DEFAULT_ENDOO_API_URL = "https://api.iendo.us/api"
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class MarySettings:
    app_dir: Path
    root: Path
    old_root: Path
    wiki_api: str = DEFAULT_WIKI_API
    wiki_base: str = DEFAULT_WIKI_BASE
    kb_url: str = DEFAULT_KB_URL
    endoo_base_url: str = DEFAULT_BASE_URL
    endoo_api_url: str = DEFAULT_ENDOO_API_URL
    endoo_wiki_enabled: bool = True
    sync_interval_minutes: int = 120
    default_effort: str = "medium"
    # Adaptive effort raises the reasoning effort per turn when the request
    # profile demands it; it never lowers the user's chosen level.
    vr_adaptive_effort: bool = True
    # Module fan-out research: parallel per-module readers for multi-module or
    # deeply detailed questions. Kill switch: VR_RESEARCH_FANOUT=0.
    vr_research_fanout: bool = True
    # Discreet hint suggesting the VR flow when a native-mode message clearly
    # targets the local ERP domain (max once per conversation).
    vr_mode_hint_enabled: bool = True
    # Opt-in: expose the vr_search tool to native turns so the provider can
    # pull local evidence on demand. Applies to threads created after enabling.
    native_vr_search_enabled: bool = True

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
    def erp_releases_dir(self) -> Path:
        return self.root / "ERP" / "releases"

    @property
    def code_index_dir(self) -> Path:
        return self.index_dir / "codigo"

    @property
    def code_tools_dir(self) -> Path:
        return self.root / "tools" / "code-analysis"

    @property
    def code_processing_database_path(self) -> Path:
        return self.code_index_dir / "processing.sqlite"

    @property
    def work_dir(self) -> Path:
        return self.root / "TrabalhoVR"

    @property
    def legacy_work_dir(self) -> Path:
        """Workspace location used by installations created before the rename."""

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

    @property
    def endoo_state_path(self) -> Path:
        return self.state_dir / "endoo.json"

    def relative_path(self, value: str | Path | None) -> str:
        return to_portable_path(self.root, value)

    def resolve_path(self, value: str | Path | None) -> Path:
        return resolve_portable_path(self.root, value)

    def ensure_dirs(self) -> None:
        directories = [
            self.state_dir,
            self.assets_dir / "wiki",
            self.assets_dir / "wiki" / "endoo",
            self.assets_dir / "kb",
            self.index_dir,
            self.erp_releases_dir,
            self.code_index_dir / "releases",
            self.code_index_dir / "artifacts",
            self.code_tools_dir / "decompilers",
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


def load_vr_settings(
    app_dir: str | Path | None = None,
    root: str | Path | None = None,
    old_root: str | Path | None = None,
) -> MarySettings:
    app = Path(app_dir or Path.cwd()).resolve()
    load_dotenv_file(app / ".env")
    configured_root = _discover_root(
        app,
        root or os.environ.get("VR_ROOT") or os.environ.get("MARY_ROOT"),
    )
    configured_old_root = (
        old_root or os.environ.get("VR_OLD_ROOT") or os.environ.get("MARY_OLD_ROOT")
    )
    if configured_old_root:
        old_path = _resolve_from_app(app, configured_old_root)
    elif LEGACY_OLD_ROOT.exists():
        old_path = LEGACY_OLD_ROOT.resolve()
    else:
        old_path = configured_root / "legacy-source"
    try:
        interval = int(
            os.environ.get("VR_SYNC_INTERVAL_MINUTES")
            or os.environ.get("MARY_SYNC_INTERVAL_MINUTES", "120")
        )
    except ValueError:
        interval = 120
    effort = (
        os.environ.get("VR_DEFAULT_EFFORT")
        or os.environ.get("MARY_DEFAULT_EFFORT", "medium")
    ).strip().lower()
    if effort == "ultra":
        effort = "max"
    if effort not in VALID_EFFORTS:
        effort = "medium"
    return MarySettings(
        app_dir=app,
        root=configured_root,
        old_root=old_path,
        wiki_api=validated_http_url(
            os.environ.get("VR_WIKI_API")
            or os.environ.get("MARY_WIKI_API", DEFAULT_WIKI_API),
            "URL da API Wiki",
        ).rstrip("/"),
        wiki_base=validated_http_url(
            os.environ.get("VR_WIKI_BASE")
            or os.environ.get("MARY_WIKI_BASE", DEFAULT_WIKI_BASE),
            "URL base da Wiki",
        ),
        kb_url=validated_http_url(
            os.environ.get("VR_KB_URL")
            or os.environ.get("MARY_KB_URL", DEFAULT_KB_URL),
            "URL do KB",
        ).rstrip("/"),
        endoo_base_url=validated_http_url(
            os.environ.get("ENDOO_BASE_URL", DEFAULT_BASE_URL),
            "URL base do Endoo",
        ).rstrip("/"),
        endoo_api_url=validated_http_url(
            os.environ.get("ENDOO_API_URL", DEFAULT_ENDOO_API_URL),
            "URL da API do Endoo",
        ).rstrip("/"),
        endoo_wiki_enabled=str(
            os.environ.get("VR_ENDOO_WIKI_ENABLED", "1")
        ).strip().casefold() not in {"", "0", "false", "no", "off"},
        vr_adaptive_effort=str(
            os.environ.get("VR_ADAPTIVE_EFFORT", "1")
        ).strip().casefold() not in {"", "0", "false", "no", "off"},
        vr_research_fanout=str(
            os.environ.get("VR_RESEARCH_FANOUT", "1")
        ).strip().casefold() not in {"", "0", "false", "no", "off"},
        vr_mode_hint_enabled=str(
            os.environ.get("VR_MODE_HINT_ENABLED", "1")
        ).strip().casefold() not in {"", "0", "false", "no", "off"},
        native_vr_search_enabled=str(
            os.environ.get("VR_NATIVE_SEARCH_ENABLED", "1")
        ).strip().casefold() not in {"", "0", "false", "no", "off"},
        sync_interval_minutes=max(15, interval),
        default_effort=effort,
    )


def save_vr_env(app_dir: Path, values: dict[str, str]) -> None:
    interval_text = values.get("VR_SYNC_INTERVAL_MINUTES", "").strip()
    try:
        interval = int(interval_text)
    except ValueError as exc:
        raise ConfigError("O intervalo de sincronização deve ser um número inteiro.") from exc
    if interval < 15:
        raise ConfigError("O intervalo de sincronização deve ser de pelo menos 15 minutos.")

    root = values.get("VR_ROOT", "").strip()
    if not root:
        raise ConfigError("A raiz da base VR não pode ficar vazia.")
    effort = values.get("VR_DEFAULT_EFFORT", "").strip().lower()
    if effort not in VALID_EFFORTS:
        raise ConfigError("O nível de esforço padrão é inválido.")

    sanitized = {key: str(value) for key, value in values.items()}
    sanitized["VR_ROOT"] = root
    sanitized["VR_SYNC_INTERVAL_MINUTES"] = str(interval)
    sanitized["VR_DEFAULT_EFFORT"] = effort
    update_dotenv_file(app_dir / ".env", sanitized)


# Public compatibility alias for integrations created before the VR rename.
load_mary_settings = load_vr_settings
save_mary_env = save_vr_env


def _discover_root(app: Path, configured: str | Path | None) -> Path:
    if configured:
        return _resolve_from_app(app, configured)
    candidates = (
        app / "VRProject",
        app.parent / "VRProject",
        app / "MaryProject",
        app.parent / "MaryProject",
        app,
        LEGACY_MARY_ROOT,
    )
    for candidate in candidates:
        if _looks_like_vr_root(candidate):
            return candidate.resolve()
    return (app / DEFAULT_VR_ROOT).resolve()


def _resolve_from_app(app: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else app / path).resolve()


def _looks_like_vr_root(path: Path) -> bool:
    return path.is_dir() and (
        (path / "conhecimento").is_dir()
        or (path / "indice" / "conhecimento.sqlite").is_file()
        or (path / "agentes" / "AGENTS.md").is_file()
    )
