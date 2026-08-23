import QtQuick
import QtQuick.Controls
import "../theme"

TextField {
    id: control

    implicitHeight: Theme.controlHeight
    leftPadding: 13
    rightPadding: 13
    color: frontend.palette.text
    placeholderTextColor: frontend.palette.mutedText
    selectionColor: frontend.palette.selection
    selectedTextColor: frontend.palette.text
    font.family: Theme.fontFamily
    font.pixelSize: Theme.bodySize
    focusPolicy: Qt.StrongFocus

    background: Rectangle {
        radius: Theme.radiusControl
        color: control.enabled ? frontend.palette.surfaceRaised : frontend.palette.background
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? frontend.palette.focus : frontend.palette.border

        Behavior on border.color {
            ColorAnimation { duration: Theme.fastDuration }
        }
    }
}
