import QtQuick
import QtQuick.Controls
import "../theme"

TextArea {
    id: control

    leftPadding: 13
    rightPadding: 13
    topPadding: 11
    bottomPadding: 11
    color: frontend.palette.text
    placeholderTextColor: frontend.palette.mutedText
    selectionColor: frontend.palette.selection
    selectedTextColor: frontend.palette.text
    font.family: Theme.fontFamily
    font.pixelSize: Theme.bodySize
    wrapMode: TextArea.Wrap
    focusPolicy: Qt.StrongFocus

    background: Rectangle {
        radius: Theme.radiusControl
        color: control.enabled ? frontend.palette.surfaceRaised : frontend.palette.background
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? frontend.palette.focus : frontend.palette.border
    }
}
