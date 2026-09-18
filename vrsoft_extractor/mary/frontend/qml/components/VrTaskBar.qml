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
    property real maximumListHeight: 384
    signal toggleRequested()

    implicitHeight: content.implicitHeight + 10
    color: "transparent"
    clip: true

    // Clip the lower corners below the seam, as in an attached composer banner.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: parent.height + 16
        radius: 16
        color: Qt.alpha(Theme.palette.chatComposer, Theme.glassOpacity)
        border.width: 1
        border.color: Theme.palette.chatBorder
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        spacing: 0

        Item {
            id: taskHeader
            objectName: "taskPlanHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: 24

            RowLayout {
                anchors.fill: parent
                spacing: 4

                Item {
                    Layout.preferredWidth: 24
                    Layout.preferredHeight: 24
                    VrLineIcon {
                        anchors.centerIn: parent
                        width: 12
                        height: 12
                        kind: "listTodo"
                        foreground: Theme.palette.mutedText
                    }
                }

                Text {
                    text: "Tarefas"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                }
                Text {
                    Layout.fillWidth: true
                    text: root.currentStepText()
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                }
                Text {
                    text: root.completedCount() + "/" + root.steps.length + (root.width >= 400 ? " concluídas" : "")
                    color: root.completedCount() === root.steps.length ? Theme.palette.success : Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: Font.Medium
                }
                Row {
                    visible: root.steps.length > 1 && root.steps.length <= 10 && root.width >= 600
                    spacing: 2
                    Repeater {
                        model: root.steps.length
                        delegate: Rectangle {
                            required property int index
                            width: (80 - (root.steps.length - 1) * 2) / root.steps.length
                            height: 3
                            radius: 2
                            color: root.segmentColor(index)
                        }
                    }
                }
                VrLineIcon {
                    Layout.preferredWidth: 24
                    Layout.preferredHeight: 14
                    kind: root.expanded ? "chevronDown" : "chevronUp"
                    foreground: Theme.palette.mutedText
                }
            }

            HoverHandler { id: headerHover }
            TapHandler { onTapped: root.toggleRequested() }
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: "Tarefas: " + root.completedCount() + " de " + root.steps.length
            Accessible.onPressAction: root.toggleRequested()
            Keys.onSpacePressed: root.toggleRequested()
            Keys.onReturnPressed: root.toggleRequested()
        }

        ScrollView {
            id: taskScroll
            objectName: "taskPlanScroll"
            visible: root.expanded
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(taskList.implicitHeight, root.maximumListHeight)
            contentWidth: availableWidth
            contentHeight: taskList.implicitHeight
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                id: taskList
                width: taskScroll.availableWidth
                spacing: 1

                Repeater {
                    model: root.steps
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.minimumHeight: 20
                        spacing: 4

                        Item {
                            Layout.preferredWidth: 24
                            Layout.preferredHeight: 20
                            VrLineIcon {
                                visible: modelData.state === "completed"
                                anchors.centerIn: parent
                                width: 10
                                height: 10
                                kind: "check"
                                foreground: Theme.palette.success
                            }
                            Rectangle {
                                visible: modelData.state !== "completed"
                                anchors.centerIn: parent
                                width: 6
                                height: 6
                                radius: 3
                                color: modelData.state === "running" ? Theme.palette.brandOrange : "transparent"
                                border.width: modelData.state === "pending" ? 1 : 0
                                border.color: Theme.palette.mutedText
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.text || ""
                            color: modelData.state === "running"
                                ? Theme.palette.text : Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            opacity: modelData.state === "completed" ? 0.65 : 1
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            text: modelData.state === "completed" ? "Concluída"
                                : modelData.state === "running" ? "Executando" : "Pendente"
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeMicro
                        }
                        Text {
                            Layout.preferredWidth: 40
                            Layout.rightMargin: 4
                            horizontalAlignment: Text.AlignRight
                            text: modelData.durationMs !== undefined
                                ? root.durationText(modelData.durationMs)
                                : modelData.state === "running" ? "agora" : ""
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeMicro
                        }
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
        for (var pendingIndex = 0; pendingIndex < root.steps.length; ++pendingIndex)
            if (String(root.steps[pendingIndex].state || "") === "pending")
                return String(root.steps[pendingIndex].text || "")
        return root.steps.length && root.completedCount() === root.steps.length
            ? "Tarefas concluídas" : ""
    }

    function durationText(milliseconds) {
        var seconds = Math.floor(milliseconds / 1000)
        return seconds >= 60 ? Math.floor(seconds / 60) + "m " + (seconds % 60) + "s" : seconds + "s"
    }

    function stateColor(state) {
        if (state === "completed") return Theme.palette.success
        if (state === "error" || state === "cancelled") return Theme.palette.danger
        if (state === "running") return Theme.palette.brandOrange
        return "transparent"
    }

    function segmentColor(index) {
        var step = root.steps[index] || ({})
        return root.stateColor(String(step.state || "pending")) === "transparent"
            ? Theme.palette.chatBorder : root.stateColor(String(step.state || "pending"))
    }
}
