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
    radius: 18
    color: frontend.palette.surfaceRaised
    border.width: 1
    border.color: frontend.palette.chatBorder

    ColumnLayout {
        id: cardColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        spacing: 9

        RowLayout {
            Layout.fillWidth: true
            spacing: 7

            VrLineIcon {
                Layout.preferredWidth: 12
                Layout.preferredHeight: 12
                kind: root.filesExpanded ? "chevronDown" : "chevronRight"
                foreground: frontend.palette.mutedText
            }

            Text {
                text: root.fileCount + " arquivo"
                    + (root.fileCount === 1 ? " alterado" : "s alterados")
                color: frontend.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
                font.weight: Font.DemiBold
            }

            Text {
                visible: root.additions > 0
                text: "+" + root.additions
                color: frontend.palette.success
                font.family: "Cascadia Mono"
                font.pixelSize: Theme.fontSize(10)
            }

            Text {
                visible: root.deletions > 0
                text: "-" + root.deletions
                color: frontend.palette.danger
                font.family: "Cascadia Mono"
                font.pixelSize: Theme.fontSize(10)
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                objectName: "changedFilesDiffButton"
                visible: root.hasDiff
                Layout.preferredWidth: diffButtonLabel.implicitWidth + 22
                Layout.preferredHeight: 26
                radius: 8
                color: diffHover.hovered
                    ? frontend.palette.hover : frontend.palette.chatControl
                border.width: 1
                border.color: frontend.palette.chatBorder

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 5
                    VrLineIcon {
                        Layout.preferredWidth: 11
                        Layout.preferredHeight: 11
                        kind: "edit"
                        foreground: frontend.palette.mutedText
                    }
                    Text {
                        id: diffButtonLabel
                        text: root.diffExpanded ? "Fechar diff" : "Abrir diff"
                        color: frontend.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(10)
                        font.weight: Font.DemiBold
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
            color: frontend.palette.mutedText
            font.family: "Cascadia Mono"
            font.pixelSize: Theme.fontSize(9)
            elide: Text.ElideRight
        }

        Flow {
            id: fileFlow
            Layout.fillWidth: true
            Layout.preferredHeight: childrenRect.height
            spacing: 6

            Repeater {
                model: root.visibleFiles

                Rectangle {
                    required property var modelData
                    width: Math.min(fileChipText.implicitWidth + 18, fileFlow.width)
                    height: 25
                    radius: 7
                    color: frontend.palette.chatControl

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 7
                        anchors.rightMargin: 7
                        spacing: 5
                        VrLineIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 10
                            height: 10
                            kind: "files"
                            foreground: frontend.palette.mutedText
                        }
                        Text {
                            id: fileChipText
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(implicitWidth, fileFlow.width - 28)
                            text: String(modelData.name || modelData.path || "arquivo")
                            color: frontend.palette.mutedText
                            font.family: "Cascadia Mono"
                            font.pixelSize: Theme.fontSize(9)
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
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(9)

            HoverHandler { id: showFilesHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.filesExpanded = !root.filesExpanded }
        }

        ColumnLayout {
            objectName: "changedFilesDiffBody"
            visible: root.diffExpanded && root.hasDiff
            Layout.fillWidth: true
            spacing: 8

            Repeater {
                model: root.files

                ColumnLayout {
                    required property var modelData
                    visible: String(modelData.diff || "").length > 0
                    Layout.fillWidth: true
                    spacing: 4

                    Text {
                        Layout.fillWidth: true
                        text: String(modelData.path || "")
                        color: frontend.palette.text
                        font.family: "Cascadia Mono"
                        font.pixelSize: Theme.fontSize(9)
                        elide: Text.ElideMiddle
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(diffText.implicitHeight + 16, 320)
                        radius: 8
                        color: frontend.palette.chatBackground
                        border.width: 1
                        border.color: frontend.palette.chatBorder
                        clip: true

                        TextEdit {
                            id: diffText
                            anchors.fill: parent
                            anchors.margins: 8
                            text: String(modelData.diff || "")
                            textFormat: TextEdit.PlainText
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.NoWrap
                            color: frontend.palette.mutedText
                            font.family: "Cascadia Mono"
                            font.pixelSize: Theme.fontSize(9)
                        }
                    }
                }
            }
        }
    }
}
