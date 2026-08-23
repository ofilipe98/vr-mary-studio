import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    objectName: "chatActivity"

    property var steps: []
    property string reasoningText: ""
    property string statusText: "Pronto"
    property bool running: false
    property bool expanded: true
    signal toggleRequested()

    implicitHeight: content.implicitHeight + 6
    color: "transparent"

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 3

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: frontend.palette.chatDivider
            opacity: 0.65
        }

        Rectangle {
            id: activityHeader
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            radius: 6
            color: activityHover.hovered ? frontend.palette.hover : "transparent"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 3
                anchors.rightMargin: 4
                spacing: 8

                VrLineIcon {
                    Layout.preferredWidth: 13
                    Layout.preferredHeight: 13
                    kind: root.expanded ? "chevronDown" : "chevronUp"
                    foreground: frontend.palette.mutedText
                }

                Row {
                    visible: root.steps.length > 0
                    spacing: 3
                    Repeater {
                        model: Math.min(7, root.steps.length)
                        delegate: Rectangle {
                            required property int index
                            width: 9
                            height: 3
                            radius: 2
                            color: {
                                var step = root.steps[index] || ({})
                                if (step.state === "completed") return frontend.palette.success
                                if (step.state === "error") return frontend.palette.danger
                                if (step.state === "running") return frontend.palette.brandOrange
                                return frontend.palette.chatBorder
                            }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.summaryText()
                    color: root.running ? frontend.palette.mutedText : frontend.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    font.weight: root.running ? Font.Normal : Font.DemiBold
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }

                Text {
                    visible: root.steps.length > 0
                    text: root.completedCount() + "/" + root.steps.length
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: 10
                }
            }

            HoverHandler { id: activityHover }
            TapHandler { onTapped: root.toggleRequested() }
        }

        Text {
            visible: !root.expanded && root.reasoningText.length > 0
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 8
            text: "Pensamento · " + root.reasoningPreview()
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: 10
            horizontalAlignment: Text.AlignLeft
            elide: Text.ElideRight
        }

        ColumnLayout {
            visible: root.expanded
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 8
            spacing: 4

            Rectangle {
                visible: root.reasoningText.length > 0
                Layout.fillWidth: true
                Layout.preferredHeight: reasoningColumn.implicitHeight + 14
                radius: 7
                color: frontend.themeId === "dark_orange" ? "#111113" : "#F2F2F5"

                ColumnLayout {
                    id: reasoningColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 9
                    anchors.rightMargin: 9
                    spacing: 3
                    Text {
                        Layout.fillWidth: true
                        text: "Pensamento"
                        color: frontend.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignLeft
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.reasoningText
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: 10
                        lineHeight: 1.35
                        horizontalAlignment: Text.AlignLeft
                        wrapMode: Text.WordWrap
                        maximumLineCount: 5
                        elide: Text.ElideRight
                    }
                }
            }

            Repeater {
                model: root.steps.slice(Math.max(0, root.steps.length - 10))
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        Layout.preferredWidth: 12
                        text: modelData.state === "completed" ? "✓"
                            : modelData.state === "error" ? "!" : "·"
                        color: modelData.state === "completed" ? frontend.palette.success
                            : modelData.state === "error" ? frontend.palette.danger
                            : modelData.state === "running" ? frontend.palette.brandOrange
                            : frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.text
                        color: modelData.state === "running"
                            ? frontend.palette.text : frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: 10
                        lineHeight: 1.3
                        horizontalAlignment: Text.AlignLeft
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }

    function completedCount() {
        var completed = 0
        for (var index = 0; index < root.steps.length; ++index) {
            if (String(root.steps[index].state || "") === "completed") completed += 1
        }
        return completed
    }

    function summaryText() {
        if (root.statusText === "Erro") return "Execução interrompida"
        if (!root.running) return "Planejamento e execução concluídos"
        for (var index = 0; index < root.steps.length; ++index) {
            if (String(root.steps[index].state || "") === "running")
                return String(root.steps[index].text || root.statusText)
        }
        return root.statusText === "Pronto" ? "Trabalhando…" : root.statusText
    }

    function reasoningPreview() {
        var value = String(root.reasoningText || "").replace(/\s+/g, " ").trim()
        if (value.length > 180) return "…" + value.substring(value.length - 179)
        return value
    }
}
