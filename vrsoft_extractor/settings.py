from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_BASE_URL = "https://vrsoft.endoo.com.br"
PROTECTED_CREDENTIAL_KEYS = ("ENDOO_PASSWORD", "MOVIDESK_PASSWORD")
PROTECTED_CREDENTIALS_FILENAME = "credentials.dpapi.json"


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
    def courses_json_path(self) -> Path:
        return self.metadata_dir / "courses.json"

    @property
    def video_overrides_path(self) -> Path:
        return self.metadata_dir / "video_module_overrides.json"

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
    if int(max_pages_per_section) < 1:
        raise ConfigError("O limite de páginas deve ser maior que zero.")
    settings = Settings(
        project_dir=root,
        base_url=validated_http_url(base_url or DEFAULT_BASE_URL, "URL do Endoo").rstrip("/"),
        max_pages_per_section=int(max_pages_per_section),
    )
    load_dotenv_file(settings.dotenv_path)
    return settings


def validated_http_url(value: str, label: str = "URL") -> str:
    candidate = str(value or "").strip()
    parsed = urllib.parse.urlsplit(candidate)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ConfigError(f"{label} inválida: use uma URL HTTP(S) sem credenciais.")
    return candidate


def ensure_runtime_dirs(settings: Settings) -> None:
    for path in (
        settings.state_dir,
        settings.metadata_dir,
        settings.downloads_dir,
        settings.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def load_dotenv_file(path: Path) -> None:
    if path.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(path, override=False)
        except ImportError:
            for line in path.read_text(encoding="utf-8").splitlines():
                parsed = _parse_env_line(line)
                if parsed is None:
                    continue
                key, value = parsed
                os.environ.setdefault(key, value)
        _migrate_plaintext_credentials(path)
    _load_protected_credentials(path.parent)


def update_dotenv_file(path: Path, updates: dict[str, str]) -> None:
    """Update selected dotenv keys without discarding unrelated configuration."""
    normalized: dict[str, str] = {}
    for raw_key, raw_value in updates.items():
        key = str(raw_key).strip()
        value = str(raw_value)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ConfigError(f"Nome de configuração inválido: {raw_key!r}")
        if "\r" in value or "\n" in value:
            raise ConfigError(f"A configuração {key} não pode conter quebra de linha.")
        normalized[key] = value

    if os.name == "nt":
        protected_updates = {
            key: normalized[key]
            for key in PROTECTED_CREDENTIAL_KEYS
            if key in normalized
        }
        if protected_updates:
            _update_protected_credentials(path.parent, protected_updates)
            for key in protected_updates:
                normalized[key] = ""

    original = path.read_text(encoding="utf-8") if path.exists() else ""
    result: list[str] = []
    written: set[str] = set()
    assignment = re.compile(
        r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*="
    )
    for line in original.splitlines():
        match = assignment.match(line)
        if match is None:
            result.append(line)
            continue
        key = match.group("key")
        if key not in normalized:
            result.append(line)
            continue
        if key in written:
            continue
        result.append(
            f"{match.group('prefix')}{key}={_quote_dotenv_value(normalized[key])}"
        )
        written.add(key)
    for key, value in normalized.items():
        if key not in written:
            result.append(f"{key}={_quote_dotenv_value(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text("\n".join(result) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _quote_dotenv_value(value: str) -> str:
    """Return a python-dotenv compatible literal without comment expansion."""

    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_@+./:\\-]*", text):
        return text
    escaped = text.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _protected_credentials_path(directory: Path) -> Path:
    return Path(directory) / ".state" / PROTECTED_CREDENTIALS_FILENAME


def _migrate_plaintext_credentials(path: Path) -> None:
    if os.name != "nt" or not path.is_file():
        return
    try:
        from dotenv import dotenv_values

        values = dotenv_values(path)
    except ImportError:
        values = dict(
            parsed
            for line in path.read_text(encoding="utf-8").splitlines()
            if (parsed := _parse_env_line(line)) is not None
        )
    secrets = {
        key: str(values.get(key) or "")
        for key in PROTECTED_CREDENTIAL_KEYS
        if values.get(key)
    }
    if not secrets:
        return
    try:
        update_dotenv_file(path, secrets)
    except OSError:
        # Keep the existing plaintext functional if the current Windows
        # account cannot access DPAPI; the next save will retry migration.
        return


def _update_protected_credentials(directory: Path, updates: dict[str, str]) -> None:
    if os.name != "nt":
        return
    path = _protected_credentials_path(directory)
    current = _read_protected_credentials(directory)
    for key, value in updates.items():
        if value:
            current[key] = value
        else:
            current.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "values": {
            key: base64.b64encode(_protect_windows_value(value)).decode("ascii")
            for key, value in current.items()
            if key in PROTECTED_CREDENTIAL_KEYS and value
        },
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_protected_credentials(directory: Path) -> dict[str, str]:
    if os.name != "nt":
        return {}
    path = _protected_credentials_path(directory)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = dict(payload.get("values") or {})
    except (AttributeError, OSError, TypeError, ValueError):
        return {}
    result: dict[str, str] = {}
    for key, encoded in values.items():
        if key not in PROTECTED_CREDENTIAL_KEYS:
            continue
        try:
            encrypted = base64.b64decode(str(encoded), validate=True)
            result[key] = _unprotect_windows_value(encrypted)
        except (OSError, UnicodeError, ValueError):
            continue
    return result


def _load_protected_credentials(directory: Path) -> None:
    for key, value in _read_protected_credentials(directory).items():
        if not os.environ.get(key):
            os.environ[key] = value


def _protect_windows_value(value: str) -> bytes:
    return _windows_crypt(str(value).encode("utf-8"), protect=True)


def _unprotect_windows_value(value: bytes) -> str:
    return _windows_crypt(bytes(value), protect=False).decode("utf-8")


def _windows_crypt(value: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI está disponível apenas no Windows.")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    buffer = ctypes.create_string_buffer(value)
    source = DataBlob(
        len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    )
    target = DataBlob()
    function = (
        ctypes.windll.crypt32.CryptProtectData
        if protect
        else ctypes.windll.crypt32.CryptUnprotectData
    )
    description = ctypes.c_wchar_p("VR Norte Studio") if protect else None
    if not function(
        ctypes.byref(source),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(target),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(
            ctypes.cast(target.pbData, ctypes.c_void_p)
        )


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        quote = value[0]
        value = value[1:-1]
        if quote == "'":
            value = re.sub(r"\\(['\\])", r"\1", value)
        else:
            value = value.replace(r'\"', '"').replace(r"\\", "\\")
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
    for key in (
        "ENDOO_EMAIL",
        "ENDOO_PASSWORD",
        "MOVIDESK_EMAIL",
        "MOVIDESK_PASSWORD",
    ):
        value = os.environ.get(key)
        if value:
            yield value


def redact_sensitive_text(value: object, replacement: str = "[REDACTED]") -> str:
    """Remove configured credentials before text reaches logs or UI surfaces."""

    text = str(value or "")
    secrets = sorted(set(sensitive_values()), key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, replacement)
    return text
