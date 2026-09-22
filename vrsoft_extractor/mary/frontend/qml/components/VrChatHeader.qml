import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    property bool sidebarVisible: true
    property bool panelVisible: false
    property bool hasMessages: false
    property string title: ""
    property string projectLabel: "Projeto"
    property int agentCount: 0
    signal toggleSidebar()
    signal copyConversation()
    signal showAgents()
    signal showPanel()
    height: Theme.chatHeaderHeight
    color: Theme.palette.chatBackground
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.palette.chatDivider; opacity: 0.45 }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.scaledGeometry(10)
        anchors.rightMargin: Theme.scaledGeometry(10)
        spacing: Theme.scaledGeometry(8)
        VrIconButton {
            id: conversationSidebarToggle
            objectName: "conversationSidebarToggle"
            implicitWidth: Theme.scaledGeometry(34)
            implicitHeight: Theme.scaledGeometry(34)
            iconKind: "panelLeft"
            foreground: Theme.palette.mutedText
            Accessible.name: root.sidebarVisible
                ? "Recolher barra lateral" : "Mostrar conversas"
            onClicked: root.toggleSidebar()
            background: Rectangle {
                radius: Theme.scaledGeometry(8)
                color: conversationSidebarToggle.down || conversationSidebarToggle.hovered
                    ? Theme.palette.chatControl : "transparent"
                border.width: parent.activeFocus ? 1 : 0
                border.color: Theme.palette.focus
            }
        }
        Text { visible: root.width > 600; Layout.maximumWidth: Theme.scaledGeometry(160); elide: Text.ElideRight; text: root.projectLabel; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
        Text { visible: root.width > 600; text: "/"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
        Text { Layout.fillWidth: true; text: root.title; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); font.weight: Font.DemiBold; elide: Text.ElideRight }
        VrIconButton {
            objectName: "copyConversationButton"
            iconKind: "copy"
            enabled: root.hasMessages
            Accessible.name: "Copiar conversa completa"
            onClicked: root.copyConversation()
        }
        VrButton {
            visible: root.agentCount > 0
            implicitHeight: Theme.scaledGeometry(30)
            text: "Subagentes · " + root.agentCount
            variant: "ghost"
            onClicked: root.showAgents()
        }
        VrIconButton {
            id: surfaceExpandButton
            objectName: "surfaceToggleButton"
            visible: !root.panelVisible
            implicitWidth: Theme.scaledGeometry(32)
            implicitHeight: Theme.scaledGeometry(32)
            iconSize: Theme.iconSmall
            iconKind: "panelRight"
            foreground: Theme.palette.mutedText
            Accessible.name: "Expandir painel direito"
            onClicked: root.showPanel()
        }
    }
}
