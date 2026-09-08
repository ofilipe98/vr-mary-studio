pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root
    required property var bridge
    spacing: 8
    Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        text: "Busca local e relações entre fontes"
        color: Theme.palette.headingText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
        font.bold: true
    }
    VrComboBox {
        id: mode
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        model: ["Textual", "Híbrida (local, opcional)"]
        currentIndex: root.bridge.configuration.mode === "hybrid" ? 1 : 0
        enabled: !root.bridge.busy
        onActivated: root.bridge.configure(currentIndex === 1 ? "hybrid" : "textual", root.bridge.configuration.model, root.bridge.configuration.relations)
    }
    VrComboBox {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        model: ["E5 Small · MIT · 135 MB", "MiniLM · Apache-2.0 · 128 MB"]
        currentIndex: root.bridge.configuration.model === "minilm" ? 1 : 0
        enabled: !root.bridge.busy
        onActivated: root.bridge.configure(root.bridge.configuration.mode, currentIndex === 1 ? "minilm" : "e5-small", root.bridge.configuration.relations)
    }
    VrCheckBox {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        text: "Adicionar fontes ligadas por referências verificadas"
        checked: root.bridge.configuration.relations
        enabled: !root.bridge.busy
        onClicked: root.bridge.configure(root.bridge.configuration.mode, root.bridge.configuration.model, checked)
    }
    GridLayout {
        columns: root.width < 520 ? 1 : 2
        VrButton { text: "Baixar modelo e preparar índice"; enabled: !root.bridge.busy; onClicked: root.bridge.prepare() }
        VrButton { text: "Atualizar índice"; enabled: !root.bridge.busy; onClicked: root.bridge.reindex() }
    }
    Text {
        Layout.fillWidth: true
        text: root.bridge.status
        color: Theme.palette.subtleText
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(12)
    }
}
