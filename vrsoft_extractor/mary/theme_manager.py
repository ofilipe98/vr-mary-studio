"""Appearance and theme management engine for Harness (VRStudio).

Provides full parity with T3 Code's Settings -> Appearance architecture:
- Appearance modes: 'system' (real-time OS tracking), 'light', 'dark'
- Independent theme selection for light and dark appearances
- Built-in theme library with high-quality dark and light palettes
- Custom themes engine (CRUD, duplicate, export, import)
- Defensive import parser supporting Native Harness, T3 Code, and VS Code themes
- Contrast slider (50%-200%) with dynamic palette border/contrast propagation
- Glass opacity slider (40%-100%) for translucent surfaces
- Motion / Panel animations slider (0ms-400ms) honoring reduce-motion
- Typography: Simple & Advanced modes (Interface, Prompt, Code, Terminal)
- Real installed system font discovery and monospace filtering via QFontDatabase
"""

from __future__ import annotations

from pathlib import Path
import json
import logging
import math
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QSettings
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication

from vrsoft_extractor.mary.brand import (
    brand_palette,
)

logger = logging.getLogger(__name__)

HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# Default values aligned with T3 Code contracts
DEFAULT_APPEARANCE_MODE = "system"
DEFAULT_THEME_LIGHT = "light"
DEFAULT_THEME_DARK = "dark_orange"
DEFAULT_APPEARANCE_CONTRAST = 100  # 50 to 200, step 5
DEFAULT_GLASS_OPACITY = 80         # 40 to 100, step 5
DEFAULT_PANEL_ANIMATION_MS = 0     # 0 to 400, step 25
DEFAULT_TYPOGRAPHY_ADVANCED = False
DEFAULT_INTERFACE_FONT_SIZE = 16   # 12 to 20
DEFAULT_PROMPT_FONT_SIZE = 14      # 12 to 20
DEFAULT_CODE_FONT_SIZE = 13        # 10 to 18
DEFAULT_TERMINAL_FONT_SIZE = 12    # 8 to 20
DEFAULT_WORD_WRAP = True
DEFAULT_FONT_SMOOTHING = True
DEFAULT_ENVIRONMENT_IDENTIFICATION = "pill"


def _clamp(val: int, min_v: int, max_v: int) -> int:
    return max(min_v, min(max_v, int(val)))


def _is_valid_hex(hex_str: str) -> bool:
    return bool(isinstance(hex_str, str) and HEX_COLOR_RE.match(hex_str.strip()))


def _normalize_hex(hex_str: str) -> str:
    s = hex_str.strip()
    if len(s) == 4:  # #RGB -> #RRGGBB
        return f"#{s[1]*2}{s[2]*2}{s[3]*2}".upper()
    return s.upper()


def _color_luminance(hex_str: str) -> float:
    """Relative luminance (0.0 to 1.0) of a hex color."""
    c = QColor(hex_str)
    if not c.isValid():
        return 0.5
    return (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0


def _adjust_contrast(hex_str: str, contrast: int, is_dark: bool, is_border: bool = False, is_text: bool = False) -> str:
    """Adjusts color based on contrast percentage (50% to 200%)."""
    if contrast == 100:
        return hex_str
    c = QColor(hex_str)
    if not c.isValid():
        return hex_str

    if is_border:
        # Boost border contrast when contrast > 100
        if contrast > 100:
            boost = (contrast - 100) / 100.0  # 0.0 to 1.0
            if is_dark:
                # In dark mode, higher contrast makes borders slightly brighter
                factor = 1.0 + (boost * 0.45)
                r = min(255, int(c.red() * factor))
                g = min(255, int(c.green() * factor))
                b = min(255, int(c.blue() * factor))
                return QColor(r, g, b).name()
            else:
                # In light mode, higher contrast makes borders slightly darker
                factor = 1.0 - (boost * 0.35)
                r = max(0, int(c.red() * factor))
                g = max(0, int(c.green() * factor))
                b = max(0, int(c.blue() * factor))
                return QColor(r, g, b).name()
        else:
            # Contrast < 100: fade borders towards background
            fade = (100 - contrast) / 100.0
            if is_dark:
                factor = 1.0 - (fade * 0.5)
                return QColor(max(0, int(c.red() * factor)), max(0, int(c.green() * factor)), max(0, int(c.blue() * factor))).name()
            else:
                factor = 1.0 + (fade * 0.3)
                return QColor(min(255, int(c.red() * factor)), min(255, int(c.green() * factor)), min(255, int(c.blue() * factor))).name()

    if is_text:
        if contrast > 100:
            boost = (contrast - 100) / 100.0
            if is_dark:
                factor = 1.0 + (boost * 0.2)
                return QColor(min(255, int(c.red() * factor)), min(255, int(c.green() * factor)), min(255, int(c.blue() * factor))).name()
            else:
                factor = 1.0 - (boost * 0.2)
                return QColor(max(0, int(c.red() * factor)), max(0, int(c.green() * factor)), max(0, int(c.blue() * factor))).name()

    return hex_str


@dataclass
class ThemeDefinition:
    id: str
    name: str
    appearance: str  # "light" | "dark"
    built_in: bool = True
    palette: dict[str, str] = field(default_factory=dict)
    collection: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "appearance": self.appearance,
            "builtIn": self.built_in,
            "palette": self.palette,
            "collection": self.collection,
        }


def synthesize_palette_from_seed(canvas: str, accent: str, appearance: str) -> dict[str, str]:
    """Synthesizes a complete semantic palette from canvas & accent colors."""
    is_dark = appearance == "dark"
    canvas_col = QColor(canvas)
    accent_col = QColor(accent)

    if is_dark:
        surface_col = canvas_col.lighter(120)
        raised_col = canvas_col.lighter(135)
        border_col = canvas_col.lighter(145)
        text_col = "#e2e8f0"
        muted_col = "#71717a"
        heading_col = "#f8fafc"
    else:
        surface_col = canvas_col.darker(108)
        raised_col = canvas_col.darker(115)
        border_col = canvas_col.darker(120)
        text_col = "#18181b"
        muted_col = "#71717a"
        heading_col = "#09090b"

    return {
        "themeId": "custom",
        "brandOrange": accent_col.name(),
        "accessibleOrange": accent_col.name(),
        "brandYellow": "#eab308",
        "brandNavy": canvas_col.name(),
        "navigationBackground": canvas_col.darker(110).name() if is_dark else surface_col.name(),
        "background": canvas_col.name(),
        "surface": surface_col.name(),
        "surfaceRaised": raised_col.name(),
        "chatBackground": canvas_col.name(),
        "chatSidebar": surface_col.name(),
        "chatComposer": surface_col.name() if is_dark else "#ffffff",
        "chatControl": raised_col.name(),
        "chatBorder": border_col.name(),
        "chatDivider": border_col.name(),
        "messageSurface": surface_col.name(),
        "codeSurface": canvas_col.darker(110).name() if is_dark else surface_col.name(),
        "codeHeader": surface_col.name(),
        "link": accent_col.name(),
        "subtleText": muted_col,
        "headingText": heading_col,
        "inlineCodeSurface": raised_col.name(),
        "quoteSurface": surface_col.name(),
        "text": text_col,
        "mutedText": muted_col,
        "border": border_col.name(),
        "hover": raised_col.name(),
        "selection": raised_col.name(),
        "accentSoft": surface_col.name(),
        "focus": accent_col.name(),
        "success": "#22c55e" if is_dark else "#16a34a",
        "warning": "#eab308" if is_dark else "#ca8a04",
        "danger": "#ef4444" if is_dark else "#dc2626",
        "navText": heading_col,
        "navMuted": muted_col,
        "navHover": raised_col.name(),
        "navDivider": border_col.name(),
    }


