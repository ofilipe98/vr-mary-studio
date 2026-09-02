import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    objectName: "chatTaskBar"

    property var steps: []
    property bool running: false
    property bool expanded: true
    signal toggleRequested()
    signal closeRequested()

    implicitHeight: content.implicitHeight + 8
    color: "transparent"
    clip: true

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        spacing: 4

        Item {
            id: taskHeader
            Layout.fillWidth: true
            Layout.preferredHeight: 30

            RowLayout {
                anchors.fill: parent
                spacing: 7

                Text {
                    text: "Tarefas"
                    color: frontend.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(11)
                    font.weight: Font.DemiBold
                }
                Text {
                    text: root.completedCount() + "/" + root.steps.length
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(10)
                }
                Text {
                    visible: !root.expanded
                    Layout.fillWidth: true
                    text: root.currentStepText()
                    color: frontend.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(11)
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Item { visible: root.expanded; Layout.fillWidth: true }
                Row {
                    visible: !root.expanded && root.steps.length > 0
                    spacing: 3
                    Repeater {
                        model: Math.min(6, root.steps.length)
                        delegate: Rectangle {
                            required property int index
                            width: 13
                            height: 3
                            radius: 2
                            color: root.segmentColor(index)
                        }
                    }
                }
                VrLineIcon {
                    Layout.preferredWidth: 13
                    Layout.preferredHeight: 13
                    kind: root.expanded ? "chevronDown" : "chevronUp"
                    foreground: frontend.palette.mutedText
                }
                VrIconButton {
                    implicitWidth: 26
                    implicitHeight: 26
                    iconSize: 12
                    iconKind: "close"
                    foreground: frontend.palette.mutedText
                    ToolTip.visible: hovered
                    ToolTip.text: "Fechar tarefas"
                    onClicked: root.closeRequested()
                }
            }

            HoverHandler { id: headerHover }
            TapHandler { onTapped: root.toggleRequested() }
        }

        ColumnLayout {
            visible: root.expanded
            Layout.fillWidth: true
            Layout.leftMargin: 4
            Layout.rightMargin: 30
            Layout.bottomMargin: 2
            spacing: 5

            Repeater {
                model: root.steps.slice(0, 8)
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8

                    Rectangle {
                        Layout.preferredWidth: 7
                        Layout.preferredHeight: 7
                        radius: 4
                        color: root.stateColor(String(modelData.state || "pending"))
                        border.width: modelData.state === "pending" ? 1 : 0
                        border.color: frontend.palette.mutedText
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.text || ""
                        color: modelData.state === "running"
                            ? frontend.palette.text : frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(10)
                        font.weight: modelData.state === "running" ? Font.DemiBold : Font.Normal
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Text {
                        visible: modelData.state === "running"
                        text: "agora"
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(9)
                    }
                }
            }
        }
    }

    function completedCount() {
        var completed = 0
        for (var index = 0; index < root.steps.length; ++index)
            if (String(root.steps[index].state || "") === "completed") completed += 1
        return completed
    }

    function currentStepText() {
        for (var index = 0; index < root.steps.length; ++index)
            if (String(root.steps[index].state || "") === "running")
                return String(root.steps[index].text || "")
        if (root.running) return "Preparando a próxima etapa…"
        return root.steps.length ? "Tarefas concluídas" : ""
    }

    function stateColor(state) {
        if (state === "completed") return frontend.palette.success
        if (state === "error" || state === "cancelled") return frontend.palette.danger
        if (state === "running") return frontend.palette.brandOrange
        return "transparent"
    }

    function segmentColor(index) {
        var step = root.steps[index] || ({})
        return root.stateColor(String(step.state || "pending")) === "transparent"
            ? frontend.palette.chatBorder : root.stateColor(String(step.state || "pending"))
    }
}
