import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    objectName: "chatActivity"

    property var items: []
    property string reasoningText: ""
    property string statusText: "Pronto"
    property string elapsedLabel: "0s"
    property bool running: false
    property bool expanded: true
    property int recentCount: 12
    property bool logExpanded: false
    readonly property int hiddenCount: Math.max(0, items.length - recentCount)
    signal toggleRequested()

    implicitHeight: content.implicitHeight
    color: "transparent"

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 10

        Rectangle {
            id: activityHeader
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            radius: 7
            color: activityHover.hovered ? frontend.palette.hover : "transparent"

            RowLayout {
                anchors.fill: parent
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: root.headerText()
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(11)
                    font.weight: root.running ? Font.DemiBold : Font.Normal
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }

                VrLineIcon {
                    Layout.preferredWidth: 12
                    Layout.preferredHeight: 12
                    kind: root.expanded ? "chevronDown" : "chevronUp"
                    foreground: frontend.palette.mutedText
                }
            }

            HoverHandler { id: activityHover }
            TapHandler { onTapped: root.toggleRequested() }
        }

        Rectangle {
            visible: root.expanded
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: frontend.palette.chatDivider
            opacity: 0.55
        }

        ColumnLayout {
            visible: root.expanded
            Layout.fillWidth: true
            spacing: 14

            TextEdit {
                visible: root.items.length === 0
                    && root.reasoningText.trim().length > 0
                Layout.fillWidth: true
                text: root.reasoningText
                textFormat: TextEdit.MarkdownText
                readOnly: true
                activeFocusOnPress: false
                wrapMode: TextEdit.Wrap
                color: frontend.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
            }

            Rectangle {
                visible: root.hiddenCount > 0
                Layout.fillWidth: true
                Layout.preferredHeight: 25
                radius: 7
                color: logToggleHover.hovered ? frontend.palette.hover : "transparent"

                RowLayout {
                    anchors.fill: parent
                    spacing: 6
                    VrLineIcon {
                        Layout.preferredWidth: 11
                        Layout.preferredHeight: 11
                        kind: root.logExpanded ? "chevronDown" : "chevronRight"
                        foreground: frontend.palette.mutedText
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.logExpanded
                            ? "Ocultar atividades anteriores"
                            : "+" + root.hiddenCount + " atividades anteriores"
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(10)
                    }
                }

                HoverHandler { id: logToggleHover }
                TapHandler { onTapped: root.logExpanded = !root.logExpanded }
            }

            Repeater {
                model: root.visibleItems()

                Loader {
                    required property var modelData
                    Layout.fillWidth: true
                    sourceComponent: String(modelData.kind || "") === "commentary"
                        ? commentaryComponent
                        : String(modelData.kind || "") === "file_changes"
                            ? changedFilesComponent : actionComponent
                    onLoaded: {
                        if (item) item.modelData = modelData
                    }
                }
            }
        }
    }

    Component {
        id: commentaryComponent

        TextEdit {
            id: commentaryText
            property var modelData: ({})
            text: String(modelData.text || "")
            textFormat: TextEdit.MarkdownText
            readOnly: true
            activeFocusOnPress: false
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
            font.weight: Font.Normal
            onLinkActivated: link => {
                if (studio) studio.openExternalUrl(link)
            }
            onTextChanged: frontend.styleMessageDocument(
                textDocument,
                String(modelData.text || "")
            )
            Connections {
                target: frontend
                function onThemeChanged() {
                    frontend.styleMessageDocument(
                        commentaryText.textDocument,
                        String(commentaryText.modelData.text || "")
                    )
                }
                function onTypographyChanged() {
                    frontend.styleMessageDocument(
                        commentaryText.textDocument,
                        String(commentaryText.modelData.text || "")
                    )
                }
            }
        }
    }

    Component {
        id: actionComponent

        Item {
            id: actionRoot
            property var modelData: ({})
            property bool detailExpanded: false
            implicitHeight: actionColumn.implicitHeight

            ColumnLayout {
                id: actionColumn
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 6

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 27
                    radius: 7
                    color: actionHover.hovered ? frontend.palette.hover : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 2
                        anchors.rightMargin: 2
                        spacing: 8

                        VrLineIcon {
                            Layout.preferredWidth: 13
                            Layout.preferredHeight: 13
                            kind: root.itemIcon(actionRoot.modelData)
                            foreground: actionRoot.modelData.state === "running"
                                ? frontend.palette.brandOrange : frontend.palette.mutedText
                        }

                        Text {
                            Layout.fillWidth: true
                            text: String(actionRoot.modelData.text || "Atividade")
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(11)
                            font.weight: actionRoot.modelData.state === "running"
                                ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }

                        VrLineIcon {
                            visible: String(actionRoot.modelData.detail || "").length > 0
                            Layout.preferredWidth: 11
                            Layout.preferredHeight: 11
                            kind: actionRoot.detailExpanded ? "chevronDown" : "chevronRight"
                            foreground: frontend.palette.mutedText
                        }
                    }

                    HoverHandler { id: actionHover }
                    TapHandler {
                        enabled: String(actionRoot.modelData.detail || "").length > 0
                        onTapped: actionRoot.detailExpanded = !actionRoot.detailExpanded
                    }
                }

                Rectangle {
                    visible: actionRoot.detailExpanded
                        && String(actionRoot.modelData.detail || "").length > 0
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(actionDetail.implicitHeight + 18, 260)
                    radius: 8
                    color: frontend.palette.surfaceRaised
                    border.width: 1
                    border.color: frontend.palette.chatBorder
                    clip: true

                    TextEdit {
                        id: actionDetail
                        anchors.fill: parent
                        anchors.margins: 9
                        text: String(actionRoot.modelData.detail || "")
                        textFormat: TextEdit.PlainText
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.WrapAnywhere
                        color: frontend.palette.mutedText
                        font.family: "Cascadia Mono"
                        font.pixelSize: Theme.fontSize(9)
                    }
                }
            }
        }
    }

    Component {
        id: changedFilesComponent

        VrChangedFilesCard {
            property var modelData: ({})
            files: modelData.files || []
            fileCount: Number(modelData.fileCount || 0)
            additions: Number(modelData.additions || 0)
            deletions: Number(modelData.deletions || 0)
            folderSummary: String(modelData.folderSummary || "")
            hasDiff: Boolean(modelData.hasDiff)
        }
    }

    function headerText() {
        if (root.running) return "Trabalhando há " + root.elapsedLabel
        if (root.statusText === "Erro") return "Falhou após " + root.elapsedLabel
        if (root.statusText === "Interrompido")
            return "Interrompido após " + root.elapsedLabel
        return "Trabalhou por " + root.elapsedLabel
    }

    function itemIcon(item) {
        var itemType = String(item.itemType || "")
        if (itemType === "commandExecution") return "terminal"
        if (itemType === "webSearch" || itemType === "web_search") return "search"
        if (itemType === "fileChange") return "edit"
        if (String(item.kind || "") === "status") return "task"
        return "auto"
    }

    function visibleItems() {
        if (root.logExpanded || root.items.length <= root.recentCount)
            return root.items
        return root.items.slice(root.items.length - root.recentCount)
    }
}