# ============================================================================
# Built-in Theme Palettes
# ============================================================================

BUILTIN_THEMES: dict[str, ThemeDefinition] = {
    "dark_orange": ThemeDefinition(
        id="dark_orange",
        name="Dark & Orange",
        appearance="dark",
        built_in=True,
        palette=brand_palette("dark_orange"),
    ),
    "light": ThemeDefinition(
        id="light",
        name="VR Light",
        appearance="light",
        built_in=True,
        palette=brand_palette("light"),
    ),
    "nightfall": ThemeDefinition(
        id="nightfall",
        name="Nightfall",
        appearance="dark",
        built_in=True,
        palette={
            "themeId": "nightfall",
            "brandOrange": "#7aa2f7",
            "accessibleOrange": "#7aa2f7",
            "brandYellow": "#e0af68",
            "brandNavy": "#1a1b26",
            "navigationBackground": "#16161e",
            "background": "#1a1b26",
            "surface": "#1f2335",
            "surfaceRaised": "#24283b",
            "chatBackground": "#16161e",
            "chatSidebar": "#1a1b26",
            "chatComposer": "#1f2335",
            "chatControl": "#24283b",
            "chatBorder": "#292e42",
            "chatDivider": "#24283b",
            "messageSurface": "#24283b",
            "codeSurface": "#16161e",
            "codeHeader": "#1f2335",
            "link": "#7dcfff",
            "subtleText": "#787c99",
            "headingText": "#c0caf5",
            "inlineCodeSurface": "#24283b",
            "quoteSurface": "#1f2335",
            "text": "#a9b1d6",
            "mutedText": "#565f89",
            "border": "#292e42",
            "hover": "#24283b",
            "selection": "#283457",
            "accentSoft": "#283457",
            "focus": "#7aa2f7",
            "success": "#9ece6a",
            "warning": "#e0af68",
            "danger": "#f7768e",
            "navText": "#c0caf5",
            "navMuted": "#787c99",
            "navHover": "#24283b",
            "navDivider": "#292e42",
        },
    ),
    "slate_zinc": ThemeDefinition(
        id="slate_zinc",
        name="Slate & Zinc",
        appearance="dark",
        built_in=True,
        palette={
            "themeId": "slate_zinc",
            "brandOrange": "#38bdf8",
            "accessibleOrange": "#38bdf8",
            "brandYellow": "#facc15",
            "brandNavy": "#0f172a",
            "navigationBackground": "#090d16",
            "background": "#0f172a",
            "surface": "#1e293b",
            "surfaceRaised": "#334155",
            "chatBackground": "#090d16",
            "chatSidebar": "#0f172a",
            "chatComposer": "#1e293b",
            "chatControl": "#334155",
            "chatBorder": "#334155",
            "chatDivider": "#1e293b",
            "messageSurface": "#1e293b",
            "codeSurface": "#090d16",
            "codeHeader": "#1e293b",
            "link": "#38bdf8",
            "subtleText": "#94a3b8",
            "headingText": "#f8fafc",
            "inlineCodeSurface": "#334155",
            "quoteSurface": "#1e293b",
            "text": "#e2e8f0",
            "mutedText": "#64748b",
            "border": "#334155",
            "hover": "#1e293b",
            "selection": "#334155",
            "accentSoft": "#1e293b",
            "focus": "#38bdf8",
            "success": "#4ade80",
            "warning": "#facc15",
            "danger": "#f87171",
            "navText": "#f8fafc",
            "navMuted": "#94a3b8",
            "navHover": "#1e293b",
            "navDivider": "#334155",
        },
    ),
    "github_dark": ThemeDefinition(
        id="github_dark",
        name="GitHub Dark",
        appearance="dark",
        built_in=True,
        palette={
            "themeId": "github_dark",
            "brandOrange": "#58a6ff",
            "accessibleOrange": "#58a6ff",
            "brandYellow": "#d29922",
            "brandNavy": "#0d1117",
            "navigationBackground": "#010409",
            "background": "#0d1117",
            "surface": "#161b22",
            "surfaceRaised": "#21262d",
            "chatBackground": "#010409",
            "chatSidebar": "#0d1117",
            "chatComposer": "#161b22",
            "chatControl": "#21262d",
            "chatBorder": "#30363d",
            "chatDivider": "#21262d",
            "messageSurface": "#161b22",
            "codeSurface": "#010409",
            "codeHeader": "#161b22",
            "link": "#58a6ff",
            "subtleText": "#8b949e",
            "headingText": "#f0f6fc",
            "inlineCodeSurface": "#21262d",
            "quoteSurface": "#161b22",
            "text": "#c9d1d9",
            "mutedText": "#8b949e",
            "border": "#30363d",
            "hover": "#161b22",
            "selection": "#1f6feb",
            "accentSoft": "#161b22",
            "focus": "#58a6ff",
            "success": "#3fb950",
            "warning": "#d29922",
            "danger": "#f85149",
            "navText": "#f0f6fc",
            "navMuted": "#8b949e",
            "navHover": "#161b22",
            "navDivider": "#30363d",
        },
    ),
    "sepia_solar": ThemeDefinition(
        id="sepia_solar",
        name="Warm Sepia",
        appearance="light",
        built_in=True,
        palette={
            "themeId": "sepia_solar",
            "brandOrange": "#b58900",
            "accessibleOrange": "#b58900",
            "brandYellow": "#b58900",
            "brandNavy": "#073642",
            "navigationBackground": "#eee8d5",
            "background": "#fdf6e3",
            "surface": "#eee8d5",
            "surfaceRaised": "#e4dec7",
            "chatBackground": "#fdf6e3",
            "chatSidebar": "#eee8d5",
            "chatComposer": "#ffffff",
            "chatControl": "#e4dec7",
            "chatBorder": "#d3cbaf",
            "chatDivider": "#e4dec7",
            "messageSurface": "#eee8d5",
            "codeSurface": "#fdf6e3",
            "codeHeader": "#eee8d5",
            "link": "#268bd2",
            "subtleText": "#657b83",
            "headingText": "#073642",
            "inlineCodeSurface": "#e4dec7",
            "quoteSurface": "#eee8d5",
            "text": "#586e75",
            "mutedText": "#839496",
            "border": "#d3cbaf",
            "hover": "#eee8d5",
            "selection": "#e4dec7",
            "accentSoft": "#eee8d5",
            "focus": "#b58900",
            "success": "#859900",
            "warning": "#b58900",
            "danger": "#dc322f",
            "navText": "#073642",
            "navMuted": "#657b83",
            "navHover": "#e4dec7",
            "navDivider": "#d3cbaf",
        },
    ),
}

