import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    objectName: "chatTaskBar"

    property var steps: []
    property var progress: ({})
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
        radius: Theme.scaledGeometry(16)
        color: Qt.alpha(Theme.palette.chatComposer, Theme.glassOpacity)
        border.width: 1
        border.color: Theme.palette.chatBorder
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Theme.scaledGeometry(4)
        anchors.rightMargin: Theme.scaledGeometry(4)
        spacing: 0

        Item {
            id: taskHeader
            objectName: "taskPlanHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(24)

            RowLayout {
                anchors.fill: parent
                spacing: Theme.scaledGeometry(4)

                Item {
                    Layout.preferredWidth: Theme.scaledGeometry(24)
                    Layout.preferredHeight: Theme.scaledGeometry(24)
                    VrLineIcon {
                        anchors.centerIn: parent
                        width: Theme.iconMicro
                        height: Theme.iconMicro
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
                    text: root.effectiveCurrentStep()
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
                Text {
                    text: {
                        var total = root.effectiveTotal();
                        if (total <= 0)
                            return "";
                        var label = root.effectiveCompleted() + "/" + total;
                        if (root.width >= 400)
                            label += " concluídas · " + Math.round(100 * root.effectiveCompleted() / total) + "%";
                        return label;
                    }
                    color: root.effectiveCompleted() === root.effectiveTotal() ? Theme.palette.success : Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: Font.Medium
                }
                VrProgressBar {
                    objectName: "taskPlanProgress"
                    visible: root.effectiveTotal() > 0 && root.width >= 600
                    Layout.preferredWidth: Theme.scaledGeometry(80)
                    Layout.preferredHeight: Theme.scaledGeometry(4)
                    barHeight: Theme.scaledGeometry(4)
                    from: 0
                    to: root.effectiveTotal()
                    value: root.effectiveCompleted()
                    accentColor: root.effectiveCompleted() >= root.effectiveTotal()
                        ? Theme.palette.success : Theme.palette.brandOrange
                    Accessible.name: "Progresso das tarefas"
                }
                VrLineIcon {
                    Layout.preferredWidth: Theme.scaledGeometry(24)
                    Layout.preferredHeight: Theme.iconCompact
                    kind: root.expanded ? "chevronDown" : "chevronUp"
                    foreground: Theme.palette.mutedText
                }
            }

            HoverHandler { id: headerHover }
            TapHandler { onTapped: root.toggleRequested() }
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: "Tarefas: " + root.effectiveCompleted() + " de " + root.effectiveTotal()
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
                        Layout.minimumHeight: Theme.scaledGeometry(20)
                        spacing: Theme.scaledGeometry(4)

                        Item {
                            Layout.preferredWidth: Theme.scaledGeometry(24)
                            Layout.preferredHeight: Theme.scaledGeometry(20)
                            VrLineIcon {
                                visible: modelData.state === "completed"
                                anchors.centerIn: parent
                                width: Theme.iconMicro
                                height: Theme.iconMicro
                                kind: "check"
                                foreground: Theme.palette.success
                            }
                            Rectangle {
                                visible: modelData.state !== "completed"
                                anchors.centerIn: parent
                                width: Theme.scaledGeometry(6)
                                height: Theme.scaledGeometry(6)
                                radius: Theme.scaledGeometry(3)
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
                            Layout.preferredWidth: Theme.scaledGeometry(40)
                            Layout.rightMargin: Theme.scaledGeometry(4)
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

    function hasBackendProgress() {
        return root.progress !== undefined && root.progress !== null
            && Number(root.progress.total || 0) > 0
    }

    function effectiveCompleted() {
        if (root.hasBackendProgress())
            return Number(root.progress.completed || 0)
        return root.completedCount()
    }

    function effectiveTotal() {
        if (root.hasBackendProgress())
            return Number(root.progress.total || 0)
        return root.steps.length
    }

    function effectiveCurrentStep() {
        if (root.hasBackendProgress()) {
            var backendStep = String(root.progress.step || "")
            if (backendStep.length > 0)
                return backendStep
        }
        return root.currentStepText()
    }

    function durationText(milliseconds) {
        var seconds = Math.floor(milliseconds / 1000)
        return seconds >= 60 ? Math.floor(seconds / 60) + "m " + (seconds % 60) + "s" : seconds + "s"
    }
}
