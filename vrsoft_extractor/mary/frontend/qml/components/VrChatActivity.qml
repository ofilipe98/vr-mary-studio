import QtQuick
import QtQuick.Controls
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
    property bool expanded: false
    property int recentCount: 5
    property bool logExpanded: false
    readonly property int hiddenCount: Math.max(0, items.length - recentCount)
    signal toggleRequested()

    implicitHeight: content.implicitHeight
    color: "transparent"
    clip: true
    Behavior on implicitHeight {
        enabled: !frontend.reduceMotion && !root.running
        NumberAnimation { duration: Theme.fastDuration }
    }
    Rectangle {
        x: 7; y: 34
        width: 1
        height: Math.max(0, root.implicitHeight - 34)
        visible: root.expanded
        color: Theme.palette.chatDivider
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 4

        Rectangle {
            id: activityHeader
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: root.headerText()
            Accessible.description: root.expanded ? "Recolher atividades" : "Expandir atividades"
            Keys.onReturnPressed: root.toggleRequested()
            Keys.onSpacePressed: root.toggleRequested()
            border.width: activeFocus ? 1 : 0
            border.color: Theme.palette.focus
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            radius: 7
            color: activityHover.hovered ? Theme.palette.hover : "transparent"

            RowLayout {
                anchors.fill: parent
                spacing: 8

                VrLineIcon {
                    Layout.preferredWidth: 14; Layout.preferredHeight: 14
                    kind: root.expanded ? "chevronDown" : "chevronRight"
                    foreground: Theme.palette.mutedText
                }
                Text {
                    text: root.running ? "·" : root.statusText === "Erro" ? "!" : root.statusText === "Interrompido" ? "−" : "✓"
                    color: root.statusText === "Erro" ? Theme.palette.danger : Theme.palette.mutedText
                    font.pixelSize: Theme.captionSize
                }
                Text {
                    Layout.fillWidth: true
                    text: root.headerText()
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    font.weight: root.running ? Font.DemiBold : Font.Normal
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }


            }

            HoverHandler { id: activityHover }
            TapHandler { onTapped: root.toggleRequested() }
        }

        ColumnLayout {
            visible: root.expanded
            Layout.fillWidth: true
            Layout.leftMargin: 7
            spacing: 3

            TextEdit {
                visible: !root.items.some(function(item) { return item.itemType === "reasoning" })
                    && root.reasoningText.trim().length > 0
                Layout.fillWidth: true
                text: root.reasoningText
                textFormat: TextEdit.MarkdownText
                readOnly: true
                activeFocusOnPress: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
            }

            Rectangle {
                visible: root.hiddenCount > 0
                Layout.fillWidth: true
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Mostrar atividades anteriores"
                Keys.onReturnPressed: root.logExpanded = !root.logExpanded
                Keys.onSpacePressed: root.logExpanded = !root.logExpanded
                Layout.preferredHeight: 25
                radius: 7
                color: logToggleHover.hovered ? Theme.palette.hover : "transparent"

                RowLayout {
                    anchors.fill: parent
                    spacing: 6
                    VrLineIcon {
                        Layout.preferredWidth: 11
                        Layout.preferredHeight: 11
                        kind: root.logExpanded ? "chevronDown" : "chevronRight"
                        foreground: Theme.palette.mutedText
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.logExpanded
                            ? "Ocultar atividades anteriores"
                            : "+" + root.hiddenCount + " atividades anteriores"
                        color: Theme.palette.mutedText
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
                        if (item) item.modelData = Qt.binding(function() { return modelData })
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
            color: Theme.palette.text
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
                    activeFocusOnTab: String(actionRoot.modelData.detail || "").length > 0
                    Accessible.role: Accessible.Button
                    Accessible.name: String(actionRoot.modelData.text || "Atividade")
                    Keys.onReturnPressed: actionRoot.detailExpanded = !actionRoot.detailExpanded
                    Keys.onSpacePressed: actionRoot.detailExpanded = !actionRoot.detailExpanded
                    border.width: activeFocus ? 1 : 0
                    border.color: Theme.palette.focus
                    Layout.fillWidth: true
                    Layout.leftMargin: 10
                    Layout.preferredHeight: 27
                    radius: 7
                    color: actionHover.hovered ? Theme.palette.hover : "transparent"

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
                                ? Theme.palette.brandOrange : Theme.palette.mutedText
                        }

                        Text {
                            Layout.fillWidth: true
                            text: String(actionRoot.modelData.text || "Atividade")
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            font.weight: actionRoot.modelData.state === "running"
                                ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }

                        VrLineIcon {
                            visible: String(actionRoot.modelData.detail || "").length > 0
                            Layout.preferredWidth: 11
                            Layout.preferredHeight: 11
                            kind: actionRoot.detailExpanded ? "chevronDown" : "chevronRight"
                            foreground: Theme.palette.mutedText
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
                    color: Theme.palette.surfaceRaised
                    border.width: 1
                    border.color: Theme.palette.chatBorder
                    clip: true

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 9
                        clip: true
                        contentWidth: availableWidth
                        TextArea {
                            id: actionDetail
                            text: String(actionRoot.modelData.detail || "")
                            textFormat: TextEdit.PlainText
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.WrapAnywhere
                            color: Theme.palette.mutedText
                            font.family: "Cascadia Mono"
                            font.pixelSize: Theme.captionSize
                            background: Item { }
                        }
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
        if (root.running) return (root.statusText && root.statusText !== "Pronto" ? root.statusText : "Trabalhando") + " · " + root.elapsedLabel
        if (root.statusText === "Erro") return "Falhou após " + root.elapsedLabel
        if (root.statusText === "Interrompido")
            return "Interrompido após " + root.elapsedLabel
        return "Trabalhou por " + root.elapsedLabel
    }

    function itemIcon(item) {
        if (item.state === "error" || item.state === "failed") return "close"
        if (item.state === "completed" || item.state === "success") return "check"
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
