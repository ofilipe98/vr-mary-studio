import QtQuick
import QtQuick.Controls
import "../theme"

Switch {
    id: control
    property bool subdued: false
    property color activeColor: Theme.palette.accessibleOrange
    property color thumbColor: control.checked ? "#FFFFFF" : Theme.palette.mutedText
    property color inactiveColor: Theme.palette.chatControl

    implicitWidth: 32
    implicitHeight: 20
    padding: 0
    spacing: 0
    text: ""
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus

    indicator: Rectangle {
        implicitWidth: 32
        implicitHeight: 18
        x: 0
        y: (control.height - height) / 2
        radius: height / 2
        color: control.checked
            ? (control.subdued ? Qt.tint(Theme.palette.chatControl, Qt.alpha(control.activeColor, 0.40)) : control.activeColor) : control.inactiveColor
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus
            ? Theme.palette.focus : control.checked
                ? (control.subdued ? Theme.palette.focus : control.activeColor) : Theme.palette.chatBorder
        opacity: control.enabled ? 1 : 0.4
        Rectangle { anchors.fill: parent; radius: parent.radius; color: Theme.palette.text; opacity: control.hovered && control.enabled ? 0.06 : 0 }

        Rectangle {
            width: 14
            height: 14
            radius: 7
            y: 2
            x: control.checked ? parent.width - width - 2 : 2
            color: control.thumbColor

            Behavior on x {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.fastDuration; easing.type: Easing.OutCubic }
            }
        }
    }

    contentItem: Item { }
}
