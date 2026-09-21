import QtQuick
import QtQuick.Controls
import "../theme"

TextEdit {
    id: control
    objectName: "messageBody"
    property string markdown: ""
    property bool applyingStyle: false
    text: markdown
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
    font.pixelSize: Theme.bodySize
    // Rhythm for Markdown blocks comes from frontend.styleMessageDocument
    // (QTextDocument block line-height, T3 leading-relaxed equivalent).
    height: paintedHeight
    onLinkActivated: link => {
        var value = String(link)
        if (value.indexOf("vr-file:") === 0 || value.indexOf("file:") === 0) {
            if (typeof chat !== "undefined" && chat) chat.openFileReference(value)
        } else if (studio) {
            studio.openExternalUrl(value)
        }
    }
    function applyStyle() {
        if (applyingStyle) return
        applyingStyle = true
        frontend.styleMessageDocument(textDocument, markdown)
        applyingStyle = false
    }
    // Finish layout before ListView measures a newly visible/reused delegate.
    onTextChanged: applyStyle()
    Component.onCompleted: applyStyle()
    Connections {
        target: frontend
        function onThemeChanged() { control.applyStyle() }
        function onTypographyChanged() { control.applyStyle() }
    }
    HoverHandler {
        cursorShape: control.linkAt(point.position.x, point.position.y)
            ? Qt.PointingHandCursor : Qt.IBeamCursor
    }
}
