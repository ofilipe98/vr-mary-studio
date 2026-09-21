import QtQuick
import QtQuick.Controls
import "../theme"

Column {
    id: root
    objectName: "tableBlock"
    property string markdown: ""
    property int columns: 2
    property bool expanded: !frontend.wordWrap
    property bool copied: false
    signal layoutChanging()
    spacing: 2
    property var rowEdges: []
    function updateRules() { rowEdges = frontend.tableRowEdges(body.textDocument) }
    onMarkdownChanged: rulesTimer.restart()
    onExpandedChanged: { viewport.contentX = 0; rulesTimer.restart() }
    Timer { id: rulesTimer; interval: 0; onTriggered: root.updateRules() }

    function copyTable(formatName) {
        studio.copyText(frontend.tableClipboardText(markdown, formatName))
        copied = true
        feedback.restart()
    }

    Flickable {
        id: viewport
        objectName: "tableViewport"
        width: root.width
        // Qt's painted text bounds omit the final cell padding at some scales.
        // Include the measured row edge so the bottom divider remains visible.
        height: Math.max(body.paintedHeight, root.rowEdges.length
            ? Math.ceil(root.rowEdges[root.rowEdges.length - 1]) : 0)
            + (contentWidth > width ? 10 : 0)
        contentWidth: Math.max(width, body.width, body.paintedWidth)
        contentHeight: height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.HorizontalFlick
        ScrollBar.horizontal: VrScrollBar { }
        VrMarkdownContent {
            id: body
            objectName: "tableBody"
            width: root.expanded ? Math.max(viewport.width * 1.35, root.columns * 220) : viewport.width
            markdown: root.markdown
            onPaintedHeightChanged: rulesTimer.restart()
            onWidthChanged: rulesTimer.restart()
            Component.onCompleted: rulesTimer.restart()
        }
        Repeater {
            model: root.rowEdges
            Rectangle {
                required property var modelData
                objectName: "tableRowRule"
                y: Math.round(modelData) - 1
                width: viewport.contentWidth
                height: 1
                color: Theme.palette.chatBorder
            }
        }
    }
    Item {
        width: root.width
        height: Theme.scaledGeometry(26)
        VrIconButton {
            objectName: "tableExpandButton"
            width: Theme.scaledGeometry(26); height: Theme.scaledGeometry(26)
            symbol: root.expanded ? "↙" : "↗"
            foreground: Theme.palette.mutedText
            checkable: true
            checked: root.expanded
            Accessible.name: root.expanded ? "Ajustar tabela à conversa" : "Ampliar colunas"
            onClicked: { root.layoutChanging(); root.expanded = !root.expanded }
        }
        VrIconButton {
            id: copyButton
            objectName: "tableCopyButton"
            anchors.right: parent.right
            width: Theme.scaledGeometry(26); height: Theme.scaledGeometry(26); iconSize: Theme.iconSmall
            iconKind: root.copied ? "check" : "copy"
            foreground: Theme.palette.mutedText
            Accessible.name: root.copied ? "Copiado" : "Copiar tabela"
            onClicked: copyMenu.popup()
            Menu {
                id: copyMenu
                y: copyButton.height
                x: copyButton.width - width
                MenuItem { text: "Copiar como Markdown"; onTriggered: root.copyTable("markdown") }
                MenuItem { text: "Copiar como CSV"; onTriggered: root.copyTable("csv") }
                MenuItem { text: "Copiar para planilha"; onTriggered: root.copyTable("tsv") }
            }
        }
    }
    Timer { id: feedback; interval: 1500; onTriggered: root.copied = false }
}
