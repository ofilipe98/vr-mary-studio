import QtQuick
import "../theme"

Item {
    id: root

    property string projectLabel: ""
    property string iconPath: ""
    property string iconKind: ""
    property string iconEmoji: ""
    property string iconColor: ""
    property string iconText: ""
    property bool isAll: false
    // flat=true: glifo puro na cor do projeto, sem caixa/fundo (estilo lista do T3).
    property bool flat: false
    property real iconSize: 15
    property real boxSize: 24

    implicitWidth: boxSize
    implicitHeight: boxSize
    width: boxSize
    height: boxSize

    // Catálogo de cores estilo T3 Code (nome + hex), reutilizado pelo seletor.
    readonly property var iconColors: [
        { name: "gray", value: "#6B7280" }, { name: "red", value: "#EF4444" },
        { name: "orange", value: "#F97316" }, { name: "amber", value: "#F59E0B" },
        { name: "yellow", value: "#EAB308" }, { name: "lime", value: "#84CC16" },
        { name: "green", value: "#22C55E" }, { name: "emerald", value: "#10B981" },
        { name: "teal", value: "#14B8A6" }, { name: "cyan", value: "#06B6D4" },
        { name: "sky", value: "#0EA5E9" }, { name: "blue", value: "#3B82F6" },
        { name: "indigo", value: "#6366F1" }, { name: "violet", value: "#8B5CF6" },
        { name: "purple", value: "#A855F7" }, { name: "fuchsia", value: "#D946EF" },
        { name: "pink", value: "#EC4899" }, { name: "rose", value: "#F43F5E" }
    ]

    function iconColorName(value) {
        var raw = String(value || "").trim().toLowerCase()
        if (!raw.length) return "auto"
        for (var i = 0; i < iconColors.length; ++i) {
            if (String(iconColors[i].value).toLowerCase() === raw) return iconColors[i].name
        }
        return raw
    }

    function normalizedColor(value) {
        var raw = String(value || "").trim()
        if (/^#[0-9a-fA-F]{6}$/.test(raw)) return raw
        if (/^#[0-9a-fA-F]{3}$/.test(raw)) {
            return "#" + raw[1] + raw[1] + raw[2] + raw[2] + raw[3] + raw[3]
        }
        return ""
    }

    function paletteFor(label) {
        var palette = ["#A855F7", "#F57616", "#38BDF8", "#22C55E", "#E879F9",
                       "#FACC15", "#34D399", "#F87171", "#818CF8", "#FB7185"]
        var text = String(label || "")
        if (!text.length) return palette[2]
        var hash = 0
        for (var i = 0; i < text.length; ++i) {
            hash = (hash * 31 + text.charCodeAt(i)) >>> 0
        }
        return palette[hash % palette.length]
    }

    function effectiveColor() {
        var custom = normalizedColor(root.iconColor)
        if (custom.length) return custom
        return paletteFor(root.projectLabel)
    }

    function monogramFor(label) {
        var text = String(label || "").trim()
        if (!text.length) return "•"
        var words = text.split(/[\s_.\-]+/).filter(function(part) { return part.length > 0 })
        if (words.length >= 2) {
            return (words[0].charAt(0) + words[1].charAt(0)).toUpperCase()
        }
        var compact = text.replace(/[^A-Za-z0-9À-ÿ]/g, "")
        if (!compact.length) compact = text
        if (compact.length >= 2) return compact.substring(0, 2).toUpperCase()
        return compact.substring(0, 1).toUpperCase()
    }

    function iconFileSource() {
        if (!root.iconPath.length) return ""
        var fixed = String(root.iconPath).replace(/\\/g, "/")
        if (fixed.indexOf("file:") === 0) return fixed
        if (fixed.indexOf("/") === 0 || /^[A-Za-z]:\//.test(fixed)) return "file:///" + fixed.replace(/^\//, "")
        return "file:///" + fixed
    }

    readonly property string resolvedColor: effectiveColor()
    readonly property string monogram: monogramFor(root.projectLabel)
    readonly property string displayText: String(root.iconText || "").trim().length
        ? String(root.iconText).trim().toUpperCase() : root.monogram
    readonly property bool showImage: root.iconPath.length > 0 && !root.isAll
    readonly property bool showEmoji: !showImage && String(root.iconEmoji || "").trim().length > 0 && !root.isAll
    readonly property bool showKind: !showImage && !showEmoji
        && String(root.iconKind || "").trim().length > 0 && !root.isAll

    Rectangle {
        id: box
        anchors.fill: parent
        radius: 6
        color: (root.flat || root.isAll || root.showKind) ? "transparent"
            : (root.showImage ? Theme.palette.chatBackground : Qt.alpha(root.resolvedColor, 0.16))
        border.width: (root.flat || root.isAll || root.showImage || root.showKind) ? 0 : 1
        border.color: (root.flat || root.isAll || root.showImage || root.showKind) ? "transparent" : Qt.alpha(root.resolvedColor, 0.35)

        VrLineIcon {
            visible: root.isAll
            anchors.centerIn: parent
            width: root.iconSize
            height: root.iconSize
            kind: "folder"
            foreground: Theme.palette.mutedText
        }

        Image {
            visible: root.showImage
            anchors.fill: parent
            anchors.margins: 2
            source: root.showImage ? root.iconFileSource() : ""
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            onStatusChanged: {
                if (status === Image.Error) visible = false
            }
        }

        Text {
            visible: root.showEmoji
            anchors.centerIn: parent
            text: String(root.iconEmoji || "").trim()
            font.pixelSize: Math.round(root.boxSize * 0.62)
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignHCenter
        }

        VrLineIcon {
            visible: root.showKind
            anchors.centerIn: parent
            width: Math.round(root.boxSize * 0.72)
            height: Math.round(root.boxSize * 0.72)
            kind: String(root.iconKind || "")
            foreground: root.resolvedColor
        }

        Text {
            visible: !root.isAll && !root.showImage && !root.showEmoji && !root.showKind
            anchors.centerIn: parent
            text: root.displayText
            color: root.resolvedColor
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(9, Math.round(root.boxSize * 0.40))
            font.weight: Font.DemiBold
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
