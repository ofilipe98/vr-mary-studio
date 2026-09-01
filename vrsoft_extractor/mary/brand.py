"""Canonical VR Norte Studio identity shared by desktop frontends."""

from __future__ import annotations

from pathlib import Path


APP_TITLE = "VR Norte Studio"
SETTINGS_APP_NAME = APP_TITLE
LEGACY_SETTINGS_APP_NAME = "VR Mary Studio"
ORGANIZATION_NAME = "VRNorte"

ASSET_DIR = Path(__file__).resolve().parent / "assets"
APP_ICON_PATH = ASSET_DIR / "vrnorte-app.ico"
BRAND_SYMBOL_PATH = ASSET_DIR / "vrnorte-symbol.png"

# Institutional palette.  Keep these values stable during the QML migration:
# the work modernizes layout and interaction without changing the brand.
BRAND_ORANGE = "#FF7200"
ACCESSIBLE_ORANGE = "#C45100"
BRAND_YELLOW = "#FCBD0F"
BRAND_NAVY = "#02021E"
TEXT_MUTED = "#4E4E62"
BACKGROUND = "#F3F3F3"
FOCUS_DARK = "#7A3500"
LINK_VISITED = "#5A2600"
DISABLED_TEXT = "#5F5F70"
DISABLED_BACKGROUND = "#ECECF1"
STATUS_GOOD = "#176B3A"
STATUS_WARN = "#8A5500"
SCROLLBAR_HANDLE = "#848493"
SCROLLBAR_TRACK = "#F0F0F4"
# Soft accent wash used by secondary selection surfaces (tabs, chips).
ACCENT_SOFT = "#FFE8D6"
ACCENT_SOFT_HOVER = "#EAEAF0"

# Deep dark canvas unified with the black navigation rail and Chat VR so the
# Dark & Orange theme never reads as gray. Surfaces keep the warm tones.
DARK_BACKGROUND = "#000000"
DARK_SURFACE = "#131110"
DARK_SURFACE_RAISED = "#1B1816"
DARK_TEXT = "#D6D6D9"
DARK_MUTED = "#96969F"
DARK_BORDER = "#2C2823"
DARK_STATUS_GOOD = "#56D18B"
DARK_STATUS_WARN = "#FFB55C"
DARK_SCROLLBAR_HANDLE = "#8C8077"
DARK_ACCENT_SOFT = "#462813"


def brand_palette(theme_id: str) -> dict[str, str]:
    """Return semantic colors without leaking a widget implementation."""

    dark = theme_id == "dark_orange"
    return {
        "themeId": "dark_orange" if dark else "light",
        "brandOrange": BRAND_ORANGE,
        "accessibleOrange": ACCESSIBLE_ORANGE,
        "brandYellow": BRAND_YELLOW,
        "brandNavy": BRAND_NAVY,
        "navigationBackground": "#000000" if dark else "#FFFFFF",
        "background": DARK_BACKGROUND if dark else BACKGROUND,
        "surface": DARK_SURFACE if dark else "#FFFFFF",
        "surfaceRaised": DARK_SURFACE_RAISED if dark else "#F7F7FA",
        # Chat VR intentionally uses a more immersive, neutral-black stack
        # than the data pages in Dark & Orange. These values mirror the
        # existing Qt Widgets screen instead of inheriting the generic theme.
        "chatBackground": "#0C0C0D" if dark else BACKGROUND,
        "chatSidebar": "#101011" if dark else "#FFFFFF",
        "chatComposer": "#202021" if dark else "#FFFFFF",
        "chatControl": "#2B2B2D" if dark else "#ECECF1",
        "chatBorder": "#38383B" if dark else "#D7D7DF",
        "chatDivider": "#252527" if dark else "#D7D7DF",
        "text": DARK_TEXT if dark else BRAND_NAVY,
        "mutedText": DARK_MUTED if dark else TEXT_MUTED,
        "border": "#2C2823" if dark else "#D7D7DF",
        "hover": "#1D1A17" if dark else "#F1F1F4",
        "selection": "#27272A" if dark else "#E8E8EE",
        "accentSoft": DARK_ACCENT_SOFT if dark else ACCENT_SOFT,
        "focus": "#6D6D76" if dark else "#686875",
        "success": DARK_STATUS_GOOD if dark else STATUS_GOOD,
        "warning": DARK_STATUS_WARN if dark else STATUS_WARN,
        "danger": "#FF7B72" if dark else "#B42318",
        "navText": "#E9E9F0" if dark else BRAND_NAVY,
        "navMuted": "#B8B8C8" if dark else TEXT_MUTED,
        "navHover": "#19191D" if dark else "#F1F1F4",
        "navDivider": "#25252A" if dark else "#D7D7DF",
    }
