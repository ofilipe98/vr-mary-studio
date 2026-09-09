import QtQuick
import QtQuick.Controls
import "../theme"

Slider {
    id: control

    implicitWidth: 200
    implicitHeight: 24
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus

    background: Rectangle {
        x: control.leftPadding
        y: control.topPadding + control.availableHeight / 2 - height / 2
        implicitWidth: 200
        implicitHeight: 6
        width: control.availableWidth
        height: implicitHeight
        radius: 3
        color: Theme.palette.surfaceRaised
        border.color: Theme.palette.border
        border.width: 1

        Rectangle {
            width: control.visualPosition * parent.width
            height: parent.height
            color: control.enabled ? Theme.palette.accessibleOrange : Theme.palette.mutedText
            radius: 3
        }
    }

    handle: Rectangle {
        x: control.leftPadding + control.visualPosition * (control.availableWidth - width)
        y: control.topPadding + control.availableHeight / 2 - height / 2
        implicitWidth: 18
        implicitHeight: 18
        radius: 9
        color: control.pressed ? Theme.palette.brandOrange : (control.hovered ? "#FFFFFF" : "#EEEEEE")
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.accessibleOrange
        border.width: control.activeFocus ? 3 : 2

        scale: !frontend.reduceMotion && (control.pressed || control.hovered) ? 1.15 : 1.0

        Behavior on scale {
            enabled: !frontend.reduceMotion
            NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
        }
    }
}
