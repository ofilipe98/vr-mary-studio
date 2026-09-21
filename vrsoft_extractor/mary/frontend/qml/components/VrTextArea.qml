import QtQuick
import QtQuick.Controls
import QtQuick.Templates as T
import "../theme"

TextArea {
    id: control

    // Substitui o menu nativo do Qt 6.11 (Undo/Redo/Delete em inglês e sem
    // atalhos) pelo menu temático do app.
    T.ContextMenu.menu: VrEditContextMenu {
        editor: control
    }

    leftPadding: Theme.scaledGeometry(13)
    rightPadding: Theme.scaledGeometry(13)
    topPadding: Theme.scaledGeometry(11)
    bottomPadding: Theme.scaledGeometry(11)
    color: Theme.palette.text
    placeholderTextColor: Theme.palette.mutedText
    selectionColor: Theme.palette.selection
    selectedTextColor: Theme.palette.text
    font.family: Theme.fontFamily
    font.pixelSize: Theme.controlSize
    renderType: Theme.textRenderType
    wrapMode: TextArea.Wrap
    focusPolicy: Qt.StrongFocus

    background: Rectangle {
        radius: Theme.radiusControl
        color: control.enabled ? Theme.palette.surfaceRaised : Theme.palette.background
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.border
    }
}
