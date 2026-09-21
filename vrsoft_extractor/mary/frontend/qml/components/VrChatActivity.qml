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
    readonly property string headerLabel: root.headerText()
    signal toggleRequested()

    implicitHeight: content.implicitHeight
    color: "transparent"
    clip: true
    Behavior on implicitHeight {
        enabled: !(typeof frontend !== "undefined" && frontend.reduceMotion) && !root.running
        NumberAnimation { duration: Theme.fastDuration }
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.scaledGeometry(4)

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
            Layout.preferredHeight: Theme.scaledGeometry(30)
            radius: Theme.scaledGeometry(7)
            color: "transparent"

            RowLayout {
                anchors.fill: parent
                spacing: Theme.scaledGeometry(6)

                VrLineIcon {
                    Layout.preferredWidth: Theme.scaledGeometry(16)
                    Layout.preferredHeight: Theme.scaledGeometry(16)
                    kind: root.headerIcon()
                    foreground: Theme.palette.mutedText
                }

                VrShimmerText {
                    Layout.fillWidth: true
                    text: root.headerText()
                    running: root.running
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.Normal
                    horizontalAlignment: Text.AlignLeft
                    elide: Text.ElideRight
                }
                VrLineIcon {
                    Layout.preferredWidth: Theme.iconSmall
                    Layout.preferredHeight: Theme.iconSmall
                    kind: root.expanded ? "chevronDown" : "chevronRight"
                    foreground: Theme.palette.mutedText
                }
            }

            HoverHandler { cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.toggleRequested() }
        }

        // Horizontal hairline separator below header
        Rectangle {
            visible: (root.expanded || root.visibleItems().length > 0) && root.items && root.items.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.palette.chatBorder
            opacity: 0.6
        }

        ColumnLayout {
            visible: root.expanded || root.visibleItems().length > 0
            Layout.fillWidth: true
            Layout.leftMargin: 0
            spacing: Theme.scaledGeometry(3)

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
                    id: activityItemLoader
                    required property var modelData
                    Layout.fillWidth: true
                    sourceComponent: {
                        var k = String(modelData.kind || "")
                        var t = String(modelData.itemType || "")
                        if (k === "commentary") return commentaryComponent
                        if (k === "file_changes" || t === "fileChange") return changedFilesComponent
                        if (k === "action_group" || (modelData.items && modelData.items.length > 0)) return toolGroupComponent
                        if (t === "commandExecution" || k === "command") return commandCardComponent
                        return toolCardComponent
                    }
                    onLoaded: {
                        if (item) item.modelData = activityItemLoader.modelData
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
            readonly property string displayText: (typeof frontend !== "undefined" && frontend)
                ? frontend.displayMarkdown(String(modelData.text || ""))
                : String(modelData.text || "")
            text: displayText
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
                var value = String(link)
                if (value.indexOf("vr-file:") === 0 || value.indexOf("file:") === 0) {
                    if (typeof chat !== "undefined" && chat) chat.openFileReference(value)
                } else if (typeof studio !== "undefined" && studio) {
                    studio.openExternalUrl(value)
                }
            }
            onTextChanged: frontend.styleMessageDocument(
                textDocument,
                displayText
            )
            Connections {
                target: frontend
                function onThemeChanged() {
                    frontend.styleMessageDocument(
                        commentaryText.textDocument,
                        commentaryText.displayText
                    )
                }
                function onTypographyChanged() {
                    frontend.styleMessageDocument(
                        commentaryText.textDocument,
                        commentaryText.displayText
                    )
                }
            }
        }
    }

    Component {
        id: commandCardComponent

        VrCommandCard {}
    }

    Component {
        id: toolCardComponent

        VrToolCard {}
    }

    Component {
        id: toolGroupComponent

        VrToolGroupCard {}
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
            var base = "Trabalhando há " + root.elapsedLabel
            if (root.taskStep.length > 0)
                return base + " · " + root.taskStep
            return base
        }
        if (root.statusText === "Erro") return "Falhou após " + root.elapsedLabel
        if (root.statusText === "Interrompido")
            return "Interrompido após " + root.elapsedLabel
        return "Concluído em " + root.elapsedLabel
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

    function headerIcon() {
        var list = root.items || []
        for (var index = list.length - 1; index >= 0; --index) {
            var state = String(list[index].state || "")
            if (state === "running" || state === "waiting_approval")
                return root.itemIcon(list[index])
        }
        if (list.length > 0)
            return root.itemIcon(list[list.length - 1])
        return "terminalPrompt"
    }

    function visibleItems() {
        if (root.expanded)
            return root.items || []
        if (!root.items || root.items.length === 0)
            return []

        // The live trace stays complete even while the disclosure is collapsed.
        if (root.running)
            return root.items

        // A settled failure remains available as a compact diagnostic summary.
        var failedItems = root.items.filter(function(i) {
            return i.state === "error" || i.state === "failed"
        })
        if (failedItems.length > 0) return failedItems.slice(-1)

        // Successful settled work is disclosed by the Concluído em ... header.
        return []
    }
}
