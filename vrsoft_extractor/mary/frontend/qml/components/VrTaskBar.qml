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

    implicitHeight: root.expanded
        ? Math.max(Theme.scaledGeometry(160), Math.min(root.maximumListHeight, content.implicitHeight + Theme.scaledGeometry(12)))
        : Theme.scaledGeometry(36)
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
        anchors.top: parent.top
        anchors.leftMargin: Theme.scaledGeometry(8)
        anchors.rightMargin: Theme.scaledGeometry(8)
        spacing: 0

        Item {
            id: taskHeader
            objectName: "taskPlanHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(36)

            RowLayout {
                anchors.fill: parent
                spacing: Theme.scaledGeometry(6)

                Item {
                    Layout.preferredWidth: Theme.scaledGeometry(20)
                    Layout.preferredHeight: Theme.scaledGeometry(20)
                    VrLineIcon {
                        anchors.centerIn: parent
                        width: Theme.scaledGeometry(14)
                        height: Theme.scaledGeometry(14)
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
                    color: Theme.palette.headingText || "#E6E6E6"
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
                        return root.effectiveCompleted() + "/" + total;
                    }
                    color: root.effectiveCompleted() === root.effectiveTotal() ? Theme.palette.success : Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: Font.Medium
                }
                VrProgressBar {
                    objectName: "taskPlanProgress"
                    visible: root.effectiveTotal() > 0 && root.width >= 480
                    Layout.preferredWidth: Theme.scaledGeometry(80)
                    Layout.preferredHeight: Theme.scaledGeometry(3)
                    barHeight: Theme.scaledGeometry(3)
                    from: 0
                    to: root.effectiveTotal()
                    value: root.effectiveCompleted()
                    segments: root.effectiveTotal() <= 10 ? root.effectiveTotal() : 0
                    activeSegment: root.running ? root.effectiveCompleted() : -1
                    accentColor: root.effectiveCompleted() >= root.effectiveTotal()
                        ? Theme.palette.success : Theme.palette.brandOrange
                    Accessible.name: "Progresso das tarefas"
                }
                VrLineIcon {
                    Layout.preferredWidth: Theme.scaledGeometry(18)
                    Layout.preferredHeight: Theme.scaledGeometry(18)
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
                    delegate: Rectangle {
                        required property int index
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: Theme.scaledGeometry(26)
                        color: taskHover.hovered ? Theme.palette.hoverBackground : "transparent"
                        radius: Theme.scaledGeometry(4)

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.scaledGeometry(8)
                            anchors.rightMargin: Theme.scaledGeometry(8)
                            spacing: Theme.scaledGeometry(6)

                            VrLineIcon {
                                Layout.preferredWidth: Theme.iconMicro
                                Layout.preferredHeight: Theme.iconMicro
                                kind: {
                                    var state = modelData.state || modelData.status || ""
                                    if (state === "completed" || state === "done") return "check"
                                    if (state === "running" || state === "in_progress") return "loader"
                                    if (state === "failed" || state === "error") return "alertTriangle"
                                    return "circle"
                                }
                                foreground: {
                                    var state = modelData.state || modelData.status || ""
                                    if (state === "completed" || state === "done") return Theme.palette.success
                                    if (state === "running" || state === "in_progress") return Theme.palette.brandOrange
                                    if (state === "failed" || state === "error") return Theme.palette.danger
                                    return Theme.palette.mutedText
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: modelData.text || modelData.step || modelData.title || ""
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                elide: Text.ElideRight
                                maximumLineCount: 1
                            }
                        }

                        HoverHandler { id: taskHover }
                    }
                }
            }
        }
    }

    function effectiveTotal() {
        if (progress && typeof progress.total === "number" && progress.total > 0)
            return progress.total
        if (steps && steps.length > 0)
            return steps.length
        return 0
    }

    function effectiveCompleted() {
        if (progress && typeof progress.completed === "number")
            return progress.completed
        if (steps && steps.length > 0) {
            var c = 0
            for (var i = 0; i < steps.length; ++i) {
                var s = steps[i].state || steps[i].status || ""
                if (s === "completed" || s === "done")
                    c++
            }
            return c
        }
        return 0
    }

    function effectiveCurrentStep() {
        if (steps && steps.length > 0) {
            for (var i = 0; i < steps.length; ++i) {
                var s = steps[i].state || steps[i].status || ""
                if (s === "running" || s === "in_progress")
                    return steps[i].text || steps[i].step || steps[i].title || ""
            }
            for (var j = 0; j < steps.length; ++j) {
                var st = steps[j].state || steps[j].status || ""
                if (st !== "completed" && st !== "done")
                    return steps[j].text || steps[j].step || steps[j].title || ""
            }
        }
        if (progress && progress.currentStep)
            return progress.currentStep
        return ""
    }
}
