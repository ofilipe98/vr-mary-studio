import QtQuick
import QtQuick.Controls
import "../theme"

// Wraps the Markdown TextEdit so VrInlineChipLayer can paint the T3 chip
// chrome (rounded fill + hairline border) behind the text. The body keeps
// the messageBody object name by default; table bodies override it.
Item {
    id: control
    property string markdown: ""
    property string bodyObjectName: "messageBody"
    // T3 chat markdown renders at text-sm (14) with leading-relaxed. The table
    // block reuses this surface at .75rem (12) like `.chat-markdown table`.
    property real fontPixelSize: Theme.markdownBodySize
    property var chipRanges: []
    property bool applyingStyle: false
    readonly property alias paintedHeight: body.paintedHeight
    readonly property alias paintedWidth: body.paintedWidth
    readonly property alias textDocument: body.textDocument
    implicitHeight: body.paintedHeight

    function applyStyle() {
        if (applyingStyle) return
        applyingStyle = true
        frontend.styleMessageDocument(body.textDocument, markdown)
        chipRanges = frontend.messageChipRanges(body.textDocument)
        applyingStyle = false
    }

    VrInlineChipLayer {
        anchors.fill: parent
        body: body
        ranges: control.chipRanges
        fontPixelSize: control.fontPixelSize
    }

    TextEdit {
        id: body
        objectName: control.bodyObjectName
        width: control.width
        text: control.markdown
        textFormat: TextEdit.MarkdownText
        readOnly: true
        selectByMouse: true
        persistentSelection: true
        wrapMode: TextEdit.Wrap
        color: Theme.palette.text
        renderType: Theme.textRenderType
        selectionColor: Theme.palette.selection
        selectedTextColor: Theme.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: control.fontPixelSize
        // Rhythm for Markdown blocks comes from frontend.styleMessageDocument
        // (QTextDocument block line-height, T3 leading-relaxed equivalent).
        height: paintedHeight
        onTextChanged: control.applyStyle()
        onLinkActivated: link => {
            var value = String(link)
            if (value.indexOf("vr-file:") === 0 || value.indexOf("file:") === 0) {
                if (typeof chat !== "undefined" && chat) chat.openFileReference(value)
            } else if (value.indexOf("vr-code:") === 0) {
                if (typeof chat !== "undefined" && chat) chat.openDecompiledReference(value)
            } else if (studio) {
                studio.openExternalUrl(value)
            }
        }
        HoverHandler {
            cursorShape: body.linkAt(point.position.x, point.position.y)
                ? Qt.PointingHandCursor : Qt.IBeamCursor
        }
    }

    onMarkdownChanged: applyStyle()
    onFontPixelSizeChanged: applyStyle()
    Component.onCompleted: applyStyle()
    Connections {
        target: frontend
        function onThemeChanged() { control.applyStyle() }
        function onTypographyChanged() { control.applyStyle() }
    }
}
