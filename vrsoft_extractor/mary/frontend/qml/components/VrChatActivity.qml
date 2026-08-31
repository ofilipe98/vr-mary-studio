import QtQuick
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
    property int recentCount: 6
    property bool logExpanded: false
    readonly property int hiddenCount: Math.max(0, items.length - recentCount)
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
                    text: root.headerText()
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(11)
                    font.weight: root.running ? Font.DemiBold : Font.Normal
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }
                Text {
                    visible: root.items.length > 0
                    text: root.completedItemCount() + "/" + root.items.length
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(9)
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

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: frontend.palette.chatDivider
            opacity: 0.65
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
                font.pixelSize: Theme.fontSize(11)
                lineHeightMode: Text.ProportionalHeight
                lineHeight: 1.35
                horizontalAlignment: Text.AlignLeft
                wrapMode: Text.WordWrap
            }

            Rectangle {
                visible: root.hiddenCount > 0
                Layout.fillWidth: true
                Layout.preferredHeight: 24
                radius: 7
                color: logToggleHover.hovered ? frontend.palette.hover : "transparent"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    anchors.rightMargin: 6
                    spacing: 6

                    VrLineIcon {
                        Layout.preferredWidth: 11
                        Layout.preferredHeight: 11
                        kind: root.logExpanded ? "chevronUp" : "chevronRight"
                        foreground: frontend.palette.mutedText
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "+" + root.hiddenCount + " entradas anteriores de log"
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(10)
                    }
                }

                HoverHandler { id: logToggleHover }
                TapHandler { onTapped: root.logExpanded = !root.logExpanded }
            }

            Repeater {
                model: root.visibleItems()
                delegate: ColumnLayout {
                    id: activityItem
                    required property var modelData
                    property bool detailExpanded: false
                    readonly property bool isCommand:
                        String(modelData.itemType || "") === "commandExecution"
                    Layout.fillWidth: true
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        VrLineIcon {
                            Layout.preferredWidth: 13
                            Layout.preferredHeight: 13
                            kind: root.itemIcon(activityItem.modelData)
                            foreground: root.stateColor(activityItem.modelData.state)
                        }
                        Text {
                            Layout.fillWidth: true
                            text: activityItem.isCommand
                                ? "bash" : (activityItem.modelData.text || "Atividade")
                            color: activityItem.modelData.state === "running"
                                ? frontend.palette.text : frontend.palette.mutedText
                            font.family: activityItem.isCommand
                                ? "Cascadia Mono" : Theme.fontFamily
                            font.pixelSize: Theme.fontSize(
                                activityItem.isCommand ? 10 : 10)
                            font.weight: activityItem.modelData.state === "running"
                                && !activityItem.isCommand
                                ? Font.DemiBold : Font.Normal
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        Text {
                            text: root.stateLabel(activityItem.modelData.state)
                            color: root.stateColor(activityItem.modelData.state)
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(9)
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
                            font.pixelSize: Theme.fontSize(9)
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }
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

    function headerText() {
        if (root.running) return "Trabalhando por " + root.elapsedLabel
        if (root.statusText === "Erro") return "Falhou após " + root.elapsedLabel
        if (root.statusText === "Interrompido")
            return "Interrompido após " + root.elapsedLabel
        return "Trabalhou por " + root.elapsedLabel
    }

    function itemIcon(item) {
        var itemType = String(item.itemType || "")
        if (itemType === "fileChange") return "edit"
        if (itemType === "commandExecution") return "terminal"
        if (itemType === "webSearch" || itemType === "web_search") return "search"
        if (itemType === "reasoning") return "auto"
        if (String(item.kind || "") === "tool") return "terminal"
        return "task"
    }

    function visibleItems() {
        if (root.logExpanded || root.items.length <= root.recentCount)
            return root.items
        return root.items.slice(root.items.length - root.recentCount)
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
