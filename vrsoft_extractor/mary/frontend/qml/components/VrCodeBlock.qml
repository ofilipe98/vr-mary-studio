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
    color: frontend.themeId === "dark_orange" ? "#1E1E22" : "#F6F6F8"
    border.width: 1
    border.color: frontend.themeId === "dark_orange" ? "#34343A" : "#D8D8E0"
    implicitHeight: headerRow.height + codeBody.paintedHeight
        + codeBody.topPadding + codeBody.bottomPadding

    Column {
        id: layout
        width: parent.width

        Rectangle {
            id: headerRow
            width: parent.width
            height: 30
            color: frontend.themeId === "dark_orange" ? "#232327" : "#ECECF1"
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
                color: frontend.themeId === "dark_orange" ? "#34343A" : "#D8D8E0"

                Text {
                    id: badgeLabel
                    anchors.centerIn: parent
                    text: root.badge
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

        TextEdit {
            id: codeBody
            width: parent.width
            padding: 12
            text: root.code
            textFormat: TextEdit.PlainText
            readOnly: true
            activeFocusOnPress: false
            wrapMode: wrapButton.checked ? TextEdit.Wrap : TextEdit.NoWrap
            color: frontend.themeId === "dark_orange" ? "#E4E4E7" : "#27272A"
            font.family: Theme.monospaceFontFamily
            font.pixelSize: Theme.monospaceFontSize(12)
        }
    }
}
