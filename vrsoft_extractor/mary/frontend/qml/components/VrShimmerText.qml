import QtQuick
import "../theme"

// Text whose own glyphs are tinted by a moving white specular highlight while a
// task runs. Colors each character from the base color towards white, so the
// sweep lives inside the letters (never a box) and renders in software mode.
Item {
    id: root

    property string text: ""
    property color color: Theme.palette.mutedText
    property alias font: label.font
    property int horizontalAlignment: Text.AlignLeft
    property int elide: Text.ElideRight
    property alias renderType: label.renderType
    property bool running: false
    property real phase: -0.4

    readonly property bool reduceMotion: typeof frontend !== "undefined"
        && frontend !== null && frontend.reduceMotion
    readonly property bool shimmering: root.running && !root.reduceMotion

    implicitWidth: natural.width
    implicitHeight: natural.height

    TextMetrics {
        id: natural
        font: label.font
        text: root.text
    }

    TextMetrics {
        id: fitted
        font: label.font
        text: root.text
        elide: root.elide
        elideWidth: Math.max(0, root.width)
    }

    Text {
        id: label
        anchors.fill: parent
        horizontalAlignment: root.horizontalAlignment
        color: root.color
        textFormat: root.shimmering ? Text.RichText : Text.PlainText
        text: root.shimmering ? root.shimmerMarkup(fitted.elidedText) : fitted.elidedText
    }

    SequentialAnimation on phase {
        running: root.shimmering
        loops: Animation.Infinite
        NumberAnimation {
            from: -0.4
            to: 1.4
            duration: 1800
            easing.type: Easing.InOutSine
        }
        PauseAnimation {
            duration: 350
        }
    }

    function channel(value) {
        var text = Math.max(0, Math.min(255, Math.round(value))).toString(16)
        return text.length < 2 ? "0" + text : text
    }

    function shimmerMarkup(value) {
        if (!value || value.length === 0) return ""
        var base = root.color
        var dim = 0.75
        var baseR = base.r * 255 * dim
        var baseG = base.g * 255 * dim
        var baseB = base.b * 255 * dim
        var length = value.length
        var radius = Math.max(0.20, Math.min(0.40, 4.5 / Math.max(1, length - 1)))
        var currentPhase = root.phase
        var markup = ""
        for (var index = 0; index < length; ++index) {
            var character = value.charAt(index)
            if (character === "&") character = "&amp;"
            else if (character === "<") character = "&lt;"
            else if (character === ">") character = "&gt;"
            else if (character === " ") character = "&nbsp;"
            var position = length > 1 ? index / (length - 1) : 0.5
            var dist = Math.abs(position - currentPhase) / radius
            var glow = 0.0
            if (dist < 1.0) {
                glow = 0.5 * (1.0 + Math.cos(dist * Math.PI))
            }
            var r = baseR + (255 - baseR) * glow
            var g = baseG + (255 - baseG) * glow
            var b = baseB + (255 - baseB) * glow
            markup += '<font color="#' + channel(r) + channel(g) + channel(b) + '">' + character + '</font>'
        }
        return markup
    }
}
