import QtQuick
import QtQuick.Controls
import "../theme"

Button {
    id: control

    property url iconSource
    property string iconKind: ""
    property string symbol: ""
    property bool round: false
    property color foreground: Theme.palette.text
    property real iconSize: Theme.iconSize

    implicitWidth: Theme.iconButtonNormal
    implicitHeight: Theme.iconButtonNormal
    padding: 0
    focusPolicy: Qt.StrongFocus
    Accessible.name: text || iconKind || symbol
    opacity: enabled ? 1 : 0.38
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && control.down && control.enabled ? 0.91 : 1

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

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
            font.pixelSize: Theme.fontSize(17)
            font.weight: Font.DemiBold
        }
    }

    background: Rectangle {
        radius: control.round ? height / 2 : Theme.radiusControl
        color: control.down || control.hovered ? Theme.palette.hover : "transparent"
        border.width: control.activeFocus ? 2 : 0
        border.color: Theme.palette.focus

        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }
}
