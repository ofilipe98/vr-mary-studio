import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "vrUltraPage"

    property string selectionWarning: ""

    function toggleResearchModel(key) {
        var values = chat.researchModelKeys.slice()
        var current = values.indexOf(key)
        if (current >= 0) {
            values.splice(current, 1)
            selectionWarning = ""
        } else if (values.length < 3) {
            values.push(key)
            selectionWarning = ""
        } else {
            selectionWarning = "Selecione no máximo 3 modelos."
        }
        chat.setResearchModels(values)
    }

    function submitResearch() {
        var question = researchInput.text.trim()
        if (!question.length || chat.turnRunning) return
        chat.startUltraResearch(question)
        researchInput.clear()
    }

    Rectangle { anchors.fill: parent; color: frontend.palette.chatBackground }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        handle: Rectangle {
            implicitWidth: 5
            color: SplitHandle.hovered || SplitHandle.pressed
                ? frontend.palette.focus : frontend.palette.chatDivider
            opacity: SplitHandle.hovered || SplitHandle.pressed ? 0.75 : 0.4
        }

        Rectangle {
            objectName: "vrUltraNavigation"
            SplitView.minimumWidth: 220
            SplitView.preferredWidth: 260
            SplitView.maximumWidth: 430
            color: frontend.palette.navigationBackground

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                VrBrandHeader {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 62
                    primaryColor: frontend.palette.navText
                    toggleColor: frontend.palette.navMuted
                    onBrandActivated: frontend.setCurrentPage(1)
                }

                VrNavItem {
                    Layout.fillWidth: true
                    title: "Chat VR"
                    iconSource: frontend.navigationItems[1].icon
                    compact: false
                    onActivated: frontend.setCurrentPage(1)
                }
                VrNavItem {
                    Layout.fillWidth: true
                    title: "VR ULTRA"
                    iconSource: frontend.navigationItems[8].icon
                    selected: true
                    compact: false
                    onActivated: frontend.setCurrentPage(8)
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 7
                    Layout.rightMargin: 7
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    implicitHeight: 1
                    color: frontend.palette.navDivider
                }

                Repeater {
                    model: [
                        { title: "Dashboard", page: 0 },
                        { title: "Conhecimento", page: 2 },
                        { title: "Sincronizações", page: 3 },
                        { title: "Revisão", page: 4 },
                        { title: "Vídeos", page: 5 },
                        { title: "Logs", page: 6 }
                    ]
                    delegate: VrNavItem {
                        required property var modelData
                        Layout.fillWidth: true
                        title: modelData.title
                        iconSource: frontend.navigationItems[modelData.page].icon
                        compact: false
                        onActivated: frontend.setCurrentPage(modelData.page)
                    }
                }

                Item { Layout.fillHeight: true }

                VrIconButton {
                    Layout.alignment: Qt.AlignLeft
                    implicitWidth: 38
                    implicitHeight: 38
                    iconKind: "settings"
                    foreground: frontend.palette.navMuted
                    ToolTip.visible: hovered
                    ToolTip.text: "Configurações"
                    Accessible.name: "Abrir Configurações"
                    onClicked: frontend.setCurrentPage(7)
                }
            }
        }

        Item {
            SplitView.minimumWidth: 620
            SplitView.fillWidth: true

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 28
                anchors.rightMargin: 28
                anchors.topMargin: 24
                anchors.bottomMargin: 22
                spacing: 16

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Text {
                            text: "VR ULTRA"
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: 26
                            font.weight: Font.Bold
                        }
                        Text {
                            text: "Pesquisa multiagente com síntese em uma única resposta"
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: 13
                        }
                    }
                    Rectangle {
                        implicitWidth: statusRow.implicitWidth + 22
                        implicitHeight: 30
                        radius: 15
                        color: chat.turnRunning ? frontend.palette.accentSoft : frontend.palette.chatControl
                        Row {
                            id: statusRow
                            anchors.centerIn: parent
                            spacing: 7
                            Text {
                                text: chat.turnRunning ? "●" : "✦"
                                color: chat.turnRunning
                                    ? frontend.palette.brandOrange : frontend.palette.mutedText
                                font.pixelSize: 11
                            }
                            Text {
                                text: chat.turnRunning ? "Pesquisando" : "Pronto"
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 190
                    radius: 18
                    color: frontend.palette.chatComposer
                    border.width: researchInput.activeFocus ? 2 : 1
                    border.color: researchInput.activeFocus
                        ? frontend.palette.focus : frontend.palette.chatBorder

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8
                        VrTextArea {
                            id: researchInput
                            objectName: "vrUltraResearchInput"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            placeholderText: "Descreva o tema, a decisão ou o problema que os agentes devem investigar..."
                            readOnly: chat.turnRunning
                            background: Item { }
                            Keys.onPressed: event => {
                                if ((event.modifiers & Qt.ControlModifier)
                                        && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
                                    root.submitResearch()
                                    event.accepted = true
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Item {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                VrComboBox {
                                    id: ultraProjectSelector
                                    objectName: "vrUltraProjectSelector"
                                    anchors.fill: parent
                                    leftPadding: 31
                                    model: chat.projectItems
                                    textRole: "label"
                                    currentIndex: chat.currentProjectIndex
                                    onActivated: index => chat.setProject(index)
                                }
                                VrLineIcon {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 9
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 15; height: 15
                                    kind: "folder"
                                    foreground: frontend.palette.mutedText
                                }
                            }
                            VrButton {
                                objectName: "vrUltraSubmitButton"
                                text: chat.turnRunning ? "Pesquisando…" : "Iniciar pesquisa"
                                variant: "primary"
                                enabled: researchInput.text.trim().length > 0 && !chat.turnRunning
                                onClicked: root.submitResearch()
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 14

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumWidth: 360
                        radius: 14
                        color: frontend.palette.surface
                        border.width: 1
                        border.color: frontend.palette.border

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 10
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    Layout.fillWidth: true
                                    text: "Síntese"
                                    color: frontend.palette.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                }
                                VrButton {
                                    text: "Abrir no Chat VR"
                                    variant: "ghost"
                                    onClicked: frontend.setCurrentPage(1)
                                }
                            }
                            ListView {
                                id: ultraMessages
                                objectName: "vrUltraResults"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 10
                                model: chat.messages
                                delegate: Item {
                                    required property string role
                                    required property string displayContent
                                    width: ultraMessages.width
                                    visible: role === "assistant"
                                    height: visible ? resultText.implicitHeight + 18 : 0
                                    Text {
                                        id: resultText
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 9
                                        text: displayContent
                                        textFormat: Text.MarkdownText
                                        wrapMode: Text.WordWrap
                                        color: frontend.palette.text
                                        linkColor: frontend.palette.brandOrange
                                        font.family: Theme.fontFamily
                                        font.pixelSize: 13
                                    }
                                }
                                Text {
                                    anchors.centerIn: parent
                                    width: parent.width - 40
                                    visible: ultraMessages.count === 0
                                    text: "A síntese aparecerá aqui durante a pesquisa."
                                    color: frontend.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 12
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.preferredWidth: 310
                        Layout.fillHeight: true
                        radius: 14
                        color: frontend.palette.surface
                        border.width: 1
                        border.color: frontend.palette.border

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 10
                            Text {
                                text: "Equipe de pesquisa"
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Escolha até 3 modelos. Sem seleção, o VR escolhe automaticamente."
                                color: frontend.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            ScrollView {
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.min(190, modelColumn.implicitHeight)
                                clip: true
                                ColumnLayout {
                                    id: modelColumn
                                    width: parent.width
                                    spacing: 2
                                    Repeater {
                                        model: chat.researchModelItems
                                        delegate: VrCheckBox {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            text: modelData.label
                                            checked: chat.researchModelKeys.indexOf(modelData.key) >= 0
                                            onClicked: root.toggleResearchModel(modelData.key)
                                        }
                                    }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: root.selectionWarning.length > 0
                                text: root.selectionWarning
                                color: frontend.palette.warning
                                font.family: Theme.fontFamily
                                font.pixelSize: 10
                            }
                            Text {
                                text: "Agentes simultâneos"
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Repeater {
                                    model: [1, 2, 3]
                                    delegate: VrButton {
                                        required property int modelData
                                        Layout.fillWidth: true
                                        text: String(modelData)
                                        variant: chat.researchMaxParallel === modelData
                                            ? "secondary" : "ghost"
                                        onClicked: chat.setResearchMaxParallel(modelData)
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 1
                                color: frontend.palette.chatDivider
                            }
                            Text {
                                text: "Execução"
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                            ListView {
                                id: ultraAgentList
                                objectName: "vrUltraAgentList"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 5
                                model: chat.agentItems
                                delegate: Rectangle {
                                    required property var modelData
                                    width: ultraAgentList.width
                                    height: 56
                                    radius: 8
                                    color: frontend.palette.chatControl
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        spacing: 8
                                        Text {
                                            text: modelData.status === "concluído" ? "✓"
                                                : modelData.status === "falhou" ? "!" : "●"
                                            color: modelData.status === "concluído"
                                                ? frontend.palette.success
                                                : modelData.status === "falhou"
                                                    ? frontend.palette.danger
                                                    : frontend.palette.brandOrange
                                            font.pixelSize: 13
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 1
                                            Text { Layout.fillWidth: true; text: modelData.label; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight }
                                            Text { Layout.fillWidth: true; text: modelData.model + " · " + modelData.statusLabel; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: 9; elide: Text.ElideRight }
                                        }
                                    }
                                }
                                Text {
                                    anchors.centerIn: parent
                                    width: parent.width - 20
                                    visible: ultraAgentList.count === 0
                                    text: chat.turnRunning ? "Preparando agentes…" : "Nenhum agente em execução"
                                    color: frontend.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 10
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Component.onCompleted: chat.refreshModels()
}
