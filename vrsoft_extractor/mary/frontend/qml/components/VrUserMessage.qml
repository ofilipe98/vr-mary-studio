import QtQuick
import QtQuick.Controls
import "../theme"

Item {
    id: root
    property string content: ""
    property string messageKey: ""
    property bool copied: false
    readonly property bool animating: collapsible.animating
    signal copyRequested()
    signal layoutChanging()
    signal toggled(bool expanded, real heightDelta)
    signal anchorRequested()
    signal transitionFinished()
    implicitHeight: bubble.height + 18
    TextMetrics { id: measure; font: body.font; text: root.content }
    Rectangle {
        id: bubble
        anchors.right: parent.right
        width: Math.min(root.width * (root.width < 500 || root.content.length > 900 ? 0.9 : 0.8), Math.max(64, measure.advanceWidth + 28))
        height: collapsible.implicitHeight + 24
        radius: Theme.messageRadius
        color: Theme.palette.messageSurface
        VrCollapsibleMessageContent {
            id: collapsible
            x: 14; y: 12; width: parent.width - 28
            messageKey: root.messageKey
            fadeColor: Theme.palette.messageSurface
            onLayoutChanging: root.layoutChanging()
            onToggled: (expanded, heightDelta) => root.toggled(expanded, heightDelta)
            onAnchorRequested: root.anchorRequested()
            onTransitionFinished: root.transitionFinished()
            TextEdit {
                id: body
                objectName: "messageBody"
                width: parent.width
                text: root.content
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                persistentSelection: true
                wrapMode: TextEdit.Wrap
                color: Theme.palette.text
                renderType: Theme.textRenderType
                selectionColor: Theme.palette.selection
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
            }
        }
    }
    VrIconButton {
        anchors.right: bubble.right
        anchors.top: bubble.bottom
        width: 28; height: 26; iconSize: Theme.iconSmall
        objectName: "messageCopyButton"
        iconKind: root.copied ? "check" : "copy"
        opacity: hover.hovered || hovered || activeFocus || root.copied ? 1 : 0
        ToolTip.visible: hovered || activeFocus
        ToolTip.text: root.copied ? "Copiado" : "Copiar mensagem"
        onClicked: { root.copyRequested(); root.copied = true; feedback.restart() }
        Behavior on opacity { enabled: !frontend.reduceMotion; NumberAnimation { duration: Theme.fastDuration } }
    }
    Timer { id: feedback; interval: 1500; onTriggered: root.copied = false }
    HoverHandler { id: hover }
}
