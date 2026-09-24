import QtQuick
import QtQuick.Controls
import "../theme"

Rectangle {
    id: root
    objectName: "decompiledSourceViewer"

    required property var frontendBridge
    property string code: ""
    property string language: "java"
    property int targetLine: 0

    function lineStartPosition(lineNumber) {
        var line = Number(lineNumber)
        if (!isFinite(line) || Math.floor(line) !== line || line < 1)
            return -1
        var lines = String(root.code).split("\n")
        if (line > lines.length)
            return -1
        var offset = 0
        for (var index = 0; index < line - 1; ++index)
            offset += lines[index].length + 1
        return offset
    }

    function revealLine() {
        var line = Number(root.targetLine)
        if (!isFinite(line) || Math.floor(line) !== line || line <= 0)
            return
        Qt.callLater(function() {
            var offset = root.lineStartPosition(line)
            if (offset < 0)
                return
            var rectangle = body.positionToRectangle(offset)
            var maximumY = Math.max(0, viewport.contentHeight - viewport.height)
            var targetY = rectangle.y - viewport.height * 0.2
            viewport.contentY = Math.max(0, Math.min(targetY, maximumY))
        })
    }

    color: Theme.palette.codeSurface
    clip: true
    onCodeChanged: {
        if (root.frontendBridge)
            root.frontendBridge.highlightCodeDocument(body.textDocument, root.language)
    }
    onLanguageChanged: {
        if (root.frontendBridge)
            root.frontendBridge.highlightCodeDocument(body.textDocument, root.language)
    }

    Component.onCompleted: {
        if (root.frontendBridge)
            root.frontendBridge.highlightCodeDocument(body.textDocument, root.language)
    }

    Connections {
        target: root.frontendBridge
        function onThemeChanged() {
            if (root.frontendBridge)
                root.frontendBridge.highlightCodeDocument(body.textDocument, root.language)
        }
    }

    Flickable {
        id: viewport
        objectName: "decompiledSourceViewport"
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.AutoFlickIfNeeded
        contentWidth: Math.max(width, body.paintedWidth + Theme.scaledGeometry(28))
        contentHeight: Math.max(height, body.paintedHeight + Theme.scaledGeometry(20))
        ScrollBar.horizontal: VrScrollBar { }
        ScrollBar.vertical: VrScrollBar { }

        TextEdit {
            id: body
            objectName: "decompiledSourceBody"
            leftPadding: Theme.scaledGeometry(14)
            rightPadding: Theme.scaledGeometry(14)
            topPadding: Theme.scaledGeometry(10)
            bottomPadding: Theme.scaledGeometry(10)
            text: root.code
            textFormat: TextEdit.PlainText
            readOnly: true
            selectByMouse: true
            persistentSelection: true
            activeFocusOnPress: true
            renderType: Theme.textRenderType
            wrapMode: TextEdit.NoWrap
            color: Theme.palette.text
            selectionColor: Theme.palette.selection
            selectedTextColor: Theme.palette.text
            font.family: Theme.monospaceFontFamily
            font.pixelSize: Theme.monospaceFontSize(12)
        }
    }
}
