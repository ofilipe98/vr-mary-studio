import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "settingsPage"
    property int tabIndex: 0
    property string pendingDeleteId: ""

    Rectangle { anchors.fill: parent; color: frontend.palette.background }

    VrPageColumn {
        spacing: Theme.pageSpacing

        VrPageHeader {
            Layout.fillWidth: true
            title: "Configurações"
            subtitle: "Provedores, agentes VR Ultra, aparência e preferências locais."
        }

        VrTabBar {
            objectName: "settingsTabBar"
            Layout.fillWidth: true
            model: ["Geral", "Provedores", "VR Ultra", "Temas", "Projetos arquivados"]
            currentIndex: root.tabIndex
            onActivated: index => root.tabIndex = index
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.tabIndex

            // ------------------------------------------------------------ Geral
            Item {
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spaceXs
                    spacing: Theme.spaceSm

                    VrCard {
                        id: geralCard
                        Layout.fillWidth: true

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 3
                            rowSpacing: Theme.spaceSm
                            columnSpacing: Theme.spaceSm

                            Text { text: "Fonte de conhecimento VR"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
                            VrTextField {
                                id: rootField
                                Layout.fillWidth: true
                                Layout.minimumWidth: 140
                                text: studio.settingsValues.root || ""
                            }
                            VrButton { text: "Procurar…"; onClicked: { var value = studio.chooseKnowledgeRoot(); if (value.length) rootField.text = value } }

                            Text { text: "Email Movidesk"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
                            VrTextField { id: movideskEmail; Layout.fillWidth: true; Layout.minimumWidth: 140; Layout.columnSpan: 2; text: studio.settingsValues.movideskEmail || "" }
                            Text { text: "Senha Movidesk"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
                            VrTextField { id: movideskPassword; Layout.fillWidth: true; Layout.minimumWidth: 140; Layout.columnSpan: 2; text: ""; placeholderText: studio.settingsValues.movideskPasswordConfigured ? "Senha configurada — deixe vazio para manter" : "Informe a senha"; echoMode: TextInput.Password }
                            Text { text: "Email Endoo"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
                            VrTextField { id: endooEmail; Layout.fillWidth: true; Layout.minimumWidth: 140; Layout.columnSpan: 2; text: studio.settingsValues.endooEmail || "" }
                            Text { text: "Senha Endoo"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
                            VrTextField { id: endooPassword; Layout.fillWidth: true; Layout.minimumWidth: 140; Layout.columnSpan: 2; text: ""; placeholderText: studio.settingsValues.endooPasswordConfigured ? "Senha configurada — deixe vazio para manter" : "Informe a senha"; echoMode: TextInput.Password }

                            Text { text: "Repetir sincronização"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
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

                            Text { text: "Diagnóstico"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; Layout.alignment: Qt.AlignTop }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 100
                                Layout.columnSpan: 2
                                text: studio.settingsValues.diagnostic || ""
                                color: frontend.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.bodySize
                                wrapMode: Text.WordWrap
                            }

                            Flow {
                                Layout.fillWidth: true
                                Layout.columnSpan: 2
                                spacing: Theme.spaceSm

                                VrButton { text: "Instalar OCR portátil"; onClicked: studio.runSync("ocr") }
                                VrButton { text: "Abrir no Codex"; onClicked: studio.openVrInCodex() }
                                Item { Layout.fillWidth: true }
                                VrButton {
                                    text: "Salvar .env"
                                    variant: "primary"
                                    onClicked: studio.saveSettings(rootField.text, movideskEmail.text, movideskPassword.text, endooEmail.text, endooPassword.text, interval.values[interval.currentIndex])
                                }
                            }
                        }
                    }


                    Item { Layout.fillHeight: true }
                }
            }

            // -------------------------------------------------------- Provedores
            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spaceXs
                    spacing: Theme.spaceMd

                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            Text { text: "Provedores"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.headingSize; font.weight: Font.DemiBold }
                            Text { text: "Ative os provedores disponíveis para novas conversas. O estado é verificado localmente."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }
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
                                anchors.margins: Theme.spaceMd
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Text { text: modelData.name; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.subtitleSize; font.weight: Font.DemiBold }
                                    Text { text: modelData.description; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize }
                                    Text { text: modelData.status; color: modelData.available && modelData.enabled ? frontend.palette.success : frontend.palette.warning; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; font.weight: Font.DemiBold }
                                }
                                VrCheckBox { text: "Ativo"; checked: modelData.enabled; onToggled: studio.setProviderEnabled(modelData.id, checked) }
                            }
                        }
                    }
                    Text { text: "Verificado agora · configurações aplicadas a novas conversas"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize }
                    Item { Layout.fillHeight: true }
                }
            }

            // --------------------------------------------------------- VR Ultra
            VRUltraSettingsPage { }

            // ------------------------------------------------------------ Temas
            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spaceXs
                    spacing: Theme.spaceMd
                    Text { text: "Aparência"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.headingSize; font.weight: Font.DemiBold }
                    Text { text: "Escolha o tema usado em todas as telas do VR Norte Studio."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 96
                        radius: Theme.radiusCard
                        color: frontend.palette.surface
                        border.width: 1
                        border.color: frontend.palette.border
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: Theme.spaceMd
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text { text: "Tema"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold }
                                Text { text: "A alteração é aplicada imediatamente e salva neste computador."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; wrapMode: Text.WordWrap }
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
                            anchors.margins: Theme.spaceMd
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text { text: "Movimento"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold }
                                Text { text: "Evita pulsos e transições decorativas sem remover feedback de estado."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; wrapMode: Text.WordWrap }
                            }
                            VrCheckBox { text: "Reduzir movimento"; checked: frontend.reduceMotion; onToggled: frontend.setReduceMotion(checked) }
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
                            anchors.margins: Theme.spaceMd
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text { objectName: "uiScalePreviewText"; text: "Escala da interface"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold }
                                Text {
                                    objectName: "uiScaleDescription"
                                    text: frontend.uiScale === "auto"
                                        ? "Automática ativa: " + Theme.automaticScalePercent + "%. Acompanha a janela sem alterar painéis e controles."
                                        : "Ajusta a tipografia imediatamente, sem alterar as proporções de painéis e controles."
                                    color: frontend.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.captionSize
                                    wrapMode: Text.WordWrap
                                }
                            }
                            VrComboBox {
                                id: uiScaleCombo
                                objectName: "uiScaleCombo"
                                Layout.preferredWidth: 210
                                model: ["Automática", "100%", "105%", "110%", "125%", "150%"]
                                property var values: ["auto", "100", "105", "110", "125", "150"]
                                currentIndex: Math.max(0, values.indexOf(frontend.uiScale))
                                onActivated: index => frontend.setUiScale(values[index])
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            // ------------------------------------------------ Projetos arquivados
            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spaceXs
                    spacing: Theme.spaceMd
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
                        spacing: Theme.spaceXs
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
                                anchors.margins: Theme.spaceSm
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text { Layout.fillWidth: true; text: title; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold; elide: Text.ElideRight }
                                    Text { Layout.fillWidth: true; text: project + " · " + provider + " · " + updatedAt; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; elide: Text.ElideRight }
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
        onAboutToShow: deleteConfirmField.text = ""
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text { Layout.fillWidth: true; text: "A conversa, o histórico e o workspace local associado serão removidos. Esta ação não pode ser desfeita."; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }
            Text { Layout.fillWidth: true; text: "Digite EXCLUIR para confirmar."; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold }
            VrTextField { id: deleteConfirmField; Layout.fillWidth: true; placeholderText: "EXCLUIR" }
            RowLayout {
                Layout.fillWidth: true
                VrButton { text: "Cancelar"; onClicked: deleteDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton {
                    text: "Excluir definitivamente"
                    variant: "danger"
                    enabled: deleteConfirmField.text === "EXCLUIR"
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
