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
    property real phase: 0

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

    NumberAnimation on phase {
        running: root.shimmering
        from: 0
        to: 1
        duration: 1700
        loops: Animation.Infinite
        easing.type: Easing.InOutSine
    }

    function channel(value) {
        var text = Math.round(value).toString(16)
        return text.length < 2 ? "0" + text : text
    }

    function shimmerMarkup(value) {
        var base = root.color
        var dim = 0.4
        var red = base.r * 255 * dim
        var green = base.g * 255 * dim
        var blue = base.b * 255 * dim
        var length = value.length
        var markup = ""
        for (var index = 0; index < length; ++index) {
            var character = value.charAt(index)
            if (character === "&") character = "&amp;"
            else if (character === "<") character = "&lt;"
            else if (character === ">") character = "&gt;"
            else if (character === " ") character = "&nbsp;"
            var position = length > 1 ? index / (length - 1) : 0.5
            var glow = Math.max(0, 1 - Math.abs(position - root.phase) / 0.5)
            glow = glow * glow
            var r = red + (255 - red) * glow
            var g = green + (255 - green) * glow
            var b = blue + (255 - blue) * glow
            markup += '<font color="#' + channel(r) + channel(g) + channel(b) + '">' + character + '</font>'
        }
        return markup
    }
}
