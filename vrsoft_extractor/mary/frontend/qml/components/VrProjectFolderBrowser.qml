import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "projectFolderBrowser"

    signal backRequested()
    signal closeRequested()
    signal projectAdded()

    function syncPath() {
        folderPath.text = chat.projectFolderDisplayPath
    }

    function addCurrentFolder() {
        if (chat.addCurrentProjectFolder().length) root.projectAdded()
    }

    Keys.onPressed: event => {
        if ((event.modifiers & Qt.ControlModifier) && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
            root.addCurrentFolder()
            event.accepted = true
        } else if (event.key === Qt.Key_Backspace && !folderPath.activeFocus) {
            chat.browseParentProjectFolder()
            event.accepted = true
        } else if (event.key === Qt.Key_Escape) {
            root.closeRequested()
            event.accepted = true
        }
    }

    Connections {
        target: chat
        function onProjectFolderChanged() { root.syncPath() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 50
            Layout.leftMargin: 8
            Layout.rightMargin: 10
            spacing: 4
            VrIconButton {
                objectName: "projectFolderBackButton"
                implicitWidth: 34
                implicitHeight: 34
                iconKind: "back"
                foreground: Theme.palette.text
                onClicked: root.backRequested()
            }
            VrTextField {
                id: folderPath
                objectName: "projectFolderPathField"
                Layout.fillWidth: true
                implicitHeight: 36
                text: chat.projectFolderDisplayPath
                background: Item { }
                onAccepted: chat.browseProjectFolder(text)
            }
            VrButton {
                objectName: "projectFolderAddButton"
                text: "Adicionar"
                variant: "secondary"
                implicitHeight: 30
                onClicked: root.addCurrentFolder()
            }
            Rectangle {
                Layout.preferredWidth: shortcutLabel.implicitWidth + 10
                Layout.preferredHeight: 22
                radius: 5
                color: Theme.palette.chatControl
                Text {
                    id: shortcutLabel
                    anchors.centerIn: parent
                    text: "Ctrl Enter"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMicro
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.palette.chatDivider }

        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 18
            Layout.rightMargin: 18
            Layout.topMargin: 14
            Layout.bottomMargin: 6
            text: "Diretórios"
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeCaption
            font.weight: Font.DemiBold
        }

        ListView {
            id: folderList
            objectName: "projectFolderList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 10
            Layout.rightMargin: 10
            clip: true
            spacing: 2
            model: chat.projectFolderItems
            currentIndex: count ? 0 : -1
            focus: true
            ScrollIndicator.vertical: ScrollIndicator { }

            Keys.onReturnPressed: {
                if (currentIndex >= 0) chat.browseProjectFolder(chat.projectFolderItems[currentIndex].path)
            }
            Keys.onEnterPressed: {
                if (currentIndex >= 0) chat.browseProjectFolder(chat.projectFolderItems[currentIndex].path)
            }

            delegate: Button {
                id: folderRow
                required property int index
                required property var modelData
                width: folderList.width
                height: 34
                padding: 0
                hoverEnabled: true
                onClicked: chat.browseProjectFolder(modelData.path)
                background: Rectangle {
                    radius: 6
                    color: folderRow.hovered || folderList.currentIndex === folderRow.index
                        ? Theme.palette.chatControl : "transparent"
                }
                contentItem: RowLayout {
                    spacing: 9
                    Image {
                        Layout.preferredWidth: 17
                        Layout.preferredHeight: 17
                        source: Qt.resolvedUrl(frontend.themeId === "dark_orange"
                            ? "../../../assets/project-folder-dark.svg"
                            : "../../../assets/project-folder.svg")
                        fillMode: Image.PreserveAspectFit
                    }
                    Text {
                        Layout.fillWidth: true
                        text: folderRow.modelData.label
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        elide: Text.ElideRight
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: folderList.count === 0
                text: "Nenhuma subpasta disponível"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 42
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatDivider
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: 10
                Text {
                    text: "↑↓  Navegar    Enter  Abrir    Backspace  Voltar    Esc  Fechar"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMicro
                    font.weight: Theme.weightMedium
                }
                Item { Layout.fillWidth: true }
                Button {
                    flat: true
                    text: "Abrir no Explorer"
                    onClicked: chat.openCurrentProjectFolder()
                    contentItem: Text {
                        text: parent.text
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        font.weight: Theme.weightMedium
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Item { }
                }
            }
        }
    }

    Component.onCompleted: root.syncPath()
}
