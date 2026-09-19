import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "commandCard"

    property var modelData: ({})
    property bool detailExpanded: false
    property bool copiedCmd: false
    property bool copiedOutput: false

    readonly property string commandText: String(modelData.command || modelData.text || "Comando")
    readonly property string outputText: String(modelData.output || modelData.detail || "")
    readonly property string errorDetailsText: String(modelData.errorDetails || "")
    readonly property string errorSummaryText: String(modelData.errorSummary || "")
    readonly property string stateValue: String(modelData.state || "running")
    readonly property bool isRunning: stateValue === "running"
    readonly property bool isError: stateValue === "error" || stateValue === "failed"
    readonly property bool isSuccess: stateValue === "completed" || stateValue === "success"
    readonly property bool isWaitingApproval: stateValue === "waiting_approval"

    implicitHeight: mainColumn.implicitHeight

    Timer {
        id: copyCmdTimer
        interval: 1500
        onTriggered: root.copiedCmd = false
    }

    Timer {
        id: copyOutputTimer
        interval: 1500
        onTriggered: root.copiedOutput = false
    }

    ColumnLayout {
        id: mainColumn
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 4

        // Header Row
        Rectangle {
            id: headerBox
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: root.commandText
            Accessible.description: root.detailExpanded ? "Recolher comando" : "Expandir comando"
            Keys.onReturnPressed: root.detailExpanded = !root.detailExpanded
            Keys.onSpacePressed: root.detailExpanded = !root.detailExpanded
            border.width: activeFocus ? 1 : 0
            border.color: Theme.palette.focus
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            radius: 4
            color: headerHover.hovered ? Theme.palette.hover : "transparent"
            clip: true

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 6
                spacing: 7

                VrLineIcon {
                    Layout.preferredWidth: 14
                    Layout.preferredHeight: 14
                    kind: root.isError ? "close" : (root.isSuccess ? "check" : (root.isWaitingApproval ? "alert" : "terminalPrompt"))
                    foreground: root.isError
                        ? Theme.palette.danger
                        : (root.isSuccess
                            ? Theme.palette.success
                            : (root.isWaitingApproval ? Theme.palette.warning : Theme.palette.mutedText))
                }

                Text {
                    Layout.fillWidth: true
                    text: root.commandText
                    color: root.isError
                        ? Theme.palette.danger
                        : (root.isWaitingApproval
                            ? Theme.palette.warning
                            : (root.isRunning ? Theme.palette.text : Theme.palette.mutedText))
                    font.family: Theme.monospaceFontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: (root.isRunning || root.isWaitingApproval) ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                    renderType: Theme.textRenderType
                }

                // Duration badge
                Text {
                    visible: String(root.modelData.durationLabel || "").length > 0
                    text: String(root.modelData.durationLabel || "")
                    color: Theme.palette.mutedText
                    font.family: Theme.monospaceFontFamily
                    font.pixelSize: Theme.fontSizeMicro
                    renderType: Theme.textRenderType
                }

                // Status / Exit code badge
                Rectangle {
                    visible: String(root.modelData.badgeText || "").length > 0
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: badgeLabel.implicitWidth + 10
                    radius: 3
                    color: root.isError
                        ? Qt.rgba(Theme.palette.danger.r, Theme.palette.danger.g, Theme.palette.danger.b, 0.15)
                        : (root.isSuccess
                            ? Qt.rgba(Theme.palette.success.r, Theme.palette.success.g, Theme.palette.success.b, 0.15)
                            : (root.isWaitingApproval
                                ? Qt.rgba(Theme.palette.warning.r, Theme.palette.warning.g, Theme.palette.warning.b, 0.15)
                                : Qt.rgba(Theme.palette.mutedText.r, Theme.palette.mutedText.g, Theme.palette.mutedText.b, 0.12)))

                    Text {
                        id: badgeLabel
                        anchors.centerIn: parent
                        text: String(root.modelData.badgeText || "")
                        color: root.isError
                            ? Theme.palette.danger
                            : (root.isSuccess
                                ? Theme.palette.success
                                : (root.isWaitingApproval ? Theme.palette.warning : Theme.palette.mutedText))
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        font.weight: Font.Medium
                        renderType: Theme.textRenderType
                    }
                }

                VrLineIcon {
                    Layout.preferredWidth: 9
                    Layout.preferredHeight: 9
                    kind: root.detailExpanded ? "chevronDown" : "chevronRight"
                    foreground: Theme.palette.mutedText
                }
            }

            // Specular highlight shimmer animation on running tool call (disabled when reduceMotion is set)
            Rectangle {
                id: specularShimmer
                anchors.fill: parent
                radius: parent.radius
                clip: true
                color: "transparent"
                visible: root.isRunning && !(typeof frontend !== "undefined" && frontend.reduceMotion)

                Rectangle {
                    id: shimmerBeam
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: Math.max(120, parent.width * 0.4)
                    x: -width
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 0.35; color: Qt.rgba(255, 255, 255, 0.0) }
                        GradientStop { position: 0.5; color: Qt.rgba(255, 255, 255, 0.28) }
                        GradientStop { position: 0.65; color: Qt.rgba(255, 255, 255, 0.0) }
                        GradientStop { position: 1.0; color: "transparent" }
                    }
                    NumberAnimation on x {
                        running: root.isRunning && !(typeof frontend !== "undefined" && frontend.reduceMotion)
                        from: -shimmerBeam.width
                        to: specularShimmer.width + shimmerBeam.width
                        duration: 1500
                        loops: Animation.Infinite
                        easing.type: Easing.Linear
                    }
                }
            }

            HoverHandler { id: headerHover }
            TapHandler {
                onTapped: root.detailExpanded = !root.detailExpanded
            }
        }

        // Expandable Detail Body
        Rectangle {
            visible: root.detailExpanded
            Layout.fillWidth: true
            Layout.preferredHeight: detailContent.implicitHeight + 16
            radius: 6
            color: Theme.palette.surfaceRaised
            border.width: 1
            border.color: Theme.palette.chatBorder
            clip: true

            ColumnLayout {
                id: detailContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 8
                spacing: 6

                // Action / Metadata bar
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        visible: String(root.modelData.cwd || "").length > 0
                        Layout.fillWidth: true
                        text: "cwd: " + String(root.modelData.cwd || "")
                        color: Theme.palette.mutedText
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        elide: Text.ElideMiddle
                        renderType: Theme.textRenderType
                    }

                    Text {
                        visible: root.modelData.exitCode !== undefined && root.modelData.exitCode !== null
                        text: "exit: " + root.modelData.exitCode
                        color: Number(root.modelData.exitCode) === 0 ? Theme.palette.success : Theme.palette.danger
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        renderType: Theme.textRenderType
                    }

                    Item {
                        visible: !root.modelData.cwd && (root.modelData.exitCode === undefined || root.modelData.exitCode === null)
                        Layout.fillWidth: true
                    }

                    // Copy command button
                    Rectangle {
                        Layout.preferredHeight: 22
                        Layout.preferredWidth: copyCmdText.implicitWidth + 12
                        radius: 3
                        color: copyCmdHover.hovered ? Theme.palette.hover : "transparent"
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        Text {
                            id: copyCmdText
                            anchors.centerIn: parent
                            text: root.copiedCmd ? "Copiado!" : "Copiar cmd"
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeMicro
                            renderType: Theme.textRenderType
                        }
                        HoverHandler { id: copyCmdHover }
                        TapHandler {
                            onTapped: {
                                if (typeof studio !== "undefined" && studio) {
                                    studio.copyText(root.commandText)
                                }
                                root.copiedCmd = true
                                copyCmdTimer.restart()
                            }
                        }
                    }

                    // Copy output button
                    Rectangle {
                        visible: root.outputText.length > 0
                        Layout.preferredHeight: 22
                        Layout.preferredWidth: copyOutputText.implicitWidth + 12
                        radius: 3
                        color: copyOutputHover.hovered ? Theme.palette.hover : "transparent"
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        Text {
                            id: copyOutputText
                            anchors.centerIn: parent
                            text: root.copiedOutput ? "Copiado!" : "Copiar saída"
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeMicro
                            renderType: Theme.textRenderType
                        }
                        HoverHandler { id: copyOutputHover }
                        TapHandler {
                            onTapped: {
                                if (typeof studio !== "undefined" && studio) {
                                    studio.copyText(root.outputText)
                                }
                                root.copiedOutput = true
                                copyOutputTimer.restart()
                            }
                        }
                    }
                }

                // Error Details Panel (isolated stack trace / error summary)
                Rectangle {
                    visible: root.isError && (root.errorDetailsText.length > 0 || root.errorSummaryText.length > 0)
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(errorColumn.implicitHeight + 12, 180)
                    radius: 4
                    color: Qt.rgba(Theme.palette.danger.r, Theme.palette.danger.g, Theme.palette.danger.b, 0.08)
                    border.width: 1
                    border.color: Qt.rgba(Theme.palette.danger.r, Theme.palette.danger.g, Theme.palette.danger.b, 0.3)
                    clip: true

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 6
                        clip: true
                        contentWidth: availableWidth

                        ColumnLayout {
                            id: errorColumn
                            width: parent.width
                            spacing: 4

                            Text {
                                visible: root.errorSummaryText.length > 0
                                Layout.fillWidth: true
                                text: root.errorSummaryText
                                color: Theme.palette.danger
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeMicro
                                font.weight: Font.DemiBold
                                wrapMode: Text.Wrap
                                renderType: Theme.textRenderType
                            }

                            TextArea {
                                visible: root.errorDetailsText.length > 0
                                Layout.fillWidth: true
                                text: root.errorDetailsText
                                textFormat: TextEdit.PlainText
                                readOnly: true
                                selectByMouse: true
                                wrapMode: TextEdit.WrapAnywhere
                                color: Theme.palette.danger
                                font.family: Theme.monospaceFontFamily
                                font.pixelSize: Theme.fontSizeMicro
                                background: Item { }
                            }
                        }
                    }
                }

                // Terminal Console Output Box
                Rectangle {
                    visible: root.outputText.length > 0
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(outputArea.implicitHeight + 16, 220)
                    radius: 4
                    color: Theme.palette.chatBackground
                    border.width: 1
                    border.color: Theme.palette.chatBorder
                    clip: true

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 8
                        clip: true
                        contentWidth: availableWidth

                        TextArea {
                            id: outputArea
                            text: root.outputText
                            textFormat: TextEdit.PlainText
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.WrapAnywhere
                            color: Theme.palette.mutedText
                            font.family: Theme.monospaceFontFamily
                            font.pixelSize: Theme.fontSizeMicro
                            background: Item { }
                        }
                    }
                }
            }
        }
    }
}
