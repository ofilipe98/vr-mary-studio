import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

// Command execution rendered with the same T3 Code activity row as other tool
// calls: terminal icon, monospaced command label, duration and rotating
// chevron. The expanded body holds exit/cwd metadata, the isolated error
// disclosure and the raw output, all selectable natively.
Item {
    id: root
    objectName: "commandCard"

    property var modelData: ({})
    property bool detailExpanded: false

    readonly property string commandText: String(modelData.command || modelData.text || "Comando")
    readonly property string outputText: String(modelData.output || modelData.detail || "")
    readonly property string errorDetailsText: String(modelData.errorDetails || "")
    readonly property string errorSummaryText: String(modelData.errorSummary || "")
    readonly property string durationLabel: String(modelData.durationLabel || "")
    readonly property string stateValue: String(modelData.state || "running")
    readonly property bool isRunning: stateValue === "running"
    readonly property bool isError: stateValue === "error" || stateValue === "failed"
    readonly property bool isSuccess: stateValue === "completed" || stateValue === "success"
    readonly property bool isWaitingApproval: stateValue === "waiting_approval"
    readonly property bool hasCwd: String(modelData.cwd || "").length > 0
    readonly property bool hasExitCode: modelData.exitCode !== undefined && modelData.exitCode !== null
    readonly property bool canExpand: root.outputText.length > 0
        || (root.isError && (root.errorDetailsText.length > 0 || root.errorSummaryText.length > 0))
        || root.hasCwd || root.hasExitCode
    readonly property bool reduceMotion: typeof frontend !== "undefined" && frontend !== null
        ? frontend.reduceMotion : false
    readonly property color insetSurface: Qt.rgba(
        Theme.palette.chatControl.r, Theme.palette.chatControl.g,
        Theme.palette.chatControl.b, Theme.palette.appearance === "light" ? 0.55 : 0.45)

    implicitHeight: mainColumn.implicitHeight

    ColumnLayout {
        id: mainColumn
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.scaledGeometry(4)

        Rectangle {
            id: header
            objectName: "commandHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(28)
            radius: Theme.scaledGeometry(6)
            color: hover.hovered ? Theme.palette.hover : "transparent"
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: root.commandText
            Accessible.description: root.detailExpanded ? "Recolher comando" : "Expandir comando"
            border.width: activeFocus ? 1 : 0
            border.color: Theme.palette.focus
            Keys.onReturnPressed: { if (root.canExpand) root.detailExpanded = !root.detailExpanded }
            Keys.onSpacePressed: { if (root.canExpand) root.detailExpanded = !root.detailExpanded }
            Behavior on color { ColorAnimation { duration: Theme.fastDuration } }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(2)
                anchors.rightMargin: Theme.scaledGeometry(2)
                spacing: Theme.scaledGeometry(6)

                Item {
                    Layout.preferredWidth: Theme.scaledGeometry(24)
                    Layout.preferredHeight: Theme.scaledGeometry(24)
                    VrLineIcon {
                        anchors.centerIn: parent
                        width: Theme.iconSmall
                        height: Theme.iconSmall
                        kind: root.isError ? "circleAlert" : "terminal"
                        opacity: root.isError ? 0.75 : 0.9
                        foreground: root.isError
                            ? Theme.palette.danger
                            : (root.isWaitingApproval ? Theme.palette.warning : Theme.palette.mutedText)
                    }
                }

                VrShimmerText {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: root.commandText
                    running: root.isRunning
                    color: root.isError
                        ? Theme.palette.danger
                        : (root.isWaitingApproval
                            ? Theme.palette.warning
                            : (root.isRunning ? Theme.palette.text : Theme.palette.mutedText))
                    font.family: Theme.monospaceFontFamily
                    font.pixelSize: Theme.monospaceFontSize(12)
                    elide: Text.ElideRight
                    renderType: Theme.textRenderType
                }

                Text {
                    visible: root.durationLabel.length > 0
                    text: root.durationLabel
                    color: Theme.palette.mutedText
                    opacity: 0.8
                    font.family: Theme.monospaceFontFamily
                    font.pixelSize: Theme.fontSizeMicro
                    renderType: Theme.textRenderType
                }

                VrLineIcon {
                    Layout.preferredWidth: Theme.iconMicro
                    Layout.preferredHeight: Theme.iconMicro
                    kind: "chevronRight"
                    foreground: Theme.palette.mutedText
                    opacity: root.canExpand ? 0.7 : 0
                    rotation: root.detailExpanded ? 90 : 0
                    Behavior on rotation {
                        enabled: !root.reduceMotion
                        NumberAnimation { duration: Theme.fastDuration; easing.type: Easing.OutCubic }
                    }
                }
            }

            HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
            TapHandler {
                onTapped: { if (root.canExpand) root.detailExpanded = !root.detailExpanded }
            }
        }

        Rectangle {
            objectName: "commandBody"
            visible: root.detailExpanded && root.canExpand
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(28)
            Layout.preferredHeight: detailContent.implicitHeight + Theme.scaledGeometry(16)
            radius: Theme.scaledGeometry(6)
            color: root.insetSurface
            clip: true

            ColumnLayout {
                id: detailContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.scaledGeometry(12)
                spacing: Theme.scaledGeometry(8)

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.scaledGeometry(8)
                    visible: root.hasCwd || root.hasExitCode

                    Text {
                        visible: root.hasCwd
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "cwd: " + String(root.modelData.cwd || "")
                        color: Theme.palette.mutedText
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        elide: Text.ElideMiddle
                        renderType: Theme.textRenderType
                    }

                    Text {
                        visible: root.hasExitCode
                        text: "exit: " + root.modelData.exitCode
                        color: Number(root.modelData.exitCode) === 0
                            ? Theme.palette.success : Theme.palette.danger
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        renderType: Theme.textRenderType
                    }
                }

                Rectangle {
                    visible: root.isError && (root.errorDetailsText.length > 0 || root.errorSummaryText.length > 0)
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(errorColumn.implicitHeight + 16, 180)
                    radius: Theme.scaledGeometry(6)
                    color: Qt.rgba(Theme.palette.danger.r, Theme.palette.danger.g,
                                   Theme.palette.danger.b, 0.08)
                    clip: true

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(8)
                        clip: true
                        contentWidth: availableWidth

                        ColumnLayout {
                            id: errorColumn
                            width: parent.width
                            spacing: Theme.scaledGeometry(4)

                            Text {
                                visible: root.errorSummaryText.length > 0
                                Layout.fillWidth: true
                                text: root.errorSummaryText
                                color: Theme.palette.danger
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
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
                                font.pixelSize: Theme.monospaceFontSize(12)
                                background: Item {}
                            }
                        }
                    }
                }

                ScrollView {
                    visible: root.outputText.length > 0
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(outputArea.implicitHeight, 220)
                    clip: true
                    contentWidth: availableWidth

                    TextArea {
                        id: outputArea
                        objectName: "commandOutput"
                        text: root.outputText
                        textFormat: TextEdit.PlainText
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.WrapAnywhere
                        color: Theme.palette.mutedText
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.monospaceFontSize(12)
                        background: Item {}
                    }
                }
            }
        }
    }
}
