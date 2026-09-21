import QtQuick
import QtQuick.Controls
import "../theme"

Rectangle {
    id: root

    property string code: ""
    property string language: "text"
    property string badge: "<>"
    property bool copied: false
    readonly property alias wrapEnabled: wrapButton.checked

    function copyCode() {
        if (studio) {
            studio.copyText(root.code)
        }
        root.copied = true
        copyTimer.restart()
    }

    objectName: "codeBlockCard"
    onLanguageChanged: frontend.highlightCodeDocument(codeBody.textDocument, root.language)
    Connections {
        target: frontend
        function onThemeChanged() { frontend.highlightCodeDocument(codeBody.textDocument, root.language) }
    }

    Component.onCompleted: {
        if (frontend) {
            frontend.highlightCodeDocument(codeBody.textDocument, root.language)
        }
    }

    Timer {
        id: copyTimer
        interval: 1400
        onTriggered: root.copied = false
    }

    radius: Theme.scaledGeometry(12)
    clip: true
    color: Theme.palette.codeSurface
    border.width: 1
    border.color: Theme.palette.appearance === "light"
        ? Qt.alpha(Theme.palette.border, 0.6)
        : Qt.rgba(255, 255, 255, 0.08)
    implicitHeight: layout.implicitHeight

    Column {
        id: layout
        width: parent.width

        Rectangle {
            id: headerRow
            width: parent.width
            height: Theme.scaledGeometry(32)
            radius: root.radius
            color: Theme.palette.appearance === "light"
                ? Qt.darker(Theme.palette.codeSurface, 1.05)
                : Qt.darker(Theme.palette.codeSurface, 1.08)

            // Fill the bottom corners to keep the bottom of header flush
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: parent.radius
                color: parent.color
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.palette.appearance === "light"
                    ? Qt.alpha(Theme.palette.border, 0.4)
                    : Qt.rgba(255, 255, 255, 0.06)
            }

            Text {
                id: badgeLabel
                anchors.left: parent.left
                anchors.leftMargin: Theme.scaledGeometry(12)
                anchors.right: wrapButton.left
                anchors.rightMargin: Theme.scaledGeometry(8)
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: root.language
                color: Theme.palette.subtleText || Theme.palette.mutedText || "#8f9ca8"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                font.weight: Font.Normal
                renderType: Theme.textRenderType
                verticalAlignment: Text.AlignVCenter
            }

            VrIconButton {
                id: wrapButton
                objectName: "codeBlockWrap"
                anchors.right: copyButton.left
                anchors.rightMargin: Theme.scaledGeometry(4)
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: Theme.scaledGeometry(26)
                implicitHeight: Theme.scaledGeometry(26)
                iconSize: 14
                iconKind: "wrapText"
                checkable: true
                checked: frontend.wordWrap
                foreground: checked
                    ? (Theme.palette.headingText || "#FFFFFF")
                    : (hovered ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8"))
                Accessible.name: checked ? "Desativar quebra de linhas" : "Quebrar linhas"
            }

            VrIconButton {
                id: copyButton
                objectName: "codeBlockCopy"
                anchors.right: parent.right
                anchors.rightMargin: Theme.scaledGeometry(8)
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: Theme.scaledGeometry(26)
                implicitHeight: Theme.scaledGeometry(26)
                iconSize: 14
                iconKind: root.copied ? "check" : "copy"
                foreground: root.copied
                    ? (Theme.palette.success || "#34d399")
                    : (hovered ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8"))
                Accessible.name: root.copied ? "Copiado!" : "Copiar código"
                onClicked: root.copyCode()
            }
        }

        Flickable {
            id: codeViewport
            objectName: "codeViewport"
            width: parent.width
            height: codeBody.paintedHeight + 20 + (contentWidth > width ? 8 : 0)
            contentWidth: wrapButton.checked ? width : Math.max(width, codeBody.paintedWidth + 28)
            contentHeight: height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.HorizontalFlick
            ScrollBar.horizontal: VrScrollBar { }
            TextEdit {
                id: codeBody
                objectName: "codeBlockBody"
                width: codeViewport.width
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
                wrapMode: wrapButton.checked ? TextEdit.Wrap : TextEdit.NoWrap
                color: Theme.palette.text
                selectionColor: Theme.palette.selection
                selectedTextColor: Theme.palette.text
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.monospaceFontSize(13)
            }
        }
    }
}
