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
    property string taskStep: ""
    property bool running: false
    property bool expanded: false
    property int recentCount: 5
    property bool logExpanded: false
    readonly property int hiddenCount: Math.max(0, items.length - recentCount)
    readonly property string headerLabel: root.headerText()
    signal toggleRequested()

    implicitHeight: content.implicitHeight
    color: "transparent"
    clip: true
    Behavior on implicitHeight {
        enabled: !frontend.reduceMotion && !root.running
        NumberAnimation { duration: Theme.fastDuration }
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
                spacing: 6

                Text {
                    Layout.fillWidth: true
                    text: root.headerText()
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.Normal
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }
            }

            HoverHandler { id: activityHover }
            TapHandler { onTapped: root.toggleRequested() }
        }

        // Horizontal hairline separator below header
        Rectangle {
            visible: (root.expanded || root.running) && root.items && root.items.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.palette.chatBorder
            opacity: 0.6
        }

        ColumnLayout {
            visible: root.expanded || (root.running && root.items && root.items.length > 0)
            Layout.fillWidth: true
            Layout.leftMargin: 0
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

            Repeater {
                model: root.visibleItems()

                Loader {
                    required property var modelData
                    Layout.fillWidth: true
                    sourceComponent: {
                        var k = String(modelData.kind || "")
                        var t = String(modelData.itemType || "")
                        if (k === "commentary") return commentaryComponent
                        if (k === "file_changes" || t === "fileChange") return changedFilesComponent
                        if (t === "commandExecution" || k === "command") return commandCardComponent
                        return toolCardComponent
                    }
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
                if (typeof studio !== "undefined" && studio) studio.openExternalUrl(link)
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
        id: commandCardComponent

        VrCommandCard {
            property var modelData: ({})
        }
    }

    Component {
        id: toolCardComponent

        VrToolCard {
            property var modelData: ({})
        }
    }

    Component {
        id: changedFilesComponent

        VrChangedFilesCard {
            property var modelData: ({})
            files: modelData.files || []
            fileCount: Number(modelData.fileCount || (modelData.files ? modelData.files.length : 0))
            additions: Number(modelData.additions || 0)
            deletions: Number(modelData.deletions || 0)
            folderSummary: String(modelData.folderSummary || "")
            hasDiff: Boolean(modelData.hasDiff)
        }
    }

    function headerText() {
        if (root.running) {
            var base = "Working for " + root.elapsedLabel
            if (root.taskStep.length > 0)
                return base + " · " + root.taskStep
            return base
        }
        if (root.statusText === "Erro") return "Falhou após " + root.elapsedLabel
        if (root.statusText === "Interrompido")
            return "Interrompido após " + root.elapsedLabel
        return "Worked for " + root.elapsedLabel
    }

    function itemIcon(item) {
        if (item.state === "error" || item.state === "failed") return "close"
        var itemType = String(item.itemType || "")
        var text = String(item.text || "").toLowerCase()
        if (itemType === "commandExecution" || text.indexOf("command") >= 0 || text.indexOf("terminal") >= 0 || text.indexOf("git ") >= 0 || text.indexOf("running git") >= 0 || text.indexOf("running ") === 0) {
            return "terminalPrompt"
        }
        return "hammer"
    }

    function visibleItems() {
        if (root.expanded || root.logExpanded)
            return root.items
        if (root.running) {
            var runningItems = root.items.filter(function(i) { return i.state === "running" })
            if (runningItems.length > 0) return runningItems
            return root.items.slice(-1)
        }
        return root.items.slice(-1)
    }
}
