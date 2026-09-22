import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "toolCard"
    property var modelData: ({})
    property bool detailExpanded: false
    property bool copiedOutput: false
    readonly property string titleText: String(modelData.text || modelData.title || "Atividade")
    readonly property string subtitleText: String(modelData.subtitle || "")
    readonly property string detailText: String(modelData.detail || modelData.output || "")
    readonly property string errorDetailsText: String(modelData.errorDetails || "")
    readonly property string errorSummaryText: String(modelData.errorSummary || "")
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
    implicitHeight: mainColumn.implicitHeight
    Timer { id: copyTimer; interval: 1500; onTriggered: root.copiedOutput = false }

    ColumnLayout {
        id: mainColumn
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.scaledGeometry(4)
        Rectangle {
            id: header
            objectName: "toolHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(28, title.implicitHeight + 8)
            radius: Theme.scaledGeometry(5)
            color: "transparent"
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: root.titleText + (root.isError ? ", falhou" : "")
            Accessible.description: root.detailExpanded ? "Recolher atividade" : "Expandir atividade"
            border.width: activeFocus ? 1 : 0
            border.color: Theme.palette.focus
            Keys.onReturnPressed: root.detailExpanded = !root.detailExpanded
            Keys.onSpacePressed: root.detailExpanded = !root.detailExpanded
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(4)
                anchors.rightMargin: Theme.scaledGeometry(6)
                spacing: Theme.scaledGeometry(7)
                VrLineIcon {
                    Layout.preferredWidth: Theme.iconSmall
                    Layout.preferredHeight: Theme.iconSmall
                    kind: root.isError ? "close" : (root.isWaitingApproval ? "lock" : "hammer")
                    foreground: root.isError ? Theme.palette.danger : (root.isWaitingApproval ? Theme.palette.warning : Theme.palette.mutedText)
                    opacity: root.isError ? 0.65 : 1
                }
                VrShimmerText {
                    id: title
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: root.titleText
                    running: root.isRunning
                    color: root.isRunning ? Theme.palette.text : Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    elide: Text.ElideRight
                    renderType: Theme.textRenderType
                }
                Text {
                    visible: root.detailExpanded && String(root.modelData.durationLabel || "").length > 0
                    text: String(root.modelData.durationLabel || "")
                    font.pixelSize: Theme.fontSize(12)
                    color: Theme.palette.mutedText
                }
                VrLineIcon {
                    Layout.preferredWidth: Theme.iconMicro
                    Layout.preferredHeight: Theme.iconMicro
                    kind: root.detailExpanded ? "chevronDown" : "chevronRight"
                    foreground: Theme.palette.mutedText
                }
            }
            HoverHandler { cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.detailExpanded = !root.detailExpanded }
        }
        Rectangle {
            visible: root.detailExpanded
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(26)
            Layout.preferredHeight: body.implicitHeight + 20
            radius: Theme.scaledGeometry(6)
            color: Theme.palette.chatBackground
            border.width: 1
            border.color: Theme.palette.chatBorder
            ColumnLayout {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.scaledGeometry(10)
                spacing: Theme.scaledGeometry(8)
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: root.isError ? "Falha na ferramenta" : (root.isWaitingApproval ? "Aguardando aprovação" : "Detalhes")
                        color: Theme.palette.mutedText
                        font.pixelSize: Theme.fontSize(12)
                        elide: Text.ElideRight
                    }
                    Button {
                        id: copyButton
                        text: root.copiedOutput ? "Copiado" : "Copiar"
                        implicitHeight: copyLabel.implicitHeight + 8
                        implicitWidth: copyLabel.implicitWidth + 16
                        contentItem: Text {
                            id: copyLabel
                            text: copyButton.text
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: Theme.scaledGeometry(4)
                            color: copyButton.hovered ? Theme.palette.hover : "transparent"
                            border.width: copyButton.activeFocus ? 1 : 0
                            border.color: Theme.palette.focus
                        }
                        Accessible.name: "Copiar detalhes da ferramenta"
                        onClicked: {
                            if (typeof studio !== "undefined" && studio) studio.copyText(root.expandedText)
                            root.copiedOutput = true
                            copyTimer.restart()
                        }
                    }
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(details.implicitHeight, 280)
                    contentWidth: availableWidth
                    clip: true
                    TextArea {
                        id: details
                        objectName: "toolDetails"
                        text: root.expandedText
                        textFormat: TextEdit.PlainText
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.WrapAnywhere
                        color: Theme.palette.text
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.fontSize(12)
                        background: Item {}
                    }
                }
            }
        }
    }
}
