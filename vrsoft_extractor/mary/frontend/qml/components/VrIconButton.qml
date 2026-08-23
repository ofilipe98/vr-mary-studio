import QtQuick
import QtQuick.Controls
import "../theme"

Button {
    id: control

    property url iconSource
    property string iconKind: ""
    property string symbol: ""
    property bool round: false
    property color foreground: frontend.palette.text
    property real iconSize: Theme.iconSize

    implicitWidth: Theme.controlHeight
    implicitHeight: Theme.controlHeight
    padding: 0
    focusPolicy: Qt.StrongFocus

    contentItem: Item {
        Image {
            visible: control.iconSource.toString().length > 0 && !control.iconKind.length
            anchors.centerIn: parent
            width: control.iconSize
            height: control.iconSize
            source: control.iconSource
            fillMode: Image.PreserveAspectFit
        }
        VrLineIcon {
            visible: control.iconKind.length > 0
            anchors.centerIn: parent
            width: control.iconSize
            height: control.iconSize
            kind: control.iconKind
            foreground: control.foreground
        }
        Text {
            visible: !parent.children[0].visible && !parent.children[1].visible
            anchors.centerIn: parent
            text: control.symbol
            color: control.foreground
            font.family: Theme.fontFamily
            font.pixelSize: 17
            font.weight: Font.DemiBold
        }
    }

    background: Rectangle {
        radius: control.round ? height / 2 : Theme.radiusControl
        color: control.down || control.hovered ? frontend.palette.hover : "transparent"
        border.width: control.activeFocus ? 2 : 0
        border.color: frontend.palette.focus
    }
}
