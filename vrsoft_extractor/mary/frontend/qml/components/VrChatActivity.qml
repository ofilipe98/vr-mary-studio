import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../theme/ToolIcons.js" as ToolIcons

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
    // Identity of the rendered activity (messageKey). Delegate reuse across
    // messages must not leak expanded rows into another conversation row.
    property string scopeKey: ""
    // Row disclosure state keyed by item id, owned by the activity instead of
    // the transient Repeater delegates so streamed activityData updates that
    // rebuild every row never silently collapse an expanded row.
    property var disclosureIds: ({})
    readonly property string headerLabel: root.headerText()
    readonly property bool reduceMotion: typeof frontend !== "undefined" && frontend !== null
        ? frontend.reduceMotion : false
    signal toggleRequested()
    signal disclosureToggled(bool expanded)

    onScopeKeyChanged: root.resetDisclosure()

    implicitHeight: content.implicitHeight
    color: "transparent"
    clip: true
    Behavior on implicitHeight {
        enabled: !root.reduceMotion && !root.running
        NumberAnimation { duration: Theme.fastDuration }
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.scaledGeometry(4)

        Rectangle {
            id: activityHeader
            objectName: "activityHeader"
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: root.headerText()
            Accessible.description: root.expanded ? "Recolher atividades" : "Expandir atividades"
            Keys.onReturnPressed: root.toggleRequested()
            Keys.onSpacePressed: root.toggleRequested()
            border.width: activeFocus ? 1 : 0
            border.color: Theme.palette.focus
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(28)
            radius: Theme.scaledGeometry(6)
            color: "transparent"

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
                        kind: root.headerIcon()
                        opacity: 0.9
                        foreground: Theme.palette.mutedText
                    }
                }

                VrShimmerText {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
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
                    Layout.preferredWidth: Theme.iconMicro
                    Layout.preferredHeight: Theme.iconMicro
                    kind: "chevronRight"
                    foreground: Theme.palette.mutedText
                    opacity: 0.7
                    rotation: root.expanded ? 90 : 0
                    Behavior on rotation {
                        enabled: !root.reduceMotion
                        NumberAnimation { duration: Theme.fastDuration; easing.type: Easing.OutCubic }
                    }
                }
            }

            HoverHandler { id: headerHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.toggleRequested() }
        }

        Rectangle {
            objectName: "activityHeaderDivider"
            visible: (root.expanded || root.visibleItems().length > 0)
                && root.items && root.items.length > 0
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
                    readonly property string disclosureKey: root.disclosureKeyFor(activityItemLoader.modelData)
                    // Mirrors the commentary branch of sourceComponent: only
                    // cards expose disclosureHost/disclosureExpanded.
                    readonly property bool supportsDisclosure: String(activityItemLoader.modelData.kind || "") !== "commentary"
                    sourceComponent: {
                        var k = String(modelData.kind || "")
                        var t = String(modelData.itemType || "")
                        if (k === "commentary") return commentaryComponent
                        if (k === "file_changes" || t === "fileChange") return changedFilesComponent
                        if (k === "action_group" || (modelData.items && modelData.items.length > 0)) return toolGroupComponent
                        if (t === "commandExecution" || k === "command") return commandCardComponent
                        return toolCardComponent
                    }
                    onModelDataChanged: root.restoreDisclosure(activityItemLoader)
                    onDisclosureKeyChanged: root.restoreDisclosure(activityItemLoader)
                    onLoaded: {
                        if (item && activityItemLoader.supportsDisclosure)
                            item.disclosureHost = root
                        root.restoreDisclosure(activityItemLoader)
                    }
                    // A real binding (not an onLoaded assignment) so a reused
                    // delegate always renders the current event data.
                    Binding {
                        target: activityItemLoader.item
                        property: "modelData"
                        value: activityItemLoader.modelData
                        when: activityItemLoader.item !== null
                        restoreMode: Binding.RestoreNone
                    }
                    Connections {
                        target: activityItemLoader.item
                        function onDisclosureToggled(expanded) {
                            if (activityItemLoader.disclosureKey === "")
                                return
                            root.setDisclosureExpanded(activityItemLoader.disclosureKey, expanded)
                            root.disclosureToggled(expanded)
                        }
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
                } else if (value.indexOf("vr-code:") === 0) {
                    if (typeof chat !== "undefined" && chat) chat.openDecompiledReference(value)
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
        return ToolIcons.kindFor(item)
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

    function disclosureKeyFor(item) {
        if (!item)
            return ""
        var id = item.id
        if (id === undefined || id === null)
            return ""
        var key = String(id)
        return key.length > 0 ? key : ""
    }

    function isDisclosureExpanded(key) {
        return key !== "" && root.disclosureIds[key] === true
    }

    function setDisclosureExpanded(key, expanded) {
        if (key === "")
            return
        var next = {}
        for (var current in root.disclosureIds)
            next[current] = root.disclosureIds[current]
        if (expanded) next[key] = true
        else delete next[key]
        root.disclosureIds = next
    }

    function resetDisclosure() {
        root.disclosureIds = ({})
    }

    function restoreDisclosure(loader) {
        if (!loader || !loader.item || !loader.supportsDisclosure)
            return
        loader.item.disclosureExpanded = root.isDisclosureExpanded(loader.disclosureKey)
    }
}
