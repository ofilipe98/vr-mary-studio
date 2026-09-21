pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import "../theme"

Column {
    id: root
    property string markdown: ""
    property string messageKey: ""
    property bool streaming: false
    property var sources: []
    property bool copied: false
    readonly property bool animating: collapsible.animating
    signal copyRequested()
    signal layoutChanging()
    signal toggled(bool expanded, real heightDelta)
    signal anchorRequested()
    signal transitionFinished()
    spacing: Theme.scaledGeometry(12)
    // Update existing rows in place: completed blocks keep selection and code wrap.
    function syncBlocks() {
        layoutChanging()
        var incoming = frontend.messageBlocks(markdown)
        var prose = [], citations = []
        for (var i = 0; i < incoming.length; ++i) {
            if (incoming[i].kind === "source") citations.push(incoming[i])
            else prose.push({kind: incoming[i].kind, body: incoming[i].content,
                language: incoming[i].language || "text", columns: Number(incoming[i].columns || 0)})
        }
        while (blocks.count > prose.length) blocks.remove(blocks.count - 1)
        for (var j = 0; j < prose.length; ++j) {
            if (j >= blocks.count) blocks.append(prose[j])
            else {
                var old = blocks.get(j), next = prose[j]
                if (old.kind !== next.kind || old.body !== next.body || old.language !== next.language || old.columns !== next.columns)
                    blocks.set(j, next)
            }
        }
        if (JSON.stringify(sources) !== JSON.stringify(citations)) sources = citations
    }
    onMarkdownChanged: syncBlocks()
    Component.onCompleted: syncBlocks()
    ListModel { id: blocks }
    VrCollapsibleMessageContent {
        id: collapsible
        width: root.width
        collapseEnabled: false
        // Preserve the pre-collapse Markdown block rhythm (spacing 12).
        contentSpacing: 12
        messageKey: root.messageKey
        streaming: root.streaming
        fadeColor: Theme.palette.chatBackground
        onLayoutChanging: root.layoutChanging()
        onToggled: (expanded, heightDelta) => root.toggled(expanded, heightDelta)
        onAnchorRequested: root.anchorRequested()
        onTransitionFinished: root.transitionFinished()
        Repeater {
            model: blocks
            delegate: Loader {
                id: block
                required property string kind
                required property string body
                required property string language
                required property int columns
                width: collapsible.width
                sourceComponent: kind === "code" ? codeComponent : kind === "table" ? tableComponent : proseComponent
                Component { id: proseComponent; VrMarkdownContent { markdown: block.body } }
                Component { id: codeComponent; VrCodeBlock { code: block.body; language: block.language } }
                Component {
                    id: tableComponent
                    VrTableBlock {
                        markdown: block.body
                        columns: block.columns
                        onLayoutChanging: root.layoutChanging()
                    }
                }
            }
        }
    }
    VrSources { width: root.width; sources: root.sources }
    Item {
        width: parent.width
        height: Theme.scaledGeometry(26)
        Rectangle {
            width: Theme.scaledGeometry(5); height: Theme.scaledGeometry(5); radius: Theme.scaledGeometry(3)
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.palette.mutedText
            visible: root.streaming
        }
        VrIconButton {
            id: copy
            objectName: "messageCopyButton"
            anchors.left: parent.left
            width: Theme.scaledGeometry(28); height: Theme.scaledGeometry(26); iconSize: Theme.iconSmall
            iconKind: root.copied ? "check" : "copy"
            opacity: hover.hovered || hovered || activeFocus || root.copied ? 1 : 0
            Accessible.name: root.copied ? "Copiado" : "Copiar resposta"
            onClicked: { root.copyRequested(); root.copied = true; copiedTimer.restart() }
            Behavior on opacity { enabled: !frontend.reduceMotion; NumberAnimation { duration: Theme.fastDuration } }
        }
    }
    Timer { id: copiedTimer; interval: 1500; onTriggered: root.copied = false }
    HoverHandler { id: hover }
}
