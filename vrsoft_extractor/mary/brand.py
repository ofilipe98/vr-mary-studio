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

DARK_BACKGROUND = "#12100F"
DARK_SURFACE = "#1B1816"
DARK_SURFACE_RAISED = "#24201D"
DARK_TEXT = "#E4E4E7"
DARK_MUTED = "#A1A1AA"
DARK_BORDER = "#756A63"
DARK_STATUS_GOOD = "#56D18B"
DARK_STATUS_WARN = "#FFB55C"
DARK_SCROLLBAR_HANDLE = "#8C8077"


def brand_palette(theme_id: str) -> dict[str, str]:
    """Return semantic colors without leaking a widget implementation."""

    dark = theme_id == "dark_orange"
    return {
        "themeId": "dark_orange" if dark else "light",
        "brandOrange": BRAND_ORANGE,
        "accessibleOrange": ACCESSIBLE_ORANGE,
        "brandYellow": BRAND_YELLOW,
        "brandNavy": BRAND_NAVY,
        "navigationBackground": "#000000",
        "background": DARK_BACKGROUND if dark else BACKGROUND,
        "surface": DARK_SURFACE if dark else "#FFFFFF",
        "surfaceRaised": DARK_SURFACE_RAISED if dark else "#FFFFFF",
        # Chat VR intentionally uses a more immersive, neutral-black stack
        # than the data pages in Dark & Orange. These values mirror the
        # existing Qt Widgets screen instead of inheriting the generic theme.
        "chatBackground": "#000000" if dark else BACKGROUND,
        "chatSidebar": "#09090B" if dark else "#FFFFFF",
        "chatComposer": "#141416" if dark else "#FFFFFF",
        "chatControl": "#27272A" if dark else "#ECECF1",
        "chatBorder": "#2A2A2E" if dark else "#D7D7DF",
        "chatDivider": "#202023" if dark else "#D7D7DF",
        "text": DARK_TEXT if dark else BRAND_NAVY,
        "mutedText": DARK_MUTED if dark else TEXT_MUTED,
        "border": "#3A3A40" if dark else "#D7D7DF",
        "hover": "#202023" if dark else "#F1F1F4",
        "selection": "#27272A" if dark else "#E8E8EE",
        "focus": "#6D6D76" if dark else "#686875",
        "success": DARK_STATUS_GOOD if dark else STATUS_GOOD,
        "warning": DARK_STATUS_WARN if dark else STATUS_WARN,
        "danger": "#FF7B72" if dark else "#B42318",
        "navText": "#E9E9F0",
        "navMuted": "#B8B8C8",
        "navHover": "#19191D",
        "navDivider": "#25252A",
    }
