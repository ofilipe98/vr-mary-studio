import QtQuick
import "../theme"

Item {
    id: root

    property string kind: ""
    property bool selected: false

    implicitWidth: 22
    implicitHeight: 22

    Rectangle {
        anchors.fill: parent
        radius: 7
        color: root.selected
            ? Qt.rgba(1.0, 0.45, 0.0, 0.16)
            : Theme.palette.chatControl
        border.width: 1
        border.color: root.selected
            ? Qt.rgba(1.0, 0.45, 0.0, 0.34)
            : Theme.palette.chatBorder
    }

    VrLineIcon {
        anchors.centerIn: parent
        width: 15
        height: 15
        kind: root.kind
        strokeWidth: 1.85
        foreground: root.selected
            ? Theme.palette.brandOrange
            : Theme.palette.mutedText
    }
}