# T3 Code palettes retain their semantic roles instead of approximating every
# surface from two seed colors. The vendored source and license live with the data.
_T3_ROLE_MAP = {
    "background": "canvas", "surface": "surface", "surfaceRaised": "surfaceRaised",
    "brandOrange": "messageAction", "accessibleOrange": "messageAction",
    "brandYellow": "warning", "brandNavy": "chrome", "navigationBackground": "sidebar",
    "chatBackground": "canvas", "chatSidebar": "sidebar", "chatComposer": "surfaceRaised",
    "chatControl": "toolbarControl", "chatBorder": "border", "chatDivider": "border",
    "messageSurface": "messageSurface", "codeSurface": "codeBackground", "codeHeader": "surfaceRaised",
    "link": "messageAction", "subtleText": "textMuted", "headingText": "text",
    "inlineCodeSurface": "accentSurface", "quoteSurface": "surface",
    "text": "text", "mutedText": "textMuted", "border": "border", "hover": "toolbarControlHover",
    "selection": "secondary", "accentSoft": "accentSurface", "focus": "focus",
    "warning": "warning", "danger": "error", "navText": "sidebarForeground",
    "navMuted": "sidebarMutedForeground", "navHover": "sidebarRowHover", "navDivider": "sidebarBorder",
}
_T3_THEME_DATA = json.loads((Path(__file__).parent / "data" / "t3_themes.json").read_text(encoding="utf-8"))["themes"]
for _tid, _spec in _T3_THEME_DATA.items():
    for _mode in ("light", "dark"):
        _colors = _spec[_mode]
        _palette = synthesize_palette_from_seed(_colors["canvas"], _colors["accent"], _mode)
        _palette.update({target: _colors[source] for target, source in _T3_ROLE_MAP.items()})
        _palette.update({"previewCanvas": _colors["canvas"], "previewAccent": _colors["accent"],
                         "previewAction": _colors["messageAction"], "controlBorder": _colors["input"],
                         "mutedSurface": _colors["muted"], "previewSidebar": _colors["sidebar"],
                         "previewMessage": _colors["messageSurface"], "terminalBackground": _colors["terminalBackground"]})
        if _tid == "t3-code":
            # VR Code uses the Studio black/orange identity. Keep the persisted
            # theme IDs compatible with preferences and existing exports.
            _brand = brand_palette("dark_orange" if _mode == "dark" else "light")
            _palette.update(_brand)
            _palette.update({
                "background": _brand["chatBackground"],
                "surface": _brand["chatComposer"],
                "surfaceRaised": _brand["chatControl"],
                "border": _brand["chatBorder"],
                "accessibleOrange": _brand["brandOrange"] if _mode == "dark" else _brand["accessibleOrange"],
                "previewCanvas": _brand["chatBackground"],
                "previewAccent": "#462813" if _mode == "dark" else "#FFE8D6",
                "previewAction": _brand["brandOrange"],
                "previewSidebar": _brand["chatSidebar"],
                "previewMessage": _brand["messageSurface"],
                "controlBorder": _brand["chatBorder"],
                "mutedSurface": _brand["chatControl"],
                "terminalBackground": _brand["chatBackground"],
            })
        _id = f"{_tid}-light" if _mode == "light" else _tid
        _palette["themeId"] = _id
        _name = {"t3-code": "VR Code", "t3-chat": "VR Chat"}.get(_tid, _spec["name"])
        BUILTIN_THEMES[_id] = ThemeDefinition(id=_id, name=_name, appearance=_mode,
                                             built_in=True, palette=_palette)


# ============================================================================
# Theme Importer & Defensive Parser
# ============================================================================

def _t3_color(value: str) -> str:
    """Convert T3's opaque OKLCH tokens into Qt's sRGB palette colors."""
    if _is_valid_hex(value):
        return _normalize_hex(value)
    match = re.fullmatch(r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s*\)", value)
    if not match:
        raise ValueError(f"Cor de tema inválida: {value}")
    lightness, chroma, hue = map(float, match.groups())
    if not (0 <= lightness <= 1 and 0 <= chroma <= 1 and math.isfinite(hue)):
        raise ValueError(f"Cor OKLCH fora dos limites: {value}")
    a, b = chroma * math.cos(math.radians(hue)), chroma * math.sin(math.radians(hue))
    l = (lightness + .3963377774 * a + .2158037573 * b) ** 3
    m = (lightness - .1055613458 * a - .0638541728 * b) ** 3
    s = (lightness - .0894841775 * a - 1.291485548 * b) ** 3
    rgb = (4.0767416621*l - 3.3077115913*m + .2309699292*s,
           -1.2684380046*l + 2.6097574011*m - .3413193965*s,
           -.0041960863*l - .7034186147*m + 1.707614701*s)
    def byte(channel: float) -> int:
        srgb = 12.92 * channel if channel <= .0031308 else 1.055 * channel ** (1/2.4) - .055
        return round(max(0, min(1, srgb)) * 255)
    return "#" + "".join(f"{byte(channel):02x}" for channel in rgb)


