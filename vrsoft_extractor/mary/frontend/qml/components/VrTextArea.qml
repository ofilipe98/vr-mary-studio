import QtQuick
import QtQuick.Controls
import "../theme"

TextArea {
    id: control

    leftPadding: 13
    rightPadding: 13
    topPadding: 11
    bottomPadding: 11
    color: Theme.palette.text
    placeholderTextColor: Theme.palette.mutedText
    selectionColor: Theme.palette.selection
    selectedTextColor: Theme.palette.text
    font.family: Theme.fontFamily
    font.pixelSize: Theme.bodySize
    wrapMode: TextArea.Wrap
    focusPolicy: Qt.StrongFocus

    background: Rectangle {
        radius: Theme.radiusControl
        color: control.enabled ? Theme.palette.surfaceRaised : Theme.palette.background
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.border
    }
}
