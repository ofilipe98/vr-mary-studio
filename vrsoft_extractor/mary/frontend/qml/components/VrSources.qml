pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Column {
    id: root
    objectName: "sourcesList"
    property var sources: []
    property bool expanded: false
    spacing: 6
    visible: sources.length > 0
    Text {
        text: "Fontes · " + root.sources.length
        color: Theme.palette.subtleText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.captionSize
        bottomPadding: 2
    }
    Repeater {
        model: root.expanded ? root.sources : root.sources.slice(0, 4)
        delegate: Button {
            id: source
            objectName: "sourceCitation"
            required property var modelData
            width: parent.width
            height: 36
            padding: 8
            Accessible.name: modelData.content + ", " + modelData.origin
            ToolTip.visible: hovered || activeFocus
            ToolTip.delay: 500
            ToolTip.text: modelData.url
            onClicked: { if (studio) studio.openExternalUrl(modelData.url) }
            contentItem: RowLayout {
                spacing: 8
                VrLineIcon { kind: "files"; Layout.preferredWidth: 14; Layout.preferredHeight: 14; foreground: Theme.palette.mutedText }
                Text { Layout.fillWidth: true; text: source.modelData.content; elide: Text.ElideRight; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize }
                Text { visible: root.width > 480; text: source.modelData.origin; color: Theme.palette.subtleText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11) }
                VrLineIcon { kind: "external"; Layout.preferredWidth: 14; Layout.preferredHeight: 14; foreground: Theme.palette.mutedText }
            }
            background: Rectangle {
                radius: Theme.radiusSmall
                color: source.hovered ? Theme.palette.chatControl : Theme.palette.codeSurface
                border.width: source.activeFocus ? 1 : 0
                border.color: Theme.palette.focus
                Behavior on color { enabled: !frontend.reduceMotion; ColorAnimation { duration: Theme.fastDuration } }
            }
        }
    }
    VrButton {
        objectName: "sourcesExpandButton"
        visible: root.sources.length > 4
        variant: "ghost"
        implicitHeight: 28
        text: root.expanded ? "Mostrar menos" : "Mostrar mais " + (root.sources.length - 4)
        onClicked: root.expanded = !root.expanded
    }
}
