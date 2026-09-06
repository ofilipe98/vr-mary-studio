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
    selectionColor: Theme.palette.selection
    selectedTextColor: Theme.palette.text
    font.family: Theme.fontFamily
    font.pixelSize: Theme.bodySize
    height: paintedHeight
    onLinkActivated: link => { if (studio) studio.openExternalUrl(link) }
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
