pragma Singleton

import QtQuick

QtObject {
    // Convert the Python QVariantMap once per theme change, not per hover.
    readonly property var palette: frontend.palette
    // Identidade fixa dos modos VR (VR e VR Ultra): anel, halo e realces do
    // composer mantêm o laranja da marca mesmo quando o tema remapeia o acento
    // (temas T3 levam brandOrange/accessibleOrange para messageAction).
    readonly property color vrAccent: "#FF7200"
    readonly property string fontFamily: (frontend && frontend.effectiveInterfaceFontFamily) ? frontend.effectiveInterfaceFontFamily : ((frontend && frontend.interfaceFontFamily) ? frontend.interfaceFontFamily : "Segoe UI")
    readonly property string monospaceFontFamily: frontend.monospaceFontFamily
    readonly property string promptFontFamily: frontend.promptFontFamily
    readonly property string terminalFontFamily: frontend.terminalFontFamily
    // Single text-rendering policy (Windows consistent).
    // Every textual surface must use Theme.textRenderType; hardcoded render
    // types are not allowed in components. The effective mode comes from the
    // bridge (appearance/text_rendering): "qt" uses the Qt rasterizer with
    // subpixel positioning and vertical hinting, matching T3/Chromium on
    // Windows; "native" keeps Windows ClearType. On macOS the legacy
    // fontSmoothing toggle still drives the mode.
    readonly property int textRenderType: frontend.textRenderingMode === "native"
        ? Text.NativeRendering : Text.QtRendering

    readonly property real baseTextScale: 1.00
    property real viewportWidth: 1120
    property real viewportHeight: 700
    readonly property real automaticScale: 1.0
    readonly property int automaticScalePercent: 100
    readonly property real selectedScale: frontend.uiScale === "auto"
        ? 1.0 : frontend.uiScaleFactor
    readonly property real interfaceScale: frontend.interfaceFontSize / 16.0
    readonly property real textScale: baseTextScale * selectedScale * interfaceScale

    function automaticScaleForSize(width, height) {
        return 1.0
    }

    // Semantic root scale: interfaceFontSize drives textScale (nominal 16px baseline).
    // Prompt/code/mono/terminal use their own sizes, multiplied only by app zoom.
    function fontSize(pixelSize) {
        return Math.max(1, Number(pixelSize) * textScale)
    }

    function monospaceFontSize(pixelSize) {
        return Math.max(1, Number(pixelSize) * baseTextScale * selectedScale
            * (frontend.monospaceFontSize / 12.0))
    }

    function promptFontSize(pixelSize) {
        return Math.max(1, Number(pixelSize) * baseTextScale * selectedScale
            * (frontend.promptFontSize / 14.0))
    }

    function terminalFontSize(pixelSize) {
        return Math.max(1, Number(pixelSize) * baseTextScale * selectedScale
            * (frontend.terminalFontSize / 12.0))
    }

    // Semantic typography scale (T3 Code design hierarchy)
    readonly property real fontSizeMicro: fontSize(11)
    readonly property real fontSizeCaption: fontSize(12)
    readonly property real fontSizeCompact: fontSize(13)
    readonly property real fontSizeControl: fontSize(14)
    readonly property real fontSizeBody: fontSize(16)
    readonly property real fontSizeHeading: fontSize(18)
    readonly property real fontSizeSection: fontSize(20)
    readonly property real fontSizeTitle: fontSize(24)
    readonly property real fontSizePageTitle: fontSize(26)

    // T3 landing hierarchy: text-2xl (24) below 640px, text-3xl (30) above it.
    readonly property real fontSizeLandingCompact: fontSize(24)
    readonly property real fontSizeLanding: fontSize(30)

    // Semantic aliases for consistency
    readonly property real microSize: fontSizeMicro
    readonly property real captionSize: fontSizeCaption
    readonly property real compactLabelSize: fontSizeCompact
    readonly property real controlSize: fontSizeControl
    readonly property real bodySize: fontSizeBody
    readonly property real headingSize: fontSizeHeading
    readonly property real sectionTitleSize: fontSizeSection
    readonly property real subtitleSize: fontSizeHeading
    readonly property real titleSize: fontSizePageTitle
    readonly property real pageTitleSize: fontSizePageTitle

    // Typographic weights (aligned with design system)
    readonly property int weightRegular: Font.Normal
    readonly property int weightMedium: Font.Medium
    readonly property int weightDemiBold: Font.DemiBold
    readonly property int weightBold: Font.Bold

    // Proportional line-height rhythm (T3 Code body reads at ~1.45-1.5)
    readonly property real bodyLineHeight: 1.45
    readonly property real denseLineHeight: 1.35
    readonly property real headingLineHeight: 1.25

    // T3 tracking: headings use tracking-tight (-0.025em). letterSpacing in
    // QML is absolute, so scale the ratio by the pixel size.
    readonly property real trackingTight: -0.025
    function tracking(pixelSize, ratio) {
        return Number(pixelSize) * ratio
    }

    // Contrast and Glass Opacity tokens
    readonly property int contrast: frontend.appearanceContrast
    readonly property real contrastMultiplier: frontend.appearanceContrast / 100.0
    readonly property real glassOpacity: Math.max(0.4, Math.min(1.0, frontend.glassOpacity / 100.0))
    readonly property int rawPanelAnimationDuration: frontend.rawPanelAnimationDurationMs
    readonly property int panelAnimationDuration: frontend.panelAnimationDurationMs

    // T3 root font size scales rem dimensions as well as interface text.
    // App zoom additionally scales prompt/code/terminal, independently of DPI.
    function scaledGeometry(base) {
        return Math.round(Number(base) * selectedScale * interfaceScale)
    }

    readonly property int spaceXs: scaledGeometry(4)
    readonly property int spaceSm: scaledGeometry(8)
    readonly property int spaceMd: scaledGeometry(12)
    readonly property int spaceLg: scaledGeometry(16)
    readonly property int spaceXl: scaledGeometry(24)
    readonly property int space2Xl: scaledGeometry(32)

    readonly property int radiusXs: scaledGeometry(4)
    readonly property int radiusSmall: scaledGeometry(8)
    readonly property int radiusControl: scaledGeometry(8)
    readonly property int radiusPopup: scaledGeometry(12)
    readonly property int radiusCard: scaledGeometry(12)
    readonly property int radiusLg: scaledGeometry(16)

    // Standardized control heights (aligned with T3 Code)
    // T3 desktop reference: button ~32, select ~32, input ~30, compact smaller.
    // Qt defaults use compact (32) for inputs/selects/buttons; 38/44 remain
    // for large touch targets and explicit large variants.
    readonly property int controlHeightCompact: scaledGeometry(32)
    readonly property int compactControlHeight: scaledGeometry(34)
    readonly property int controlHeight: scaledGeometry(38)
    readonly property int controlHeightNormal: scaledGeometry(38)
    readonly property int controlHeightLarge: scaledGeometry(44)
    readonly property int menuRowHeight: scaledGeometry(32)
    readonly property int pickerRowHeight: scaledGeometry(40)
    readonly property int iconButtonCompact: scaledGeometry(28)
    readonly property int iconButtonNormal: scaledGeometry(34)
    readonly property int iconButtonLarge: scaledGeometry(38)

    readonly property int navigationWidth: scaledGeometry(228)
    readonly property int navigationCollapsedWidth: scaledGeometry(64)
    readonly property int chatSidebarWidth: scaledGeometry(220)
    readonly property int chatHeaderHeight: scaledGeometry(52)
    readonly property int contentWidth: scaledGeometry(800)
    readonly property int messageRadius: scaledGeometry(16)
    readonly property int composerRadius: scaledGeometry(16)
    readonly property int messageGap: scaledGeometry(8)

    // Lucide-style presence on T3's size scale (12/14/16/18/20)
    readonly property int iconMicro: scaledGeometry(12)
    readonly property int iconCompact: scaledGeometry(14)
    readonly property int iconSmall: scaledGeometry(16)
    readonly property int iconMedium: scaledGeometry(18)
    readonly property int iconSize: scaledGeometry(20)
    readonly property int pageMargin: scaledGeometry(viewportWidth < 600 ? 16 : 24)
    readonly property int pageSpacing: scaledGeometry(12)

    // Motion tokens
    readonly property int pressDuration: frontend.reduceMotion ? 0 : 90
    readonly property int fastDuration: frontend.reduceMotion ? 0 : 140
    readonly property int motionDuration: frontend.panelAnimationDurationMs
    readonly property int pageDuration: frontend.panelAnimationDurationMs
    readonly property int motionDistance: frontend.reduceMotion ? 0 : 10
}
