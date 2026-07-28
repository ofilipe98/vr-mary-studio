from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_BASE_URL = "https://vrsoft.endoo.com.br"


class ConfigError(RuntimeError):
    """Raised when local configuration is incomplete or invalid."""


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str


@dataclass(frozen=True)
class Settings:
    project_dir: Path
    base_url: str = DEFAULT_BASE_URL
    max_pages_per_section: int = 200

    @property
    def dotenv_path(self) -> Path:
        return self.project_dir / ".env"

    @property
    def state_dir(self) -> Path:
        return self.project_dir / ".state"

    @property
    def storage_state_path(self) -> Path:
        return self.state_dir / "endoo.json"

    @property
    def metadata_dir(self) -> Path:
        return self.project_dir / "metadata"

    @property
    def inventory_json_path(self) -> Path:
        return self.metadata_dir / "videos.json"

    @property
    def inventory_csv_path(self) -> Path:
        return self.metadata_dir / "videos.csv"

    @property
    def downloads_dir(self) -> Path:
        return self.project_dir / "downloads"

    @property
    def logs_dir(self) -> Path:
        return self.project_dir / "logs"

    @property
    def cookiefile_path(self) -> Path:
        return self.state_dir / "cookies.txt"


def load_settings(
    project_dir: str | Path | None = None,
    base_url: str | None = None,
    max_pages_per_section: int = 200,
) -> Settings:
    root = Path(project_dir or Path.cwd()).resolve()
    settings = Settings(
        project_dir=root,
        base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
        max_pages_per_section=max_pages_per_section,
    )
    load_dotenv_file(settings.dotenv_path)
    return settings


def ensure_runtime_dirs(settings: Settings) -> None:
    for path in (
        settings.state_dir,
        settings.metadata_dir,
        settings.downloads_dir,
        settings.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return

    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)
        return
    except ImportError:
        pass

    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if not key:
        return None
    return key, value


def get_credentials(required: bool = True) -> Credentials | None:
    email = os.environ.get("ENDOO_EMAIL", "").strip()
    password = os.environ.get("ENDOO_PASSWORD", "")
    if email and password:
        return Credentials(email=email, password=password)
    if required:
        missing = [
            name
            for name, value in (("ENDOO_EMAIL", email), ("ENDOO_PASSWORD", password))
            if not value
        ]
        raise ConfigError(
            "Credenciais ausentes no .env: " + ", ".join(missing)
        )
    return None


def sensitive_values() -> Iterable[str]:
    for key in ("ENDOO_EMAIL", "ENDOO_PASSWORD"):
        value = os.environ.get(key)
        if value:
            yield value

