pragma Singleton

import QtQuick

QtObject {
    // Convert the Python QVariantMap once per theme change, not per hover.
    readonly property var palette: frontend.palette
    readonly property string fontFamily: (frontend && frontend.effectiveInterfaceFontFamily) ? frontend.effectiveInterfaceFontFamily : ((frontend && frontend.interfaceFontFamily) ? frontend.interfaceFontFamily : "Segoe UI")
    readonly property string monospaceFontFamily: frontend.monospaceFontFamily
    readonly property string promptFontFamily: frontend.promptFontFamily
    readonly property string terminalFontFamily: frontend.terminalFontFamily
    // Honors Settings -> Appearance -> font smoothing. On keeps the current
    // Windows ClearType look (previous hardcoded behavior, also the stored
    // default); off selects the Qt rasterizer. T3 Code exposes the same
    // preference as grayscale antialiased vs. platform default.
    readonly property int textRenderType: frontend.fontSmoothing
        ? Text.NativeRendering : Text.QtRendering

    readonly property real baseTextScale: 1.00
    property real viewportWidth: 1120
    property real viewportHeight: 700
    readonly property real automaticScale: automaticScaleForSize(
        viewportWidth, viewportHeight)
    readonly property int automaticScalePercent: Math.round(automaticScale * 100)
    readonly property real selectedScale: frontend.uiScale === "auto"
        ? automaticScale : frontend.uiScaleFactor
    readonly property real textScale: baseTextScale * selectedScale
        * (frontend.interfaceFontSize / 14.0)

    function automaticScaleForSize(width, height) {
        var relativeSize = Math.min(Number(width) / 1120, Number(height) / 700)
        var progress = Math.max(0, Math.min(1, (relativeSize - 1) / 2.08))
        return 1.0 + 0.10 * progress
    }

    // P2: T3-like root scale. The interface size drives textScale (like the
    // T3 root font-size driving every rem). Prompt/code/mono/terminal stay in
    // absolute pixels from their own settings, so they never scale twice.
    function fontSize(pixelSize) {
        return Math.max(1, Number(pixelSize) * textScale)
    }

    function monospaceFontSize(pixelSize) {
        return Math.max(1, Number(pixelSize) * baseTextScale
            * (frontend.monospaceFontSize / 12.0))
    }

    function promptFontSize(pixelSize) {
        return Math.max(1, Number(pixelSize) * baseTextScale
            * (frontend.promptFontSize / 14.0))
    }

    function terminalFontSize(pixelSize) {
        return Math.max(1, Number(pixelSize) * baseTextScale
            * (frontend.terminalFontSize / 12.0))
    }

    // Contrast and Glass Opacity tokens
    readonly property int contrast: frontend.appearanceContrast
    readonly property real contrastMultiplier: frontend.appearanceContrast / 100.0
    readonly property real glassOpacity: Math.max(0.4, Math.min(1.0, frontend.glassOpacity / 100.0))
    readonly property int rawPanelAnimationDuration: frontend.rawPanelAnimationDurationMs
    readonly property int panelAnimationDuration: frontend.panelAnimationDurationMs

    // P2: layout follows selectedScale (T3 rem behavior) but keeps integer
    // snapping; only font functions stay fractional (subpixel rendering).
    function scaledGeometry(base) {
        return Math.max(1, Math.round(Number(base) * selectedScale))
    }

    readonly property int spaceXs: scaledGeometry(4)
    readonly property int spaceSm: scaledGeometry(8)
    readonly property int spaceMd: scaledGeometry(12)
    readonly property int spaceLg: scaledGeometry(16)
    readonly property int spaceXl: scaledGeometry(24)
    readonly property int space2Xl: scaledGeometry(32)

    readonly property int radiusSmall: scaledGeometry(8)
    readonly property int radiusControl: scaledGeometry(10)
    readonly property int radiusPopup: scaledGeometry(12)
    readonly property int radiusCard: scaledGeometry(14)

    readonly property int controlHeight: scaledGeometry(40)
    readonly property int compactControlHeight: scaledGeometry(34)
    readonly property int navigationWidth: scaledGeometry(228)
    readonly property int navigationCollapsedWidth: scaledGeometry(64)
    readonly property int chatSidebarWidth: scaledGeometry(220)
    readonly property int chatHeaderHeight: scaledGeometry(52)
    readonly property int contentWidth: scaledGeometry(800)
    readonly property int messageRadius: scaledGeometry(16)
    readonly property int composerRadius: scaledGeometry(16)
    readonly property int messageGap: scaledGeometry(8)
    // Lucide-style presence: 16px metadata actions, 18px inline affordances,
    // 20px navigation and toolbar icons (T3 Code uses 16px size-4 default).
    readonly property int iconSmall: scaledGeometry(16)
    readonly property int iconMedium: scaledGeometry(18)
    readonly property int pageMargin: scaledGeometry(22)
    readonly property int pageSpacing: scaledGeometry(12)
    readonly property int iconSize: scaledGeometry(20)

    readonly property real bodySize: fontSize(14)
    readonly property real captionSize: fontSize(12)
    readonly property real subtitleSize: fontSize(16)
    readonly property real titleSize: fontSize(26)
    readonly property real headingSize: fontSize(18)

    // Proportional line-height rhythm (T3 Code body reads at ~1.5).
    // Single-line centered labels are unaffected by these multipliers.
    readonly property real bodyLineHeight: 1.45
    readonly property real denseLineHeight: 1.35

    // Motion tokens keep interactions consistent and make it easy to honor
    // the reduce-motion preference at each animation site.
    readonly property int pressDuration: frontend.reduceMotion ? 0 : 90
    readonly property int fastDuration: frontend.reduceMotion ? 0 : 140
    readonly property int motionDuration: frontend.panelAnimationDurationMs
    readonly property int pageDuration: frontend.panelAnimationDurationMs
    readonly property int motionDistance: frontend.reduceMotion ? 0 : 10
}
