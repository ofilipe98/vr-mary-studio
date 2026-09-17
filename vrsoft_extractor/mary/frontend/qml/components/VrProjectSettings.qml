import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../settings/appearance"

Item {
    id: control

    property int projectIndex: -1
    property string projectName: ""
    property string projectPath: ""
    property string projectIconPath: ""
    property string projectIconKind: ""
    property string projectIconEmoji: ""
    property string projectIconColor: ""
    property string projectIconText: ""
    property int threadCount: 0
    signal closeRequested()
    signal saveRequested(string name)
    signal iconRequested()
    signal iconCustomized(string kind, string color, string emoji, string text)
    signal iconCleared()
    signal openFolderRequested()
    signal copyPathRequested()
    signal removeRequested()

    function threadLabel() {
        return control.threadCount === 1 ? "1 conversa" : control.threadCount + " conversas"
    }

    function isIconCustomized() {
        return control.projectIconPath.length > 0
            || control.projectIconKind.length > 0
            || control.projectIconEmoji.length > 0
            || control.projectIconColor.length > 0
            || control.projectIconText.length > 0
    }

    function iconSummary() {
        if (control.projectIconPath.length) return "Imagem personalizada"
        if (control.projectIconEmoji.length) return "Emoji · " + control.projectIconEmoji
        if (control.projectIconKind.length)
            return control.projectIconKind + " · " + previewIcon.iconColorName(control.projectIconColor)
        if (control.projectIconText.length) return "Monograma · " + control.projectIconText
        if (control.projectIconColor.length)
            return "Monograma · " + previewIcon.iconColorName(control.projectIconColor)
        return "Automático"
    }

    function resetView() {
        settingsFlickable.contentY = 0
    }

    onVisibleChanged: {
        if (visible) Qt.callLater(control.resetView)
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.palette.chatBackground
    }

    RowLayout {
        id: settingsHeader
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Theme.chatHeaderHeight
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 8

        Button {
            id: projectSettingsBack
            objectName: "projectSettingsBack"
            implicitWidth: backContent.implicitWidth
            implicitHeight: 30
            padding: 0
            hoverEnabled: true
            onClicked: control.closeRequested()
            contentItem: RowLayout {
                id: backContent
                spacing: 6
                VrLineIcon {
                    Layout.preferredWidth: 14
                    Layout.preferredHeight: 14
                    kind: "back"
                    foreground: projectSettingsBack.hovered
                        ? Theme.palette.text : Theme.palette.mutedText
                }
                Text {
                    id: projectsBreadcrumb
                    text: "Voltar"
                    color: projectSettingsBack.hovered
                        ? Theme.palette.text : Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    verticalAlignment: Text.AlignVCenter
                }
            }
            background: Item { }
        }
        Text {
            text: "/"
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(12)
        }
        Text {
            Layout.fillWidth: true
            text: control.projectName
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: settingsHeader.bottom
        height: 1
        color: Theme.palette.chatDivider
    }

    Flickable {
        id: settingsFlickable
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: settingsHeader.bottom
        anchors.bottom: parent.bottom
        clip: true
        contentWidth: width
        contentHeight: settingsContent.implicitHeight + 64
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: settingsContent
            x: Math.max(16, (settingsFlickable.width - width) / 2)
            y: 20
            width: Math.min(848, settingsFlickable.width - 32)
            spacing: 24

            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: projectCardContent.implicitHeight + 2
                radius: 14
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border

                ColumnLayout {
                    id: projectCardContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 1
                    spacing: 0

                    AppearanceRow {
                        title: "Name"
                        description: "The shared name for this project group in the sidebar and thread lists."
                        divider: true
                        VrTextField {
                            id: projectNameField
                            objectName: "projectSettingsName"
                            implicitWidth: 256
                            Layout.maximumWidth: 256
                            Layout.minimumWidth: 0
                            implicitHeight: 34
                            text: control.projectName
                            selectByMouse: true
                            onEditingFinished: {
                                var value = text.trim()
                                if (value.length) control.saveRequested(value)
                            }
                        }
                    }

                    AppearanceRow {
                        title: "Project icon"
                        description: control.iconSummary()
                        divider: false
                        VrProjectIcon {
                            id: previewIcon
                            Layout.preferredWidth: 30
                            Layout.preferredHeight: 30
                            boxSize: 30
                            iconSize: 17
                            projectLabel: control.projectName
                            iconPath: control.projectIconPath
                            iconKind: control.projectIconKind
                            iconEmoji: control.projectIconEmoji
                            iconColor: control.projectIconColor
                            iconText: control.projectIconText
                        }
                        VrIconButton {
                            visible: control.isIconCustomized()
                            iconKind: "reset"
                            iconSize: 13
                            implicitWidth: 28
                            implicitHeight: 28
                            foreground: Theme.palette.mutedText
                            ToolTip.visible: hovered
                            ToolTip.text: "Voltar ao automático"
                            Accessible.name: "Voltar ao ícone automático"
                            onClicked: control.iconCleared()
                        }
                        VrButton {
                            objectName: "projectSettingsChooseIcon"
                            text: "Choose icon"
                            variant: "secondary"
                            implicitHeight: 32
                            onClicked: iconPicker.openFor(
                                control.projectIconKind, control.projectIconColor,
                                control.projectIconEmoji, control.projectIconText)
                        }
                        VrButton {
                            objectName: "projectSettingsChooseFile"
                            text: "Choose file"
                            variant: "secondary"
                            implicitHeight: 32
                            ToolTip.visible: hovered
                            ToolTip.text: "Escolher imagem do disco"
                            onClicked: control.iconRequested()
                        }
                    }
                }
            }

            Text {
                text: "Novas conversas"
                Layout.leftMargin: 16
                color: Theme.palette.text
                opacity: 0.7
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(14)
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: defaultsCardContent.implicitHeight + 2
                radius: 14
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border

                ColumnLayout {
                    id: defaultsCardContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 1
                    spacing: 0

                    AppearanceRow {
                        title: "Modelo"
                        description: "Novas conversas desta pasta começam com este modelo."
                        divider: true
                        VrModelPicker {
                            implicitWidth: 188
                            implicitHeight: 30
                            outlined: true
                            popupAbove: false
                            model: chat.modelItems
                            currentIndex: chat.modelIndex
                            onActivated: index => chat.setModel(index)
                            onFavoriteToggled: index => chat.toggleModelFavorite(index)
                        }
                    }

                    AppearanceRow {
                        visible: chat.supportsReasoning
                        title: "Esforço do modelo padrão"
                        description: "Define o nível de raciocínio inicial das novas conversas deste projeto."
                        divider: true
                        VrReasoningPicker {
                            implicitWidth: 188
                            implicitHeight: 30
                            outlined: true
                            popupAbove: false
                            effortModel: chat.effortItems
                            tierModel: []
                            currentEffortIndex: chat.effortIndex
                            currentTierIndex: -1
                            onEffortActivated: index => chat.setEffort(index)
                        }
                    }

                    AppearanceRow {
                        title: "Workspace"
                        description: "Onde as novas conversas deste projeto começam. Substitui o padrão global e se aplica a cada checkout deste grupo."
                        divider: false
                        VrComboBox {
                            implicitWidth: 202
                            implicitHeight: 32
                            model: [{label: "Padrão (pasta atual)"}]
                            textRole: "label"
                            currentIndex: 0
                        }
                    }
                }
            }

            Text {
                text: "Checkout"
                Layout.leftMargin: 16
                color: Theme.palette.text
                opacity: 0.7
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(14)
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredHeight: 44
                radius: 14
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 12
                    spacing: 8
                    Text {
                        objectName: "projectSettingsOpenFolder"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: control.projectPath
                        color: pathHover.hovered ? Theme.palette.text : Theme.palette.mutedText
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.monospaceFontSize(10)
                        elide: Text.ElideMiddle
                        HoverHandler { id: pathHover }
                        TapHandler { onTapped: control.openFolderRequested() }
                    }
                    Item {
                        Layout.preferredWidth: 26
                        Layout.preferredHeight: 26
                        VrLineIcon { anchors.centerIn: parent; width: 15; height: 15; kind: "copy"; foreground: copyMouse.containsMouse ? Theme.palette.text : Theme.palette.mutedText; strokeWidth: 1.5 }
                        MouseArea { id: copyMouse; anchors.fill: parent; hoverEnabled: true; onClicked: control.copyPathRequested() }
                        ToolTip.visible: copyMouse.containsMouse
                        ToolTip.text: "Copiar caminho"
                    }
                    Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.palette.chatDivider }
                    VrComboBox {
                        implicitWidth: 96
                        implicitHeight: 30
                        model: [{label: "LF"}]
                        textRole: "label"
                        currentIndex: 0
                    }
                    Text { text: control.threadLabel(); color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: groupingCardContent.implicitHeight + 2
                radius: 14
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border

                ColumnLayout {
                    id: groupingCardContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 1
                    spacing: 0

                    AppearanceRow {
                        title: "Agrupamento do projeto"
                        description: "Define como esta pasta aparece nos grupos da barra lateral."
                        divider: false
                        VrComboBox {
                            implicitWidth: 222
                            implicitHeight: 32
                            model: [{label: "Padrão (por repositório)"}]
                            textRole: "label"
                            currentIndex: 0
                        }
                    }
                }
            }

            Text {
                text: "Ações"
                Layout.leftMargin: 16
                color: Theme.palette.text
                opacity: 0.7
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(14)
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: actionsCardContent.implicitHeight + 2
                radius: 14
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border

                ColumnLayout {
                    id: actionsCardContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 1
                    spacing: 0

                    AppearanceRow {
                        title: "Actions"
                        description: "Commands that run in this project's checkout or its worktree, with optional shortcuts."
                        divider: true
                        VrButton {
                            text: "+ Add action"
                            variant: "secondary"
                            implicitHeight: 30
                            enabled: false
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.topMargin: 12
                        Layout.bottomMargin: 12
                        text: "No actions configured."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                    }
                }
            }

            Text {
                text: "Perigo"
                Layout.leftMargin: 16
                color: Theme.palette.text
                opacity: 0.7
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(14)
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.bottomMargin: 12
                implicitHeight: dangerCardContent.implicitHeight + 2
                radius: 14
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border

                ColumnLayout {
                    id: dangerCardContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 1
                    spacing: 0

                    AppearanceRow {
                        title: "Remove project"
                        description: "Deletes the project entry and its threads. Files on disk are not touched."
                        divider: false
                        Button {
                            implicitWidth: 150
                            implicitHeight: 32
                            padding: 0
                            hoverEnabled: true
                            onClicked: control.removeRequested()
                            contentItem: RowLayout {
                                spacing: 7
                                Item { Layout.fillWidth: true }
                                VrLineIcon { Layout.preferredWidth: 15; Layout.preferredHeight: 15; kind: "trash"; foreground: Theme.palette.danger; strokeWidth: 1.55 }
                                Text { text: "Remove project"; color: Theme.palette.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                                Item { Layout.fillWidth: true }
                            }
                            background: Rectangle {
                                radius: 8
                                color: parent.down || parent.hovered ? Qt.rgba(1, 0.18, 0.18, 0.08) : "transparent"
                                border.width: 1
                                border.color: Theme.palette.danger
                            }
                        }
                    }
                }
            }
        }
    }

    VrProjectIconPicker {
        id: iconPicker
        projectLabel: control.projectName
        onSaved: (kind, color, emoji, text) => control.iconCustomized(kind, color, emoji, text)
    }
}
