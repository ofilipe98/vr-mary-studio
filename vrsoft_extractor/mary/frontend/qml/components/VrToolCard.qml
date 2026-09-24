import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../theme/ToolIcons.js" as ToolIcons

// One tool call rendered as a T3 Code activity row: quiet icon + label,
// optional duration at the trailing edge and a chevron that rotates open.
// The expanded body is a muted inset with the raw command/arguments/output;
// copying stays available through native text selection.
Item {
    id: root
    objectName: "toolCard"
    property var modelData: ({})
    property bool detailExpanded: false
    readonly property string titleText: String(modelData.text || modelData.title || "Atividade")
    readonly property string subtitleText: String(modelData.subtitle || "")
    readonly property string detailText: String(modelData.detail || modelData.output || "")
    readonly property string errorDetailsText: String(modelData.errorDetails || "")
    readonly property string errorSummaryText: String(modelData.errorSummary || "")
    readonly property string durationLabel: String(modelData.durationLabel || "")
    readonly property string stateValue: String(modelData.state || "running")
    readonly property bool isRunning: stateValue === "running"
    readonly property bool isError: stateValue === "error" || stateValue === "failed"
    readonly property bool isSuccess: stateValue === "completed" || stateValue === "success"
    readonly property bool isWaitingApproval: stateValue === "waiting_approval"
    readonly property string expandedText: {
        var blocks = []
        var values = [root.errorSummaryText, root.errorDetailsText, root.detailText]
        for (var i = 0; i < values.length; ++i) {
            var value = values[i].trim()
            if (value.length && blocks.indexOf(value) < 0) blocks.push(value)
        }
        return blocks.join("\n\n")
    }
    readonly property string bodyText: {
        var blocks = []
        var summary = root.errorSummaryText.trim()
        var values = [root.errorDetailsText, root.detailText]
        for (var i = 0; i < values.length; ++i) {
            var value = values[i].trim()
            if (value.length && value !== summary && blocks.indexOf(value) < 0)
                blocks.push(value)
        }
        return blocks.join("\n\n")
    }
    readonly property bool canExpand: root.expandedText.length > 0
    readonly property bool reduceMotion: typeof frontend !== "undefined" && frontend !== null
        ? frontend.reduceMotion : false
    // T3 keeps tool details on a quiet muted inset (bg-muted/40).
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
            objectName: "toolHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(28)
            radius: Theme.scaledGeometry(6)
            color: hover.hovered ? Theme.palette.hover : "transparent"
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: root.titleText + (root.isError ? ", falhou" : "")
            Accessible.description: root.detailExpanded ? "Recolher atividade" : "Expandir atividade"
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
                        kind: ToolIcons.kindFor(root.modelData)
                        opacity: root.isError ? 0.75 : 0.9
                        foreground: root.isError
                            ? Theme.palette.danger
                            : (root.isWaitingApproval ? Theme.palette.warning : Theme.palette.mutedText)
                    }
                }
                VrShimmerText {
                    id: title
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: root.titleText
                    running: root.isRunning
                    color: root.isError
                        ? Theme.palette.danger
                        : (root.isRunning ? Theme.palette.text : Theme.palette.mutedText)
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
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
            objectName: "toolBody"
            visible: root.detailExpanded && root.canExpand
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(28)
            Layout.preferredHeight: bodyColumn.implicitHeight + Theme.scaledGeometry(16)
            radius: Theme.scaledGeometry(6)
            color: root.insetSurface
            clip: true

            ColumnLayout {
                id: bodyColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.scaledGeometry(12)
                spacing: Theme.scaledGeometry(6)

                Text {
                    visible: root.isError && root.errorSummaryText.length > 0
                    Layout.fillWidth: true
                    text: root.errorSummaryText
                    color: Theme.palette.danger
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: Font.DemiBold
                    wrapMode: Text.Wrap
                    renderType: Theme.textRenderType
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(details.implicitHeight, Theme.scaledGeometry(256))
                    visible: root.bodyText.length > 0
                    contentWidth: availableWidth
                    clip: true
                    TextArea {
                        id: details
                        objectName: "toolDetails"
                        text: root.bodyText
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
