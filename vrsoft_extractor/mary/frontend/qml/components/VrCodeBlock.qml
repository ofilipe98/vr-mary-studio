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

    radius: 8
    clip: true
    color: Theme.palette.codeSurface
    border.width: 1
    border.color: Theme.palette.chatBorder
    implicitHeight: layout.implicitHeight

    Column {
        id: layout
        width: parent.width

        Rectangle {
            id: headerRow
            width: parent.width
            height: 30
            color: Theme.palette.codeHeader
            radius: 8

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.verticalCenter
                height: parent.height / 2
                color: parent.color
            }

            Rectangle {
                id: languageBadge
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                width: badgeLabel.implicitWidth + 14
                height: 18
                radius: 4
                color: "transparent"

                Text {
                    id: badgeLabel
                    anchors.centerIn: parent
                    text: root.language
                    color: frontend.themeId === "dark_orange" ? "#C9C9D3" : "#3F3F46"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(10)
                    font.weight: Font.DemiBold
                }
            }

            VrIconButton {
                id: wrapButton
                objectName: "codeBlockWrap"
                anchors.right: copyButton.left
                anchors.rightMargin: 4
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: 24
                implicitHeight: 24
                checkable: true
                checked: frontend.wordWrap
                iconKind: ""
                symbol: "↵"
                foreground: checked
                    ? frontend.palette.text : frontend.palette.mutedText
                ToolTip.visible: hovered
                ToolTip.text: checked ? "Não quebrar linhas" : "Quebrar linhas"
            }

            VrIconButton {
                id: copyButton
                objectName: "codeBlockCopy"
                anchors.right: parent.right
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: 24
                implicitHeight: 24
                iconSize: 13
                iconKind: root.copied ? "" : "copy"
                symbol: root.copied ? "✓" : ""
                foreground: root.copied
                    ? frontend.palette.success : frontend.palette.mutedText
                ToolTip.visible: hovered
                ToolTip.text: root.copied ? "Copiado" : "Copiar código"
                onClicked: root.copyCode()
            }
        }

        Flickable {
            id: codeViewport
            objectName: "codeViewport"
            width: parent.width
            height: codeBody.paintedHeight + 24 + (contentWidth > width ? 8 : 0)
            contentWidth: wrapButton.checked ? width : Math.max(width, codeBody.paintedWidth + 24)
            contentHeight: height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.HorizontalFlick
            ScrollBar.horizontal: VrScrollBar { }
            TextEdit {
                id: codeBody
                objectName: "codeBlockBody"
                width: codeViewport.width
                padding: 12
                text: root.code
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                persistentSelection: true
                activeFocusOnPress: true
                wrapMode: wrapButton.checked ? TextEdit.Wrap : TextEdit.NoWrap
                color: Theme.palette.text
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.monospaceFontSize(12)
            }
        }
    }
}