def parse_imported_theme(raw_json: str) -> tuple[bool, str, ThemeDefinition | None]:
    """Defensively parses theme JSON supporting Harness Native, T3 Code, and VS Code schemas."""
    try:
        data = json.loads(raw_json)
    except Exception as exc:
        return False, f"JSON inválido: {exc}", None

    if not isinstance(data, dict):
        return False, "O conteúdo do tema deve ser um objeto JSON.", None

    name = str(data.get("name") or data.get("label") or "").strip()
    if not name:
        name = "Tema Importado"

    theme_id = re.sub(r"[^a-zA-Z0-9_]+", "_", name.lower()).strip("_") or "custom_theme"

    # Schema 1: Native Harness Theme JSON
    if "palette" in data and isinstance(data["palette"], dict):
        appearance = str(data.get("appearance", "")).lower()
        if appearance not in ("light", "dark"):
            # Detect by background luminance
            bg = data["palette"].get("background", "#141416")
            appearance = "light" if _color_luminance(bg) > 0.5 else "dark"
        supplied = data["palette"]
        if any(not _is_valid_hex(str(value)) for key, value in supplied.items() if key != "themeId"):
            return False, "A paleta contém uma cor inválida.", None
        palette = synthesize_palette_from_seed(
            supplied.get("background", "#141416" if appearance == "dark" else "#ffffff"),
            supplied.get("accessibleOrange", supplied.get("brandOrange", "#ff7a00")), appearance)
        palette.update(supplied)
        palette["themeId"] = theme_id
        theme_def = ThemeDefinition(id=theme_id, name=name, appearance=appearance, built_in=False,
                                    palette=palette, collection=str(data.get("collection") or ""))
        return True, "Tema Harness nativo importado com sucesso.", theme_def

    # Current T3 exports put semantic colors under `colors`, in OKLCH or hex.
    t3_colors = data.get("colors")
    if isinstance(t3_colors, dict) and "canvas" in t3_colors:
        try:
            colors = {key: _t3_color(str(value)) for key, value in t3_colors.items()}
            appearance = str(data.get("appearance", "dark"))
            if appearance not in ("light", "dark"):
                raise ValueError("Aparência de tema inválida.")
            palette = synthesize_palette_from_seed(colors["canvas"], colors["accent"], appearance)
            palette.update({target: colors[source] for target, source in _T3_ROLE_MAP.items() if source in colors})
            palette.update(previewCanvas=colors["canvas"], previewAccent=colors["accent"],
                           previewAction=colors.get("messageAction", colors["accent"]), themeId=theme_id)
        except (ValueError, KeyError) as exc:
            return False, f"Tema T3 Code inválido: {exc}", None
        return True, "Tema T3 Code importado com sucesso.", ThemeDefinition(
            id=theme_id, name=name, appearance=appearance, built_in=False, palette=palette)

    # Schema 2: T3 Code Theme JSON ("canvas", "accent", optional "colors")
    if "canvas" in data and "accent" in data:
        canvas = str(data["canvas"]).strip()
        accent = str(data["accent"]).strip()
        if not _is_valid_hex(canvas) or not _is_valid_hex(accent):
            return False, "Cores 'canvas' ou 'accent' inválidas no formato T3 Code.", None
        appearance = str(data.get("appearance", "")).lower()
        if appearance not in ("light", "dark"):
            appearance = "light" if _color_luminance(canvas) > 0.5 else "dark"
        palette = synthesize_palette_from_seed(canvas, accent, appearance)
        # Apply color overrides if provided
        colors_override = data.get("colors")
        if isinstance(colors_override, dict):
            for k, v in colors_override.items():
                if _is_valid_hex(str(v)):
                    if k in palette:
                        palette[k] = str(v)
                    elif k == "error":
                        palette["danger"] = str(v)
                    elif k == "warning":
                        palette["warning"] = str(v)
                    elif k == "terminalSelection":
                        palette["selection"] = str(v)
        palette["themeId"] = theme_id
        theme_def = ThemeDefinition(id=theme_id, name=name, appearance=appearance, built_in=False, palette=palette)
        return True, "Tema T3 Code importado com sucesso.", theme_def

    # Schema 3: VS Code Theme JSON ("colors" dictionary with token mappings)
    if "colors" in data and isinstance(data["colors"], dict):
        vscode_colors = data["colors"]
        theme_type = str(data.get("type", "")).lower()
        editor_bg = str(vscode_colors.get("editor.background", "")).strip()
        if not _is_valid_hex(editor_bg):
            editor_bg = "#1e1e1e" if "light" not in theme_type else "#ffffff"
        appearance = "light" if ("light" in theme_type or _color_luminance(editor_bg) > 0.5) else "dark"
        accent = str(
            vscode_colors.get("activityBarBadge.background")
            or vscode_colors.get("focusBorder")
            or vscode_colors.get("button.background")
            or "#ff7a00"
        ).strip()
        if not _is_valid_hex(accent):
            accent = "#ff7a00" if appearance == "dark" else "#007acc"
        palette = synthesize_palette_from_seed(editor_bg, accent, appearance)
        # Map specific VS Code keys if present
        if _is_valid_hex(vscode_colors.get("sideBar.background", "")):
            palette["surface"] = str(vscode_colors["sideBar.background"])
            palette["chatSidebar"] = palette["surface"]
        if _is_valid_hex(vscode_colors.get("editor.foreground", "")):
            palette["text"] = str(vscode_colors["editor.foreground"])
        if _is_valid_hex(vscode_colors.get("sideBar.border", "")):
            palette["border"] = str(vscode_colors["sideBar.border"])
            palette["chatBorder"] = palette["border"]

        palette["themeId"] = theme_id
        theme_def = ThemeDefinition(id=theme_id, name=name, appearance=appearance, built_in=False, palette=palette)
        return True, "Tema VS Code importado com sucesso.", theme_def

    return False, "Formato de tema não reconhecido. Certifique-se de usar JSON nativo, T3 Code ou VS Code.", None


# ============================================================================
# ThemeManager QObject
# ============================================================================

