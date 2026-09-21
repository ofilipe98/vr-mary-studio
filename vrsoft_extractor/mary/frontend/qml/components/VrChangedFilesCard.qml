import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    objectName: "changedFilesCard"

    property var files: []
    property int fileCount: 0
    property int additions: 0
    property int deletions: 0
    property string folderSummary: ""
    property bool hasDiff: false
    property bool filesExpanded: false
    property bool diffExpanded: false

    readonly property var visibleFiles: filesExpanded
        ? files : files.slice(0, Math.min(4, files.length))

    implicitHeight: cardColumn.implicitHeight + 24
    radius: Theme.radiusCard
    color: Theme.palette.surfaceRaised
    border.width: 1
    border.color: Theme.palette.chatBorder

    ColumnLayout {
        id: cardColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.scaledGeometry(12)
        spacing: Theme.scaledGeometry(9)

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.scaledGeometry(7)

            VrLineIcon {
                Layout.preferredWidth: Theme.scaledGeometry(12)
                Layout.preferredHeight: Theme.scaledGeometry(12)
                kind: root.filesExpanded ? "chevronDown" : "chevronRight"
                foreground: Theme.palette.mutedText
            }

            Text {
                text: root.fileCount + " arquivo"
                    + (root.fileCount === 1 ? " alterado" : "s alterados")
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeCompact
                font.weight: Theme.weightMedium
                renderType: Theme.textRenderType
            }

            Text {
                visible: root.additions > 0
                text: "+" + root.additions
                color: Theme.palette.success
                font.family: Theme.monospaceFontFamily || "Cascadia Mono"
                font.pixelSize: Theme.fontSizeCaption
                renderType: Theme.textRenderType
            }

            Text {
                visible: root.deletions > 0
                text: "-" + root.deletions
                color: Theme.palette.danger
                font.family: Theme.monospaceFontFamily || "Cascadia Mono"
                font.pixelSize: Theme.fontSizeCaption
                renderType: Theme.textRenderType
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                objectName: "changedFilesDiffButton"
                visible: root.hasDiff
                Layout.preferredWidth: diffButtonLabel.implicitWidth + 24
                Layout.preferredHeight: Theme.scaledGeometry(28)
                radius: Theme.radiusSmall
                color: diffHover.hovered
                    ? Theme.palette.hover : Theme.palette.chatControl
                border.width: 1
                border.color: Theme.palette.chatBorder

                RowLayout {
                    anchors.centerIn: parent
                    spacing: Theme.scaledGeometry(5)
                    VrLineIcon {
                        Layout.preferredWidth: Theme.scaledGeometry(12)
                        Layout.preferredHeight: Theme.scaledGeometry(12)
                        kind: "edit"
                        foreground: Theme.palette.mutedText
                    }
                    Text {
                        id: diffButtonLabel
                        text: root.diffExpanded ? "Fechar diff" : "Abrir diff"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeCaption
                        font.weight: Theme.weightMedium
                        renderType: Theme.textRenderType
                    }
                }

                HoverHandler { id: diffHover }
                TapHandler { onTapped: root.diffExpanded = !root.diffExpanded }
            }

            TapHandler {
                onTapped: root.filesExpanded = !root.filesExpanded
            }
        }

        Text {
            visible: root.folderSummary.length > 0
            Layout.fillWidth: true
            text: root.folderSummary
            color: Theme.palette.mutedText
            font.family: Theme.monospaceFontFamily || "Cascadia Mono"
            font.pixelSize: Theme.fontSizeMicro
            renderType: Theme.textRenderType
            elide: Text.ElideRight
        }

        Flow {
            id: fileFlow
            Layout.fillWidth: true
            Layout.preferredHeight: childrenRect.height
            spacing: Theme.scaledGeometry(6)

            Repeater {
                model: root.visibleFiles

                Rectangle {
                    required property var modelData
                    width: Math.min(fileChipText.implicitWidth + 20, fileFlow.width)
                    height: Theme.scaledGeometry(26)
                    radius: Theme.radiusSmall
                    color: Theme.palette.chatControl

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.scaledGeometry(8)
                        anchors.rightMargin: Theme.scaledGeometry(8)
                        spacing: Theme.scaledGeometry(6)
                        VrLineIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            width: Theme.scaledGeometry(12)
                            height: Theme.scaledGeometry(12)
                            kind: "files"
                            foreground: Theme.palette.mutedText
                        }
                        Text {
                            id: fileChipText
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(implicitWidth, fileFlow.width - 32)
                            text: String(modelData.name || modelData.path || "arquivo")
                            color: Theme.palette.mutedText
                            font.family: Theme.monospaceFontFamily || "Cascadia Mono"
                            font.pixelSize: Theme.fontSizeMicro
                            renderType: Theme.textRenderType
                            elide: Text.ElideMiddle
                        }
                    }
                }
            }
        }

        Text {
            visible: root.files.length > 4
            text: root.filesExpanded
                ? "Mostrar menos" : "Mostrar todos os " + root.files.length + " arquivos"
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeCaption
            renderType: Theme.textRenderType

            HoverHandler { id: showFilesHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.filesExpanded = !root.filesExpanded }
        }

        ColumnLayout {
            objectName: "changedFilesDiffBody"
            visible: root.diffExpanded && root.hasDiff
            Layout.fillWidth: true
            spacing: Theme.scaledGeometry(8)

            Repeater {
                model: root.files

                ColumnLayout {
                    required property var modelData
                    visible: String(modelData.diff || "").length > 0
                    Layout.fillWidth: true
                    spacing: Theme.scaledGeometry(4)

                    Text {
                        Layout.fillWidth: true
                        text: String(modelData.path || "")
                        color: Theme.palette.text
                        font.family: Theme.monospaceFontFamily || "Cascadia Mono"
                        font.pixelSize: Theme.fontSizeCaption
                        renderType: Theme.textRenderType
                        elide: Text.ElideMiddle
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(diffText.implicitHeight + 16, 320)
                        radius: Theme.radiusSmall
                        color: Theme.palette.chatBackground
                        border.width: 1
                        border.color: Theme.palette.chatBorder
                        clip: true

                        TextEdit {
                            id: diffText
                            anchors.fill: parent
                            anchors.margins: Theme.scaledGeometry(8)
                            text: String(modelData.diff || "")
                            textFormat: TextEdit.PlainText
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.NoWrap
                            color: Theme.palette.mutedText
                            font.family: Theme.monospaceFontFamily || "Cascadia Mono"
                            font.pixelSize: Theme.monospaceFontSize(12)
                            renderType: Theme.textRenderType
                        }
                    }
                }
            }
        }
    }
}
