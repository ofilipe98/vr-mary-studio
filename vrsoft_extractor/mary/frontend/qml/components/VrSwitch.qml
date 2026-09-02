import QtQuick
import QtQuick.Controls
import "../theme"

Switch {
    id: control

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
            ? frontend.palette.accessibleOrange : frontend.palette.chatControl
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus
            ? frontend.palette.focus : control.checked
                ? frontend.palette.accessibleOrange : frontend.palette.chatBorder

        Rectangle {
            width: 14
            height: 14
            radius: 7
            y: 2
            x: control.checked ? parent.width - width - 2 : 2
            color: control.checked ? "#FFFFFF" : frontend.palette.mutedText

            Behavior on x {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.fastDuration; easing.type: Easing.OutCubic }
            }
        }
    }

    contentItem: Item { }
}
