import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: control

    property int projectIndex: -1
    property string projectName: ""
    property string projectPath: ""
    property string projectIconPath: ""
    property int threadCount: 0
    signal closeRequested()
    signal saveRequested(string name)
    signal iconRequested()
    signal openFolderRequested()
    signal copyPathRequested()
    signal removeRequested()

    function threadLabel() {
        return control.threadCount === 1 ? "1 conversa" : control.threadCount + " conversas"
    }

    function projectIconSource() {
        if (!control.projectIconPath.length) return ""
        return "file:///" + control.projectIconPath.replace(/\\/g, "/")
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
            x: Math.max(28, (settingsFlickable.width - width) / 2)
            y: 24
            width: Math.min(816, settingsFlickable.width - 56)
            spacing: 0

            Text {
                Layout.fillWidth: true
                Layout.bottomMargin: 16
                text: "Projeto"
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(17)
                font.weight: Font.DemiBold
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 54
                spacing: 32
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text { text: "Nome"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Nome compartilhado na lista de projetos e nas conversas."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); wrapMode: Text.WordWrap }
                }
                VrTextField {
                    id: projectNameField
                    objectName: "projectSettingsName"
                    Layout.preferredWidth: 256
                    Layout.preferredHeight: 32
                    text: control.projectName
                    selectByMouse: true
                    onEditingFinished: {
                        var value = text.trim()
                        if (value.length) control.saveRequested(value)
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 21
                Layout.preferredHeight: 54
                spacing: 32
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text { text: "Ícone do projeto"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { text: control.projectIconPath.length ? "Personalizado" : "Automático"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                }
                RowLayout {
                    Layout.preferredWidth: 256
                    spacing: 8
                    Item { Layout.fillWidth: true }
                    Item {
                        Layout.preferredWidth: 19
                        Layout.preferredHeight: 19
                        VrLineIcon { visible: !control.projectIconPath.length; anchors.fill: parent; kind: "folder"; foreground: Theme.palette.mutedText; strokeWidth: 1.55 }
                        Image { visible: control.projectIconPath.length > 0; anchors.fill: parent; source: control.projectIconSource(); fillMode: Image.PreserveAspectFit; smooth: true }
                    }
                    VrButton {
                        implicitWidth: 92
                        implicitHeight: 26
                        text: "Escolher"
                        variant: "secondary"
                        onClicked: control.iconRequested()
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 60
                Layout.bottomMargin: 15
                text: "Novas conversas"
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(17)
                font.weight: Font.DemiBold
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 58
                spacing: 32
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    RowLayout {
                        spacing: 5
                        Text { text: "Modelo"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                        Text { text: "↶"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                    }
                    Text { Layout.fillWidth: true; text: "Novas conversas desta pasta começam com este modelo."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); wrapMode: Text.WordWrap }
                }
                RowLayout {
                    Layout.preferredWidth: 256
                    spacing: 8
                    Item { Layout.fillWidth: true }
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
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 10
                Layout.preferredHeight: 58
                spacing: 32
                visible: chat.supportsReasoning
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text { text: "Esforço do modelo padrão"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Define o nível de raciocínio inicial das novas conversas deste projeto."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); wrapMode: Text.WordWrap }
                }
                RowLayout {
                    Layout.preferredWidth: 256
                    spacing: 8
                    Item { Layout.fillWidth: true }
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
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                Layout.preferredHeight: 64
                spacing: 32
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text { text: "Workspace"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Onde as novas conversas deste projeto começam. Substitui o padrão global e se aplica a cada checkout deste grupo."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); wrapMode: Text.WordWrap }
                }
                VrComboBox {
                    Layout.preferredWidth: 202
                    Layout.preferredHeight: 32
                    model: [{label: "Padrão (pasta atual)"}]
                    textRole: "label"
                    currentIndex: 0
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 68
                Layout.bottomMargin: 14
                Text {
                    Layout.fillWidth: true
                    text: "Checkout"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(17)
                    font.weight: Font.DemiBold
                }
                VrComboBox {
                    Layout.preferredWidth: 144
                    Layout.preferredHeight: 32
                    model: [{label: "LF"}]
                    textRole: "label"
                    currentIndex: 0
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 38
                radius: 8
                color: Theme.palette.surface
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 9
                    spacing: 8
                    Text {
                        objectName: "projectSettingsOpenFolder"
                        Layout.fillWidth: true
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
                    Text { text: control.threadLabel(); color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 18
                Layout.preferredHeight: 60
                spacing: 32
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text { text: "Agrupamento do projeto"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Define como esta pasta aparece nos grupos da barra lateral."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); wrapMode: Text.WordWrap }
                }
                VrComboBox {
                    Layout.preferredWidth: 222
                    Layout.preferredHeight: 32
                    model: [{label: "Padrão (por repositório)"}]
                    textRole: "label"
                    currentIndex: 0
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 49
                spacing: 32
                ColumnLayout {
                    Layout.preferredWidth: 520
                    spacing: 3
                    Text { text: "Ações"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { text: "Salvas e executadas apenas nesta pasta."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                }
                Item { Layout.fillWidth: true }
                VrButton {
                    Layout.preferredWidth: 136
                    implicitHeight: 26
                    text: "+ Adicionar"
                    variant: "secondary"
                    enabled: false
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 21
                text: "Nenhuma ação configurada para esta pasta."
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 62
                Layout.bottomMargin: 33
                text: "Perigo"
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(17)
                font.weight: Font.DemiBold
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 28
                spacing: 32
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text { text: "Remover projeto"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Remove a pasta da lista. Os arquivos no disco não são alterados."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); wrapMode: Text.WordWrap }
                }
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
                        Text { text: "Remover projeto"; color: Theme.palette.danger; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                    }
                    background: Rectangle {
                        radius: 8
                        color: parent.down || parent.hovered ? Qt.rgba(1, 0.18, 0.18, 0.08) : "transparent"
                        border.width: 1
                        border.color: Theme.palette.border
                    }
                }
            }
        }
    }
}
