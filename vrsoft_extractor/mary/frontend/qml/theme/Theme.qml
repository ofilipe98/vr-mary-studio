pragma Singleton

import QtQuick

QtObject {
    // Convert the Python QVariantMap once per theme change, not per hover.
    readonly property var palette: frontend.palette
    readonly property string fontFamily: frontend.interfaceFontFamily
    readonly property string monospaceFontFamily: frontend.monospaceFontFamily
    readonly property string promptFontFamily: frontend.promptFontFamily
    readonly property string terminalFontFamily: frontend.terminalFontFamily

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

    function fontSize(pixelSize) {
        return Math.max(1, Math.round(Number(pixelSize) * textScale))
    }

    function monospaceFontSize(pixelSize) {
        return Math.max(1, Math.round(Number(pixelSize) * baseTextScale
            * selectedScale * (frontend.monospaceFontSize / 12.0)))
    }

    function promptFontSize(pixelSize) {
        return Math.max(1, Math.round(Number(pixelSize) * baseTextScale
            * selectedScale * (frontend.promptFontSize / 14.0)))
    }

    function terminalFontSize(pixelSize) {
        return Math.max(1, Math.round(Number(pixelSize) * baseTextScale
            * selectedScale * (frontend.terminalFontSize / 12.0)))
    }

    // Contrast and Glass Opacity tokens
    readonly property int contrast: frontend.appearanceContrast
    readonly property real contrastMultiplier: frontend.appearanceContrast / 100.0
    readonly property real glassOpacity: Math.max(0.4, Math.min(1.0, frontend.glassOpacity / 100.0))
    readonly property int rawPanelAnimationDuration: frontend.rawPanelAnimationDurationMs
    readonly property int panelAnimationDuration: frontend.panelAnimationDurationMs

    readonly property int spaceXs: 4
    readonly property int spaceSm: 8
    readonly property int spaceMd: 12
    readonly property int spaceLg: 16
    readonly property int spaceXl: 24
    readonly property int space2Xl: 32

    readonly property int radiusSmall: 8
    readonly property int radiusControl: 10
    readonly property int radiusPopup: 12
    readonly property int radiusCard: 14

    readonly property int controlHeight: 40
    readonly property int compactControlHeight: 34
    readonly property int navigationWidth: 228
    readonly property int navigationCollapsedWidth: 64
    readonly property int chatSidebarWidth: 220
    readonly property int chatHeaderHeight: 50
    readonly property int contentWidth: 800
    readonly property int messageRadius: 16
    readonly property int composerRadius: 16
    readonly property int messageGap: 8
    readonly property int iconSmall: 14
    readonly property int iconMedium: 16
    readonly property int pageMargin: 22
    readonly property int pageSpacing: 12
    readonly property int iconSize: 18

    readonly property int bodySize: fontSize(14)
    readonly property int captionSize: fontSize(12)
    readonly property int subtitleSize: fontSize(16)
    readonly property int titleSize: fontSize(26)
    readonly property int headingSize: fontSize(18)

    // Motion tokens keep interactions consistent and make it easy to honor
    // the reduce-motion preference at each animation site.
    readonly property int pressDuration: frontend.reduceMotion ? 0 : 90
    readonly property int fastDuration: frontend.reduceMotion ? 0 : 140
    readonly property int motionDuration: frontend.panelAnimationDurationMs
    readonly property int pageDuration: frontend.panelAnimationDurationMs
    readonly property int motionDistance: frontend.reduceMotion ? 0 : 10
}
