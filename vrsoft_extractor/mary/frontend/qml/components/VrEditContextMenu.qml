import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Menu {
    id: menu
    objectName: "textEditContextMenu"

    // Campo de texto que originou o menu (TextField/TextArea). O menu usa as
    // propriedades e os métodos de edição do próprio editor para não divergir
    // do comportamento nativo de recortar/copiar/colar. O tipo fica em `var`
    // porque TextField e TextArea não compartilham uma base QML tipada.
    required property var editor

    readonly property bool hasEditor: menu.editor !== null && menu.editor !== undefined
    readonly property bool hasSelection: menu.hasEditor
        && menu.editor.selectedText !== undefined
        && menu.editor.selectedText.length > 0
    readonly property bool hasText: menu.hasEditor
        && menu.editor.length !== undefined
        && menu.editor.length > 0
    readonly property bool editable: menu.hasEditor && !menu.editor.readOnly
    readonly property bool canPaste: menu.hasEditor
        && menu.editor.canPaste !== undefined
        && menu.editor.canPaste

    implicitWidth: 200
    padding: 5
    overlap: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    // Item base do menu: rótulo à esquerda e atalho à direita, no visual dos
    // demais menus do app (fundo escuro, hover suave, sem ícones).
    component EditContextEntry: MenuItem {
        id: entry
        property string shortcutLabel: ""
        implicitHeight: Theme.menuRowHeight
        leftPadding: Theme.spaceMd
        rightPadding: Theme.spaceMd

        contentItem: RowLayout {
            spacing: Theme.spaceSm
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: entry.text
                color: entry.enabled ? Theme.palette.text : Theme.palette.subtleText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12.5)
                renderType: Theme.textRenderType
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
            Text {
                text: entry.shortcutLabel
                color: entry.enabled ? Theme.palette.mutedText : Theme.palette.subtleText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                renderType: Theme.textRenderType
                verticalAlignment: Text.AlignVCenter
            }
        }

        background: Rectangle {
            radius: 7
            color: entry.highlighted ? Theme.palette.chatControl : "transparent"
        }
    }

    EditContextEntry {
        objectName: "textEditContextCut"
        text: "Recortar"
        shortcutLabel: "Ctrl+X"
        enabled: menu.hasSelection && menu.editable
        onTriggered: menu.editor.cut()
    }
    EditContextEntry {
        objectName: "textEditContextCopy"
        text: "Copiar"
        shortcutLabel: "Ctrl+C"
        enabled: menu.hasSelection
        onTriggered: menu.editor.copy()
    }
    EditContextEntry {
        objectName: "textEditContextPaste"
        text: "Colar"
        shortcutLabel: "Ctrl+V"
        enabled: menu.editable && menu.canPaste
        onTriggered: menu.editor.paste()
    }
    EditContextEntry {
        objectName: "textEditContextSelectAll"
        text: "Selecionar tudo"
        shortcutLabel: "Ctrl+A"
        enabled: menu.hasText
        onTriggered: menu.editor.selectAll()
    }

    background: Rectangle {
        radius: 10
        color: Theme.palette.chatComposer
        border.width: 1
        border.color: Theme.palette.chatBorder
    }
}
