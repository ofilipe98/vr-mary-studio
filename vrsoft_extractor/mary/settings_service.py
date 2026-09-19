from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

from .config import ConfigError, MarySettings, load_vr_settings, save_vr_env

SETUP_KEY_COMPLETED = "setup/completed"
SETUP_KEY_VERSION = "setup/version"
SETUP_VERSION = 1


def is_setup_needed(
    settings: MarySettings | None,
    preferences: QSettings | None,
) -> bool:
    """Check if the initial setup wizard must be shown.

    Setup is required if:
    1. setup/completed is not set to true in QSettings
    2. The stored setup schema version is older than SETUP_VERSION
    3. The configured root folder does not exist or is invalid
    4. Essential configuration cannot be loaded
    """
    if preferences is None:
        return True

    completed = str(preferences.value(SETUP_KEY_COMPLETED, "false")).lower() == "true"
    if not completed:
        return True

    try:
        stored_version = int(preferences.value(SETUP_KEY_VERSION, 0) or 0)
    except (TypeError, ValueError):
        stored_version = 0
    if stored_version < SETUP_VERSION:
        return True

    if settings is None:
        return True

    # Validate that root exists and is an accessible directory
    try:
        if not settings.root.exists() or not settings.root.is_dir():
            return True
    except Exception:
        return True

    return False


def mark_setup_completed(preferences: QSettings) -> None:
    """Persist setup completion flag and schema version into QSettings."""
    preferences.setValue(SETUP_KEY_COMPLETED, "true")
    preferences.setValue(SETUP_KEY_VERSION, SETUP_VERSION)
    preferences.sync()


def diagnostic_text(settings: MarySettings) -> str:
    """Generate diagnostic summary for the current settings matching existing studio behavior."""
    try:
        from .ocr import OcrManager

        ocr_ready = OcrManager(settings.tesseract_dir).is_ready()
    except Exception:
        ocr_ready = False
    codex_ready = (settings.root / ".codex" / "config.toml").is_file()
    return (
        f"Projeto Codex: {'OK' if codex_ready else 'não preparado'}\n"
        f"Tesseract por+eng: {'OK' if ocr_ready else 'não instalado'}"
    )


def get_settings_values(settings: MarySettings) -> dict[str, Any]:
    """Return dictionary of current settings without exposing plaintext passwords to QML."""
    movidesk_password = os.environ.get("MOVIDESK_PASSWORD", "")
    endoo_password = os.environ.get("ENDOO_PASSWORD", "")
    return {
        "root": str(settings.root),
        "movideskEmail": os.environ.get("MOVIDESK_EMAIL", ""),
        "movideskPassword": "",
        "movideskPasswordConfigured": bool(movidesk_password),
        "endooEmail": os.environ.get("ENDOO_EMAIL", ""),
        "endooPassword": "",
        "endooPasswordConfigured": bool(endoo_password),
        "interval": str(settings.sync_interval_minutes),
        "diagnostic": diagnostic_text(settings),
    }


def save_settings(
    settings: MarySettings,
    root: str,
    movidesk_email: str,
    movidesk_password: str,
    endoo_email: str,
    endoo_password: str,
    interval: str,
) -> tuple[MarySettings, dict[str, Any]]:
    """Validate, persist and reload settings, preserving existing secrets when empty passwords are provided."""
    target_root_str = str(root or "").strip()
    if not target_root_str:
        raise ConfigError("A raiz da base VR não pode ficar vazia.")

    target_root = Path(target_root_str).expanduser().resolve()
    if target_root.exists() and not target_root.is_dir():
        raise ConfigError(f"O caminho '{target_root}' não é um diretório válido.")

    try:
        target_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise ConfigError(f"Não foi possível acessar ou criar o diretório '{target_root}': {exc}") from exc

    movidesk_secret = (
        movidesk_password.strip()
        if movidesk_password.strip()
        else os.environ.get("MOVIDESK_PASSWORD", "")
    )
    endoo_secret = (
        endoo_password.strip()
        if endoo_password.strip()
        else os.environ.get("ENDOO_PASSWORD", "")
    )

    clean_interval = str(interval or "").strip() or "120"
    values = {
        "VR_ROOT": str(target_root),
        "MOVIDESK_EMAIL": movidesk_email.strip(),
        "MOVIDESK_PASSWORD": movidesk_secret,
        "ENDOO_EMAIL": endoo_email.strip(),
        "ENDOO_PASSWORD": endoo_secret,
        "VR_SYNC_INTERVAL_MINUTES": clean_interval,
        "VR_DEFAULT_EFFORT": settings.default_effort,
    }

    # save_vr_env expects the application directory and updates <app_dir>/.env.
    save_vr_env(settings.app_dir, values)

    # Align the process runtime explicitly: reading the .env back does not
    # override variables already present, so stale values would linger.
    # Passwords keep the existing DPAPI policy (save_vr_env moves them to the
    # protected store on Windows); only mirror them here when a secret exists.
    os.environ["VR_ROOT"] = str(target_root)
    os.environ["MOVIDESK_EMAIL"] = movidesk_email.strip()
    os.environ["ENDOO_EMAIL"] = endoo_email.strip()
    os.environ["VR_SYNC_INTERVAL_MINUTES"] = clean_interval
    os.environ["VR_DEFAULT_EFFORT"] = str(settings.default_effort)
    if movidesk_secret:
        os.environ["MOVIDESK_PASSWORD"] = movidesk_secret
    if endoo_secret:
        os.environ["ENDOO_PASSWORD"] = endoo_secret

    reloaded_settings = load_vr_settings(
        str(settings.app_dir),
        str(target_root),
    )

    safe_values = get_settings_values(reloaded_settings)
    return reloaded_settings, safe_values