class ThemeManager(QObject):
    """Core theme and appearance management engine for Harness."""

    themeChanged = Signal()
    appearanceModeChanged = Signal()
    resolvedAppearanceChanged = Signal()
    themesListChanged = Signal()
    contrastChanged = Signal()
    glassOpacityChanged = Signal()
    motionChanged = Signal()
    typographyChanged = Signal()
    themeImportStatus = Signal(bool, str)  # success, message
    environmentIdentificationChanged = Signal()

    def __init__(self, preferences: QSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._preferences = preferences
        self._custom_themes: dict[str, ThemeDefinition] = {}
        self._palette_cache: dict[str, str] | None = None
        self._system_dark: bool = False

        # Load preferences
        self._load_preferences()

        # Connect system theme tracking
        self._setup_system_theme_listener()

    def _load_preferences(self) -> None:
        p = self._preferences

        # Appearance mode: system | light | dark
        saved_mode = p.value("appearance/appearance_mode", None)
        if saved_mode in ("system", "light", "dark"):
            self._appearance_mode = saved_mode
        else:
            # Migration from legacy appearance/theme
            legacy_theme = p.value("appearance/theme", "dark_orange")
            if legacy_theme == "light":
                self._appearance_mode = "light"
            elif legacy_theme == "dark_orange":
                self._appearance_mode = "dark"
            else:
                self._appearance_mode = DEFAULT_APPEARANCE_MODE

        self._theme_light = str(p.value("appearance/theme_light", DEFAULT_THEME_LIGHT))
        self._theme_dark = str(p.value("appearance/theme_dark", DEFAULT_THEME_DARK))

        self._appearance_contrast = _clamp(
            int(p.value("appearance/appearance_contrast", DEFAULT_APPEARANCE_CONTRAST) or DEFAULT_APPEARANCE_CONTRAST),
            50, 200,
        )
        self._glass_opacity = _clamp(
            int(p.value("appearance/glass_opacity", DEFAULT_GLASS_OPACITY) or DEFAULT_GLASS_OPACITY),
            40, 100,
        )
        self._panel_animation_duration_ms = _clamp(
            int(p.value("appearance/panel_animation_duration_ms", DEFAULT_PANEL_ANIMATION_MS) or DEFAULT_PANEL_ANIMATION_MS),
            0, 400,
        )
        self._typography_advanced = bool(
            p.value("appearance/typography_advanced", DEFAULT_TYPOGRAPHY_ADVANCED) in (True, "true", "1", 1)
        )
        self._font_family_interface = str(p.value("appearance/interface_font_family", "Segoe UI") or "Segoe UI")
        self._font_size_interface = _clamp(
            int(p.value("appearance/interface_font_size", DEFAULT_INTERFACE_FONT_SIZE) or DEFAULT_INTERFACE_FONT_SIZE),
            11, 22,
        )
        self._font_family_prompt = str(p.value("appearance/prompt_font_family", "") or "")
        self._font_size_prompt = _clamp(
            int(p.value("appearance/prompt_font_size", DEFAULT_PROMPT_FONT_SIZE) or DEFAULT_PROMPT_FONT_SIZE),
            12, 20,
        )
        self._font_family_code = str(p.value("appearance/monospace_font_family", "Consolas") or "Consolas")
        self._font_size_code = _clamp(
            int(p.value("appearance/monospace_font_size", DEFAULT_CODE_FONT_SIZE) or DEFAULT_CODE_FONT_SIZE),
            10, 20,
        )
        self._font_family_terminal = str(p.value("appearance/terminal_font_family", "") or "")
        self._font_size_terminal = _clamp(
            int(p.value("appearance/terminal_font_size", DEFAULT_TERMINAL_FONT_SIZE) or DEFAULT_TERMINAL_FONT_SIZE),
            8, 20,
        )
        self._font_smoothing = bool(
            p.value("appearance/font_smoothing", DEFAULT_FONT_SMOOTHING) in (True, "true", "1", 1)
        )
        self._environment_identification = str(
            p.value("appearance/environment_identification", DEFAULT_ENVIRONMENT_IDENTIFICATION) or DEFAULT_ENVIRONMENT_IDENTIFICATION
        )
        self._word_wrap = bool(
            p.value("appearance/word_wrap", DEFAULT_WORD_WRAP) in (True, "true", "1", 1)
        )
        self._reduce_motion = bool(
            p.value("appearance/reduce_motion", False) in (True, "true", "1", 1)
        )

        # Load custom themes from storage
        raw_custom = p.value("appearance/custom_themes_json", "")
        if raw_custom and isinstance(raw_custom, str):
            try:
                saved_themes = json.loads(raw_custom)
                if isinstance(saved_themes, list):
                    for item in saved_themes:
                        if isinstance(item, dict) and "id" in item and "name" in item:
                            t = ThemeDefinition(
                                id=item["id"],
                                name=item["name"],
                                appearance=item.get("appearance", "dark"),
                                built_in=False,
                                palette=item.get("palette", {}),
                                collection=str(item.get("collection") or ""),
                            )
                            self._custom_themes[t.id] = t
            except Exception as e:
                logger.warning("Could not load custom themes from storage: %s", e)

    def _setup_system_theme_listener(self) -> None:
        app = QGuiApplication.instance()
        if app and hasattr(app, "styleHints"):
            style_hints = app.styleHints()
            self._update_system_dark()
            if hasattr(style_hints, "colorSchemeChanged"):
                try:
                    style_hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)
                except Exception as e:
                    logger.debug("Failed connecting colorSchemeChanged: %s", e)

    def _update_system_dark(self) -> bool:
        app = QGuiApplication.instance()
        if app and hasattr(app, "styleHints"):
            try:
                self._system_dark = (app.styleHints().colorScheme() == Qt.ColorScheme.Dark)
            except Exception:
                self._system_dark = True
        return self._system_dark

    def _on_system_color_scheme_changed(self) -> None:
        old_dark = self._system_dark
        self._update_system_dark()
        if self._system_dark != old_dark and self._appearance_mode == "system":
            self._palette_cache = None
            self.resolvedAppearanceChanged.emit()
            self.themeChanged.emit()

    # ------------------------------------------------------------------------
    # Appearance & Resolution Properties
    # ------------------------------------------------------------------------

    @Property(str, notify=appearanceModeChanged)
    def appearanceMode(self) -> str:  # noqa: N802
        return self._appearance_mode

    @Property(str, notify=resolvedAppearanceChanged)
    def resolvedAppearance(self) -> str:  # noqa: N802
        if self._appearance_mode == "light":
            return "light"
        elif self._appearance_mode == "dark":
            return "dark"
        else:
            self._update_system_dark()
            return "dark" if self._system_dark else "light"

    @Property(str, notify=themeChanged)
    def themeLight(self) -> str:  # noqa: N802
        return self._theme_light

    @Property(str, notify=themeChanged)
    def themeDark(self) -> str:  # noqa: N802
        return self._theme_dark

    @Property(str, notify=themeChanged)
    def activeThemeId(self) -> str:  # noqa: N802
        if self.resolvedAppearance == "light":
            return self._theme_light if self._get_theme(self._theme_light) else DEFAULT_THEME_LIGHT
        else:
            return self._theme_dark if self._get_theme(self._theme_dark) else DEFAULT_THEME_DARK

    @Property(str, notify=themeChanged)
    def themeId(self) -> str:  # noqa: N802
        """Compatibility property matching legacy bridge."""
        return self.activeThemeId

    def _get_theme(self, theme_id: str) -> ThemeDefinition | None:
        if theme_id in BUILTIN_THEMES:
            return BUILTIN_THEMES[theme_id]
        if theme_id in self._custom_themes:
            return self._custom_themes[theme_id]
        return None

    @Property("QVariantMap", notify=themeChanged)
    def palette(self) -> dict[str, str]:
        if self._palette_cache is not None:
            return self._palette_cache

        theme = self._get_theme(self.activeThemeId)
        if theme is None:
            theme = BUILTIN_THEMES[DEFAULT_THEME_DARK if self.resolvedAppearance == "dark" else DEFAULT_THEME_LIGHT]

        base_palette = dict(theme.palette)
        is_dark = theme.appearance == "dark"

        # Apply contrast adjustments
        if self._appearance_contrast != 100:
            for k, v in list(base_palette.items()):
                if not isinstance(v, str) or not v.startswith("#"):
                    continue
                is_border = "border" in k.lower() or "divider" in k.lower()
                is_text = "text" in k.lower() or "heading" in k.lower() or "muted" in k.lower()
                base_palette[k] = _adjust_contrast(v, self._appearance_contrast, is_dark, is_border, is_text)

        base_palette["themeId"] = theme.id
        self._palette_cache = base_palette
        return base_palette

    # ------------------------------------------------------------------------
    # Sliders: Contrast, Glass Opacity, Motion
    # ------------------------------------------------------------------------

    @Property(int, notify=contrastChanged)
    def appearanceContrast(self) -> int:  # noqa: N802
        return self._appearance_contrast

    @Property(int, notify=glassOpacityChanged)
    def glassOpacity(self) -> int:  # noqa: N802
        return self._glass_opacity

    @Property(str, notify=environmentIdentificationChanged)
    def environmentIdentification(self) -> str:  # noqa: N802
        return self._environment_identification

    @Slot(str)
    def setEnvironmentIdentification(self, mode: str) -> None:  # noqa: N802
        if mode not in ("pill", "artwork", "none") or mode == self._environment_identification:
            return
        self._environment_identification = mode
        self._preferences.setValue("appearance/environment_identification", mode)
        self._preferences.sync()
        self.environmentIdentificationChanged.emit()

    @Property(int, notify=motionChanged)
    def panelAnimationDurationMs(self) -> int:  # noqa: N802
        return 0 if self._reduce_motion else self._panel_animation_duration_ms

    @Property(int, notify=motionChanged)
    def rawPanelAnimationDurationMs(self) -> int:  # noqa: N802
        return self._panel_animation_duration_ms

    @Property(bool, notify=motionChanged)
    def reduceMotion(self) -> bool:  # noqa: N802
        return self._reduce_motion

    # ------------------------------------------------------------------------
    # Typography Properties
    # ------------------------------------------------------------------------

    @Property(bool, notify=typographyChanged)
    def typographyAdvanced(self) -> bool:  # noqa: N802
        return self._typography_advanced

    @Property(str, notify=typographyChanged)
    def interfaceFontFamily(self) -> str:  # noqa: N802
        return self._font_family_interface

    @Property(int, notify=typographyChanged)
    def interfaceFontSize(self) -> int:  # noqa: N802
        return self._font_size_interface

    @Property(str, notify=typographyChanged)
    def promptFontFamily(self) -> str:  # noqa: N802
        return (self._font_family_prompt if self._typography_advanced else "") or self._font_family_interface

    @Property(int, notify=typographyChanged)
    def promptFontSize(self) -> int:  # noqa: N802
        return self._font_size_prompt if self._typography_advanced else self._font_size_interface

    @Property(str, notify=typographyChanged)
    def monospaceFontFamily(self) -> str:  # noqa: N802
        return self._font_family_code

    @Property(str, notify=typographyChanged)
    def codeFontFamily(self) -> str:  # noqa: N802
        return self._font_family_code

    @Property(int, notify=typographyChanged)
    def monospaceFontSize(self) -> int:  # noqa: N802
        return self._font_size_code

    @Property(int, notify=typographyChanged)
    def codeFontSize(self) -> int:  # noqa: N802
        return self._font_size_code

    @Property(str, notify=typographyChanged)
    def terminalFontFamily(self) -> str:  # noqa: N802
        return (self._font_family_terminal if self._typography_advanced else "") or self._font_family_code

    @Property(int, notify=typographyChanged)
    def terminalFontSize(self) -> int:  # noqa: N802
        return self._font_size_terminal if self._typography_advanced else self._font_size_code

    @Property(bool, notify=typographyChanged)
    def fontSmoothing(self) -> bool:  # noqa: N802
        return self._font_smoothing

    @Property(bool, notify=typographyChanged)
    def isMacOS(self) -> bool:  # noqa: N802
        return sys.platform == "darwin"

    @Property(bool, notify=typographyChanged)
    def wordWrap(self) -> bool:  # noqa: N802
        return self._word_wrap

    # ------------------------------------------------------------------------
    # Collections & Font Discovery
    # ------------------------------------------------------------------------

    @Property("QVariantList", notify=themesListChanged)
    def availableThemes(self) -> list[dict[str, Any]]:  # noqa: N802
        result = [t.to_dict() for t in BUILTIN_THEMES.values()]
        result.extend(t.to_dict() for t in self._custom_themes.values())
        return result

    @Property("QVariantList", constant=True)
    def systemFontFamilies(self) -> list[str]:  # noqa: N802
        try:
            return sorted(set(QFontDatabase.families()))
        except Exception:
            return ["Segoe UI", "Arial", "Consolas", "Courier New"]

    @Property("QVariantList", constant=True)
    def monospaceFontFamilies(self) -> list[str]:  # noqa: N802
        try:
            families = QFontDatabase.families()
            mono = [f for f in families if QFontDatabase.isFixedPitch(f)]
            return sorted(set(mono)) if mono else ["Consolas", "Courier New"]
        except Exception:
            return ["Consolas", "Cascadia Code", "Courier New"]

    # ------------------------------------------------------------------------
    # Slots: Setting Updaters
    # ------------------------------------------------------------------------

    @Slot(str)
    def setAppearanceMode(self, mode: str) -> None:  # noqa: N802
        if mode not in ("system", "light", "dark") or mode == self._appearance_mode:
            return
        self._appearance_mode = mode
        self._preferences.setValue("appearance/appearance_mode", mode)
        self._preferences.sync()
        self._palette_cache = None
        self.appearanceModeChanged.emit()
        self.resolvedAppearanceChanged.emit()
        self.themeChanged.emit()

    @Slot(str, str)
    def setThemeForAppearance(self, appearance: str, theme_id: str) -> None:  # noqa: N802
        resolved_id = theme_id
        if appearance == "light" and f"{theme_id}-light" in BUILTIN_THEMES:
            resolved_id = f"{theme_id}-light"
        elif appearance == "dark" and theme_id.endswith("-light") and theme_id[:-6] in BUILTIN_THEMES:
            resolved_id = theme_id[:-6]

        theme = BUILTIN_THEMES.get(resolved_id) or self._custom_themes.get(resolved_id) or self._get_theme(resolved_id)
        if not theme or theme.appearance != appearance:
            return
        if appearance == "light":
            if self._theme_light == resolved_id:
                return
            self._theme_light = resolved_id
            self._preferences.setValue("appearance/theme_light", resolved_id)
        elif appearance == "dark":
            if self._theme_dark == resolved_id:
                return
            self._theme_dark = resolved_id
            self._preferences.setValue("appearance/theme_dark", resolved_id)
        else:
            return

        self._preferences.sync()
        self._palette_cache = None
        self.themeChanged.emit()

    @Slot(str)
    def setTheme(self, theme_id: str) -> None:  # noqa: N802
        """Compatibility slot: applies theme to current resolved appearance."""
        theme = self._get_theme(theme_id)
        if not theme:
            theme_id = "dark_orange" if theme_id == "dark_orange" else "light"
            theme = self._get_theme(theme_id)
        if not theme:
            return
        self.setThemeForAppearance(theme.appearance, theme.id)
        if theme.appearance == "light" and self._appearance_mode == "dark":
            self.setAppearanceMode("light")
        elif theme.appearance == "dark" and self._appearance_mode == "light":
            self.setAppearanceMode("dark")

    @Slot(int)
    def setAppearanceContrast(self, contrast: int) -> None:  # noqa: N802
        val = _clamp(contrast, 50, 200)
        if val == self._appearance_contrast:
            return
        self._appearance_contrast = val
        self._preferences.setValue("appearance/appearance_contrast", val)
        self._preferences.sync()
        self._palette_cache = None
        self.contrastChanged.emit()
        self.themeChanged.emit()

    @Slot(int)
    def setGlassOpacity(self, opacity: int) -> None:  # noqa: N802
        val = _clamp(opacity, 40, 100)
        if val == self._glass_opacity:
            return
        self._glass_opacity = val
        self._preferences.setValue("appearance/glass_opacity", val)
        self._preferences.sync()
        self.glassOpacityChanged.emit()

    @Slot(int)
    def setPanelAnimationDurationMs(self, duration_ms: int) -> None:  # noqa: N802
        val = _clamp(duration_ms, 0, 400)
        if val == self._panel_animation_duration_ms:
            return
        self._panel_animation_duration_ms = val
        self._preferences.setValue("appearance/panel_animation_duration_ms", val)
        self._preferences.sync()
        self.motionChanged.emit()

    @Slot(bool)
    def setReduceMotion(self, enabled: bool) -> None:  # noqa: N802
        val = bool(enabled)
        if val == self._reduce_motion:
            return
        self._reduce_motion = val
        self._preferences.setValue("appearance/reduce_motion", val)
        self._preferences.sync()
        self.motionChanged.emit()

    @Slot(bool)
    def setTypographyAdvanced(self, advanced: bool) -> None:  # noqa: N802
        val = bool(advanced)
        if val == self._typography_advanced:
            return
        self._typography_advanced = val
        self._preferences.setValue("appearance/typography_advanced", val)
        self._preferences.sync()
        self.typographyChanged.emit()

    @Slot(str, int)
    def setInterfaceTypography(self, family: str, size: int) -> None:  # noqa: N802
        fam = family.strip() if family else "Segoe UI"
        s = _clamp(size, 11, 22)
        if fam == self._font_family_interface and s == self._font_size_interface:
            return
        self._font_family_interface = fam
        self._font_size_interface = s
        self._preferences.setValue("appearance/interface_font_family", fam)
        self._preferences.setValue("appearance/interface_font_size", s)
        self._preferences.sync()
        self.typographyChanged.emit()

    @Slot(str, int)
    def setPromptTypography(self, family: str, size: int) -> None:  # noqa: N802
        fam = family.strip()
        s = _clamp(size, 12, 20)
        self._font_family_prompt = fam
        self._font_size_prompt = s
        self._preferences.setValue("appearance/prompt_font_family", fam)
        self._preferences.setValue("appearance/prompt_font_size", s)
        self._preferences.sync()
        self.typographyChanged.emit()

    @Slot(str, int)
    def setCodeTypography(self, family: str, size: int) -> None:  # noqa: N802
        fam = family.strip() if family else "Consolas"
        s = _clamp(size, 10, 20)
        self._font_family_code = fam
        self._font_size_code = s
        self._preferences.setValue("appearance/monospace_font_family", fam)
        self._preferences.setValue("appearance/monospace_font_size", s)
        self._preferences.sync()
        self.typographyChanged.emit()

    @Slot(str, int)
    def setTerminalTypography(self, family: str, size: int) -> None:  # noqa: N802
        fam = family.strip()
        s = _clamp(size, 8, 20)
        self._font_family_terminal = fam
        self._font_size_terminal = s
        self._preferences.setValue("appearance/terminal_font_family", fam)
        self._preferences.setValue("appearance/terminal_font_size", s)
        self._preferences.sync()
        self.typographyChanged.emit()

    @Slot(bool)
    def setFontSmoothing(self, enabled: bool) -> None:  # noqa: N802
        val = bool(enabled)
        if val == self._font_smoothing:
            return
        self._font_smoothing = val
        self._preferences.setValue("appearance/font_smoothing", val)
        self._preferences.sync()
        self.typographyChanged.emit()

    @Slot(bool)
    def setWordWrap(self, enabled: bool) -> None:  # noqa: N802
        val = bool(enabled)
        if val == self._word_wrap:
            return
        self._word_wrap = val
        self._preferences.setValue("appearance/word_wrap", val)
        self._preferences.sync()
        self.typographyChanged.emit()

    @Slot(str)
    def resetSetting(self, setting_name: str) -> None:  # noqa: N802
        if setting_name == "contrast":
            self.setAppearanceContrast(DEFAULT_APPEARANCE_CONTRAST)
        elif setting_name == "glass":
            self.setGlassOpacity(DEFAULT_GLASS_OPACITY)
        elif setting_name == "motion":
            self.setPanelAnimationDurationMs(DEFAULT_PANEL_ANIMATION_MS)
        elif setting_name == "interfaceFont":
            self.setInterfaceTypography("Segoe UI", DEFAULT_INTERFACE_FONT_SIZE)
        elif setting_name == "promptFont":
            self.setPromptTypography("", DEFAULT_PROMPT_FONT_SIZE)
        elif setting_name == "codeFont":
            self.setCodeTypography("Consolas", DEFAULT_CODE_FONT_SIZE)
        elif setting_name == "terminalFont":
            self.setTerminalTypography("", DEFAULT_TERMINAL_FONT_SIZE)
        elif setting_name == "wordWrap":
            self.setWordWrap(DEFAULT_WORD_WRAP)
        elif setting_name in ("environment", "environmentIdentification"):
            self.setEnvironmentIdentification(DEFAULT_ENVIRONMENT_IDENTIFICATION)

    # ------------------------------------------------------------------------
    # Custom Themes CRUD
    # ------------------------------------------------------------------------

    def _save_custom_themes_to_storage(self) -> None:
        serialized = [t.to_dict() for t in self._custom_themes.values()]
        self._preferences.setValue("appearance/custom_themes_json", json.dumps(serialized))
        self._preferences.sync()
        self.themesListChanged.emit()

    @Slot(str, str, str, result=str)
    def createCustomTheme(self, name: str, appearance: str, seed_theme_id: str) -> str:  # noqa: N802
        seed = self._get_theme(seed_theme_id)
        if not seed:
            seed = BUILTIN_THEMES[DEFAULT_THEME_DARK if appearance == "dark" else DEFAULT_THEME_LIGHT]

        base_id = re.sub(r"[^a-zA-Z0-9_]+", "_", name.lower()).strip("_") or "custom"
        unique_id = base_id
        counter = 1
        while unique_id in BUILTIN_THEMES or unique_id in self._custom_themes:
            unique_id = f"{base_id}_{counter}"
            counter += 1

        new_palette = dict(seed.palette)
        new_palette["themeId"] = unique_id

        theme = ThemeDefinition(
            id=unique_id,
            name=name.strip() or "Novo Tema",
            appearance="dark" if appearance == "dark" else "light",
            built_in=False,
            palette=new_palette,
        )
        self._custom_themes[unique_id] = theme
        self._save_custom_themes_to_storage()
        return unique_id

    @Slot(str, str, str, "QVariantMap", result=bool)
    def updateCustomTheme(self, theme_id: str, name: str, appearance: str, palette_map: dict[str, Any]) -> bool:  # noqa: N802
        if theme_id not in self._custom_themes:
            return False
        theme = self._custom_themes[theme_id]
        was_active = self.activeThemeId == theme_id
        theme.name = name.strip() or theme.name
        theme.appearance = "dark" if appearance == "dark" else "light"
        new_palette = dict(theme.palette)
        for k, v in palette_map.items():
            if _is_valid_hex(str(v)):
                new_palette[k] = _normalize_hex(str(v))
        linked_roles = {
            "background": ("chatBackground", "terminalBackground", "previewCanvas"),
            "surface": ("chatComposer", "codeHeader", "messageSurface", "quoteSurface"),
            "border": ("chatBorder", "chatDivider", "controlBorder"),
            "text": ("headingText", "navText"),
            "mutedText": ("subtleText", "navMuted"),
            "accessibleOrange": ("brandOrange", "focus", "link", "previewAccent", "previewAction"),
        }
        for role, linked in linked_roles.items():
            if new_palette.get(role) != theme.palette.get(role):
                for key in linked:
                    new_palette[key] = new_palette[role]
        new_palette["themeId"] = theme_id
        theme.palette = new_palette
        if self._theme_light == theme_id and theme.appearance != "light":
            self.setThemeForAppearance("light", DEFAULT_THEME_LIGHT)
        if self._theme_dark == theme_id and theme.appearance != "dark":
            self.setThemeForAppearance("dark", DEFAULT_THEME_DARK)
        self._save_custom_themes_to_storage()

        if was_active or self.activeThemeId == theme_id:
            self._palette_cache = None
            self.themeChanged.emit()
        return True

    @Slot(str, str, result=str)
    def duplicateTheme(self, theme_id: str, new_name: str) -> str:  # noqa: N802
        source = self._get_theme(theme_id)
        if not source:
            return ""
        label = new_name.strip() or f"{source.name} (Cópia)"
        payload = json.loads(self.exportThemeJson(source.id))
        payload["name"] = label
        return self.importThemeJson(json.dumps(payload))["themeId"]

    @Slot(str, result=bool)
    def deleteCustomTheme(self, theme_id: str) -> bool:  # noqa: N802
        if theme_id not in self._custom_themes:
            return False

        # Fallback if the active theme was this custom theme
        if self._theme_light == theme_id:
            self.setThemeForAppearance("light", DEFAULT_THEME_LIGHT)
        if self._theme_dark == theme_id:
            self.setThemeForAppearance("dark", DEFAULT_THEME_DARK)

        del self._custom_themes[theme_id]
        self._save_custom_themes_to_storage()
        return True

    @Slot(str, result=str)
    def exportThemeJson(self, theme_id: str) -> str:  # noqa: N802
        theme = self._get_theme(theme_id)
        if not theme:
            return "{}"
        payload = {
            "version": 1,
            "id": theme.id,
            "name": theme.name,
            "appearance": theme.appearance,
            "palette": theme.palette,
            "collection": theme.collection,
        }
        related = []
        if theme.collection:
            related = [t for t in self._custom_themes.values() if t.collection == theme.collection]
        else:
            base_id = theme.id.removesuffix("-light")
            if base_id in _T3_THEME_DATA:
                related = [BUILTIN_THEMES[base_id], BUILTIN_THEMES[base_id + "-light"]]
        variants = {t.appearance: {"palette": t.palette} for t in related if t.appearance != theme.appearance}
        if variants:
            payload["variants"] = variants
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @Slot(str, result="QVariantMap")
    def importThemeJson(self, json_string: str) -> dict[str, Any]:  # noqa: N802
        success, msg, theme = parse_imported_theme(json_string)
        if not success or not theme:
            self.themeImportStatus.emit(False, msg)
            return {"success": False, "message": msg, "themeId": ""}

        # Validate every exported variant before persisting any of the import.
        data = json.loads(json_string)
        themes = [theme]
        variants = data.get("variants", {})
        if not isinstance(variants, dict):
            return {"success": False, "message": "Variantes de tema inválidas.", "themeId": ""}
        for mode, colors in variants.items():
            if mode not in ("light", "dark") or not isinstance(colors, dict) or not ({"canvas", "palette"} & colors.keys()):
                return {"success": False, "message": "Variante T3 Code inválida.", "themeId": ""}
            if mode == theme.appearance:
                continue
            variant_data = {"label": theme.name, "appearance": mode}
            if "palette" in colors:
                variant_data["palette"] = colors["palette"]
            else:
                variant_data["colors"] = colors
            ok, message, variant = parse_imported_theme(json.dumps(variant_data))
            if not ok or not variant:
                return {"success": False, "message": message, "themeId": ""}
            variant.id += "_" + mode
            themes.append(variant)
        reserved = set(BUILTIN_THEMES) | set(self._custom_themes)
        for imported in themes:
            base_id, counter = imported.id, 1
            while imported.id in reserved:
                imported.id = f"{base_id}_{counter}"
                counter += 1
            imported.palette["themeId"] = imported.id
            reserved.add(imported.id)
        for imported in themes:
            imported.collection = theme.id if len(themes) > 1 else ""
            self._custom_themes[imported.id] = imported
        self._save_custom_themes_to_storage()
        self.themeImportStatus.emit(True, f"Tema '{theme.name}' importado com sucesso.")
        return {"success": True, "message": f"Tema '{theme.name}' importado com sucesso.", "themeId": theme.id}

    @Slot(str, result=bool)
    def isMonospace(self, family_name: str) -> bool:  # noqa: N802
        try:
            return QFontDatabase.isFixedPitch(family_name)
        except Exception:
            return False

    @Slot(str, result=bool)
    def isFontAvailable(self, family_name: str) -> bool:  # noqa: N802
        try:
            return family_name in QFontDatabase.families()
        except Exception:
            return False
