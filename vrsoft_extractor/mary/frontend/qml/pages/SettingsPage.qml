import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    property int tabIndex: 0
    property string pendingDeleteId: ""

    Rectangle { anchors.fill: parent; color: frontend.palette.background }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: 10

        VrPageHeader {
            Layout.fillWidth: true
            title: "Configurações"
            subtitle: "Provedores, aparência, projetos arquivados e preferências locais."
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Repeater {
                model: ["Geral", "Provedores", "Temas", "Projetos arquivados"]
                delegate: VrButton {
                    required property int index
                    required property string modelData
                    text: modelData
                    variant: root.tabIndex === index ? "primary" : "ghost"
                    onClicked: root.tabIndex = index
                }
            }
            Item { Layout.fillWidth: true }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.tabIndex

            Item {
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: Math.min(parent.height, 380)
                    anchors.margins: 4
                    radius: Theme.radiusCard
                    color: frontend.palette.surface
                    border.width: 1
                    border.color: frontend.palette.border
                    GridLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        columns: 3
                        rowSpacing: 7
                        columnSpacing: 7
                        Text { text: "Fonte de conhecimento VR"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                        VrTextField { id: rootField; Layout.fillWidth: true; text: studio.settingsValues.root || "" }
                        VrButton { text: "Procurar…"; onClicked: { var value = studio.chooseKnowledgeRoot(); if (value.length) rootField.text = value } }
                        Text { text: "Email Movidesk"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                        VrTextField { id: movideskEmail; Layout.fillWidth: true; Layout.columnSpan: 2; text: studio.settingsValues.movideskEmail || "" }
                        Text { text: "Senha Movidesk"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                        VrTextField { id: movideskPassword; Layout.fillWidth: true; Layout.columnSpan: 2; text: studio.settingsValues.movideskPassword || ""; echoMode: TextInput.Password }
                        Text { text: "Email Endoo"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                        VrTextField { id: endooEmail; Layout.fillWidth: true; Layout.columnSpan: 2; text: studio.settingsValues.endooEmail || "" }
                        Text { text: "Senha Endoo"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                        VrTextField { id: endooPassword; Layout.fillWidth: true; Layout.columnSpan: 2; text: studio.settingsValues.endooPassword || ""; echoMode: TextInput.Password }
                        Text { text: "Repetir sincronização"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                        VrComboBox {
                            id: interval
                            Layout.fillWidth: true
                            Layout.columnSpan: 2
                            model: ["A cada 15 minutos", "A cada 30 minutos", "A cada 1 hora", "A cada 2 horas", "A cada 4 horas", "A cada 8 horas", "A cada 24 horas"]
                            property var values: ["15", "30", "60", "120", "240", "480", "1440"]
                            Component.onCompleted: {
                                var found = values.indexOf(studio.settingsValues.interval || "120")
                                currentIndex = found >= 0 ? found : 3
                            }
                        }
                        Text { text: "Diagnóstico"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 13; Layout.alignment: Qt.AlignTop }
                        Text { Layout.fillWidth: true; Layout.columnSpan: 2; text: studio.settingsValues.diagnostic || ""; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap }
                        Item { }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.columnSpan: 2
                            VrButton { text: "Instalar OCR portátil por+eng"; onClicked: studio.runSync("ocr") }
                            VrButton { text: "Preparar/abrir projeto Codex"; onClicked: studio.openVrInCodex() }
                            Item { Layout.fillWidth: true }
                            VrButton {
                                text: "Salvar .env"
                                variant: "primary"
                                onClicked: studio.saveSettings(rootField.text, movideskEmail.text, movideskPassword.text, endooEmail.text, endooPassword.text, interval.values[interval.currentIndex])
                            }
                        }
                    }
                }
            }

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            Text { text: "Provedores"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.headingSize; font.weight: Font.DemiBold }
                            Text { text: "Ative os provedores disponíveis para novas conversas. O estado é verificado localmente."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
                        }
                        VrButton { text: "Atualizar"; onClicked: studio.refreshProviders() }
                    }
                    Repeater {
                        model: studio.providerItems
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 86
                            radius: Theme.radiusCard
                            color: frontend.palette.surface
                            border.width: 1
                            border.color: frontend.palette.border
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 14
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Text { text: modelData.name; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold }
                                    Text { text: modelData.description; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: 12 }
                                    Text { text: modelData.status; color: modelData.available && modelData.enabled ? frontend.palette.success : frontend.palette.warning; font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold }
                                }
                                VrCheckBox { text: "Ativo"; checked: modelData.enabled; onToggled: studio.setProviderEnabled(modelData.id, checked) }
                            }
                        }
                    }
                    Text { text: "Verificado agora · configurações aplicadas a novas conversas"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: 12 }
                    Item { Layout.fillHeight: true }
                }
            }

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 10
                    Text { text: "Aparência"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.headingSize; font.weight: Font.DemiBold }
                    Text { text: "Escolha o tema usado em todas as telas do VR Norte Studio."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 96
                        radius: Theme.radiusCard
                        color: frontend.palette.surface
                        border.width: 1
                        border.color: frontend.palette.border
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 14
                            ColumnLayout {
                                Layout.fillWidth: true
                                Text { text: "Tema"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                                Text { text: "A alteração é aplicada imediatamente e salva neste computador."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: 12 }
                            }
                            VrComboBox {
                                Layout.preferredWidth: 210
                                model: ["Claro", "Dark & Orange"]
                                currentIndex: frontend.themeId === "dark_orange" ? 1 : 0
                                onActivated: index => frontend.setTheme(index === 1 ? "dark_orange" : "light")
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 96
                        radius: Theme.radiusCard
                        color: frontend.palette.surface
                        border.width: 1
                        border.color: frontend.palette.border
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 14
                            ColumnLayout {
                                Layout.fillWidth: true
                                Text { text: "Movimento"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                                Text { text: "Evita pulsos e transições decorativas sem remover feedback de estado."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: 12 }
                            }
                            VrCheckBox { text: "Reduzir movimento"; checked: frontend.reduceMotion; onToggled: frontend.setReduceMotion(checked) }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 10
                    Text { text: "Projetos arquivados"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.headingSize; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Conversas arquivadas ficam separadas do Chat VR. Use o botão de excluir no item para removê-las definitivamente."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }
                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        VrTextField { id: archivedSearch; Layout.preferredWidth: 320; placeholderText: "Buscar projetos"; onTextChanged: archiveDelay.restart() }
                    }
                    ListView {
                        id: archivedList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 6
                        model: studio.archivedModel
                        delegate: Rectangle {
                            required property string conversationId
                            required property string title
                            required property string project
                            required property string provider
                            required property string updatedAt
                            width: archivedList.width
                            height: 66
                            radius: Theme.radiusControl
                            color: frontend.palette.surface
                            border.width: 1
                            border.color: frontend.palette.border
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Text { Layout.fillWidth: true; text: title; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold; elide: Text.ElideRight }
                                    Text { Layout.fillWidth: true; text: project + " · " + provider + " · " + updatedAt; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: 11; elide: Text.ElideRight }
                                }
                                VrButton { text: "Restaurar"; onClicked: studio.restoreArchived(conversationId) }
                                VrButton { text: "Excluir"; onClicked: { root.pendingDeleteId = conversationId; deleteDialog.open() } }
                            }
                        }
                        Text { anchors.centerIn: parent; visible: archivedList.count === 0; text: "Nenhum projeto arquivado."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
                    }
                }
            }
        }
    }

    Timer { id: archiveDelay; interval: 180; onTriggered: studio.refreshArchived(archivedSearch.text) }
    Dialog {
        id: deleteDialog
        anchors.centerIn: parent
        width: 460
        modal: true
        title: "Excluir conversa definitivamente?"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: 10
            Text { Layout.fillWidth: true; text: "A conversa, o histórico e o workspace local associado serão removidos. Esta ação não pode ser desfeita."; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }
            RowLayout {
                Layout.fillWidth: true
                VrButton { text: "Cancelar"; onClicked: deleteDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton {
                    text: "Excluir definitivamente"
                    variant: "primary"
                    onClicked: {
                        studio.purgeArchived(root.pendingDeleteId)
                        root.pendingDeleteId = ""
                        deleteDialog.close()
                    }
                }
            }
        }
        background: Rectangle { color: frontend.palette.surface; border.width: 1; border.color: frontend.palette.danger; radius: Theme.radiusPopup }
    }
}
