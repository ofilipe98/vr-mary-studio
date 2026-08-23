import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    objectName: "chatActivity"

    property var items: []
    property string reasoningText: ""
    property string statusText: "Pronto"
    property string elapsedLabel: "0s"
    property bool running: false
    property bool expanded: true
    signal toggleRequested()

    implicitHeight: content.implicitHeight + 4
    color: "transparent"

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 5

        Rectangle {
            id: activityHeader
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            radius: 7
            color: activityHover.hovered ? frontend.palette.hover : "transparent"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 3
                anchors.rightMargin: 5
                spacing: 8

                VrLineIcon {
                    Layout.preferredWidth: 14
                    Layout.preferredHeight: 14
                    kind: root.running ? "auto"
                        : root.expanded ? "chevronDown" : "chevronUp"
                    foreground: root.running
                        ? frontend.palette.brandOrange : frontend.palette.mutedText
                }
                Text {
                    Layout.fillWidth: true
                    text: root.summaryText()
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    font.weight: root.running ? Font.DemiBold : Font.Normal
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }
                Text {
                    visible: root.items.length > 0
                    text: root.completedItemCount() + "/" + root.items.length
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: 9
                }
                VrLineIcon {
                    Layout.preferredWidth: 12
                    Layout.preferredHeight: 12
                    kind: root.expanded ? "chevronDown" : "chevronUp"
                    foreground: frontend.palette.mutedText
                }
            }

            HoverHandler { id: activityHover }
            TapHandler { onTapped: root.toggleRequested() }
        }

        ColumnLayout {
            visible: root.expanded
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 8
            spacing: 7

            Text {
                visible: root.reasoningText.trim().length > 0
                Layout.fillWidth: true
                text: root.reasoningText
                textFormat: Text.PlainText
                color: frontend.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: 11
                lineHeightMode: Text.ProportionalHeight
                lineHeight: 1.35
                horizontalAlignment: Text.AlignLeft
                wrapMode: Text.WordWrap
            }

            Repeater {
                model: root.items.slice(Math.max(0, root.items.length - 30))
                delegate: ColumnLayout {
                    id: activityItem
                    required property var modelData
                    property bool detailExpanded: false
                    Layout.fillWidth: true
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        VrLineIcon {
                            Layout.preferredWidth: 13
                            Layout.preferredHeight: 13
                            kind: activityItem.modelData.kind === "tool" ? "terminal" : "task"
                            foreground: root.stateColor(activityItem.modelData.state)
                        }
                        Text {
                            Layout.fillWidth: true
                            text: activityItem.modelData.text || "Atividade"
                            color: activityItem.modelData.state === "running"
                                ? frontend.palette.text : frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: 10
                            font.weight: activityItem.modelData.state === "running"
                                ? Font.DemiBold : Font.Normal
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        Text {
                            text: root.stateLabel(activityItem.modelData.state)
                            color: root.stateColor(activityItem.modelData.state)
                            font.family: Theme.fontFamily
                            font.pixelSize: 9
                        }
                        VrLineIcon {
                            visible: String(activityItem.modelData.detail || "").length > 0
                            Layout.preferredWidth: 11
                            Layout.preferredHeight: 11
                            kind: activityItem.detailExpanded ? "chevronDown" : "chevronUp"
                            foreground: frontend.palette.mutedText
                        }
                        TapHandler {
                            enabled: String(activityItem.modelData.detail || "").length > 0
                            onTapped: activityItem.detailExpanded = !activityItem.detailExpanded
                        }
                    }

                    Rectangle {
                        visible: activityItem.detailExpanded
                            && String(activityItem.modelData.detail || "").length > 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: detailText.implicitHeight + 14
                        radius: 7
                        color: frontend.palette.surfaceRaised
                        border.width: 1
                        border.color: frontend.palette.chatBorder

                        Text {
                            id: detailText
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            text: activityItem.modelData.detail || ""
                            color: frontend.palette.mutedText
                            font.family: "Cascadia Mono"
                            font.pixelSize: 9
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: frontend.palette.chatDivider
            opacity: 0.65
        }
    }

    function completedItemCount() {
        var completed = 0
        for (var index = 0; index < root.items.length; ++index) {
            var state = String(root.items[index].state || "")
            if (state === "completed") completed += 1
        }
        return completed
    }

    function summaryText() {
        if (root.running) {
            for (var index = root.items.length - 1; index >= 0; --index) {
                if (String(root.items[index].state || "") === "running")
                    return root.items[index].kind === "tool"
                        ? "Executando " + String(root.items[index].text || "ferramenta")
                        : String(root.items[index].text || "Pensando…")
            }
            return root.reasoningText.length ? "Pensando…"
                : root.statusText === "Pronto" ? "Trabalhando…" : root.statusText
        }
        if (root.statusText === "Erro") return "Execução interrompida"
        if (root.statusText === "Interrompido") return "Execução interrompida pelo usuário"
        return "Trabalhou por " + root.elapsedLabel
    }

    function stateColor(state) {
        if (state === "completed") return frontend.palette.success
        if (state === "error" || state === "cancelled") return frontend.palette.danger
        if (state === "running") return frontend.palette.brandOrange
        return frontend.palette.mutedText
    }

    function stateLabel(state) {
        if (state === "completed") return "concluído"
        if (state === "error") return "falhou"
        if (state === "cancelled") return "interrompido"
        if (state === "running") return "agora"
        return ""
    }
}
