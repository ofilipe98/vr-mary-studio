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

        // Horizontal hairline separator below header (target: T3 Code)
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
            spacing: 2

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
                spacing: 4

                Rectangle {
                    activeFocusOnTab: String(actionRoot.modelData.detail || "").length > 0
                    Accessible.role: Accessible.Button
                    Accessible.name: String(actionRoot.modelData.text || "Atividade")
                    Keys.onReturnPressed: actionRoot.detailExpanded = !actionRoot.detailExpanded
                    Keys.onSpacePressed: actionRoot.detailExpanded = !actionRoot.detailExpanded
                    border.width: activeFocus ? 1 : 0
                    border.color: Theme.palette.focus
                    Layout.fillWidth: true
                    Layout.leftMargin: 0
                    Layout.preferredHeight: 25
                    radius: 4
                    color: actionHover.hovered ? Theme.palette.hover : "transparent"
                    clip: true

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 2
                        anchors.rightMargin: 4
                        spacing: 8

                        VrLineIcon {
                            Layout.preferredWidth: 14
                            Layout.preferredHeight: 14
                            kind: root.itemIcon(actionRoot.modelData)
                            foreground: actionRoot.modelData.state === "running"
                                ? Theme.palette.text : Theme.palette.mutedText
                        }

                        Text {
                            Layout.fillWidth: true
                            text: String(actionRoot.modelData.text || "Atividade")
                            color: actionRoot.modelData.state === "running"
                                ? Theme.palette.text : Theme.palette.mutedText
                            font.family: Theme.monospaceFontFamily
                            font.pixelSize: Theme.fontSize(12)
                            font.weight: actionRoot.modelData.state === "running"
                                ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }

                        VrLineIcon {
                            Layout.preferredWidth: 9
                            Layout.preferredHeight: 9
                            kind: actionRoot.detailExpanded ? "chevronDown" : "chevronRight"
                            foreground: Theme.palette.mutedText
                        }
                    }

                    // Specular highlight shimmer animation on running tool call (target: T3 Code)
                    Rectangle {
                        id: specularShimmer
                        anchors.fill: parent
                        radius: parent.radius
                        clip: true
                        color: "transparent"
                        visible: actionRoot.modelData.state === "running"

                        Rectangle {
                            id: shimmerBeam
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: Math.max(120, parent.width * 0.4)
                            x: -width
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: "transparent" }
                                GradientStop { position: 0.35; color: Qt.rgba(255, 255, 255, 0.0) }
                                GradientStop { position: 0.5; color: Qt.rgba(255, 255, 255, 0.28) }
                                GradientStop { position: 0.65; color: Qt.rgba(255, 255, 255, 0.0) }
                                GradientStop { position: 1.0; color: "transparent" }
                            }
                            NumberAnimation on x {
                                running: actionRoot.modelData.state === "running"
                                from: -shimmerBeam.width
                                to: specularShimmer.width + shimmerBeam.width
                                duration: 1500
                                loops: Animation.Infinite
                                easing.type: Easing.Linear
                            }
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
                    radius: 6
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
                            font.family: Theme.monospaceFontFamily
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
        if (root.running) {
            var base = "Working for " + root.elapsedLabel
            if (root.taskStep.length > 0)
                return base + " · " + root.taskStep
            return base
        }
        if (root.statusText === "Erro") return "Falhou após " + root.elapsedLabel
        if (root.statusText === "Interrompido")
            return "Interrompido após " + root.elapsedLabel
        // Completed turns keep the last status; the drawer holds the full plan.
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
