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

    function openSearchResult(index) {
        root.tabIndex = Math.max(0, Math.min(5, Number(index)))
    }

    function applyTypography() {
        frontend.setTypography(
            interfaceFontCombo.currentText,
            Number(interfaceFontSizeCombo.currentText.replace(" px", "")),
            monospaceFontCombo.currentText,
            Number(monospaceFontSizeCombo.currentText.replace(" px", "")),
            wordWrapSwitch.checked)
    }

    Rectangle { anchors.fill: parent; color: frontend.palette.chatBackground }

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
            model: ["Geral", "Provedores", "VR Ultra", "Aparência", "Browser", "Projetos arquivados"]
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
                        flat: true

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

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: providerList.implicitHeight
                        color: "transparent"

                        ColumnLayout {
                            id: providerList
                            anchors.left: parent.left
                            anchors.right: parent.right
                            spacing: 0

                            Repeater {
                                model: studio.providerItems
                                delegate: Item {
                                    required property int index
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 76

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 10
                                        spacing: 12
                                        VrProviderIcon {
                                            Layout.preferredWidth: 24
                                            Layout.preferredHeight: 24
                                            provider: modelData.id
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 2
                                            Text { text: modelData.name; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.subtitleSize; font.weight: Font.DemiBold }
                                            Text { text: modelData.description; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; elide: Text.ElideRight; Layout.fillWidth: true }
                                            Text { text: String(modelData.status || "").replace(/^●\s*/, ""); color: modelData.available && modelData.enabled ? frontend.palette.success : frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize }
                                        }
                                        VrSwitch {
                                            checked: modelData.enabled
                                            Accessible.name: "Ativar " + modelData.name
                                            onToggled: studio.setProviderEnabled(modelData.id, checked)
                                        }
                                    }

                                    Rectangle {
                                        visible: index < studio.providerItems.length - 1
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.bottom: parent.bottom
                                        anchors.leftMargin: 46
                                        height: 1
                                        color: frontend.palette.chatDivider
                                    }
                                }
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
                Flickable {
                    anchors.fill: parent
                    clip: true
                    contentWidth: width
                    contentHeight: appearanceContent.implicitHeight + Theme.spaceLg
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                ColumnLayout {
                    id: appearanceContent
                    width: parent.width - Theme.spaceSm
                    x: Theme.spaceXs
                    spacing: Theme.spaceMd
                    Text { text: "Aparência"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.headingSize; font.weight: Font.DemiBold }
                    Text { text: "Tema, movimento e tipografia usados em todas as telas do VR Norte Studio."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 96
                        color: "transparent"
                        border.width: 0
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
                        color: "transparent"
                        border.width: 0
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
                        color: "transparent"
                        border.width: 0
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
                                model: ["Automática", "100%", "101%", "102%", "103%", "104%", "105%", "110%", "125%", "150%"]
                                property var values: ["auto", "100", "101", "102", "103", "104", "105", "110", "125", "150"]
                                currentIndex: Math.max(0, values.indexOf(frontend.uiScale))
                                onActivated: index => frontend.setUiScale(values[index])
                            }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: frontend.palette.chatDivider }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Tipografia"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.headingSize; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        Text { text: "Aplicada imediatamente"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize }
                    }
                    Text { Layout.fillWidth: true; text: "Ajuste separadamente a leitura da interface e de código, com uma prévia real abaixo."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }
                    RowLayout {
                        Layout.fillWidth: true; spacing: Theme.spaceSm
                        ColumnLayout {
                            Layout.fillWidth: true
                            Text { text: "Fonte da interface"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold }
                            Text { text: "Mensagens, menus e áreas fora de blocos de código."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize }
                        }
                        VrComboBox { id: interfaceFontCombo; objectName: "interfaceFontCombo"; Layout.preferredWidth: 190; model: ["Segoe UI", "Arial", "Inter", "Tahoma"]; currentIndex: Math.max(0, model.indexOf(frontend.interfaceFontFamily)); onActivated: root.applyTypography() }
                        VrComboBox { id: interfaceFontSizeCombo; objectName: "interfaceFontSizeCombo"; Layout.preferredWidth: 112; model: ["12 px", "13 px", "14 px", "15 px", "16 px", "18 px", "20 px", "22 px"]; currentIndex: Math.max(0, model.indexOf(frontend.interfaceFontSize + " px")); onActivated: root.applyTypography() }
                    }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 58; radius: Theme.radiusControl
                        color: frontend.palette.chatComposer; border.width: 1; border.color: frontend.palette.chatBorder
                        Text { anchors.fill: parent; anchors.margins: 12; text: "Prévia da interface — converse, pesquise e revise com conforto."; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; verticalAlignment: Text.AlignVCenter }
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: Theme.spaceSm
                        ColumnLayout {
                            Layout.fillWidth: true
                            Text { text: "Fonte monoespaçada"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold }
                            Text { text: "Blocos de código, caminhos, diffs e terminal."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize }
                        }
                        VrComboBox { id: monospaceFontCombo; objectName: "monospaceFontCombo"; Layout.preferredWidth: 190; model: ["Consolas", "Cascadia Code", "Courier New"]; currentIndex: Math.max(0, model.indexOf(frontend.monospaceFontFamily)); onActivated: root.applyTypography() }
                        VrComboBox { id: monospaceFontSizeCombo; objectName: "monospaceFontSizeCombo"; Layout.preferredWidth: 112; model: ["10 px", "11 px", "12 px", "13 px", "14 px", "16 px", "18 px", "20 px"]; currentIndex: Math.max(0, model.indexOf(frontend.monospaceFontSize + " px")); onActivated: root.applyTypography() }
                    }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 76; radius: Theme.radiusControl
                        color: frontend.themeId === "dark_orange" ? "#111113" : "#F4F4F6"; border.width: 1; border.color: frontend.palette.chatBorder
                        Text { anchors.fill: parent; anchors.margins: 12; text: "const contexto = provider.contextWindow\nreturn contexto ?? ocultarIcone()"; color: frontend.palette.text; font.family: Theme.monospaceFontFamily; font.pixelSize: Theme.monospaceFontSize(12); wrapMode: frontend.wordWrap ? Text.Wrap : Text.NoWrap }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            Text { text: "Quebra automática de linha"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold }
                            Text { text: "Quebra linhas longas em código e prévias por padrão."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize }
                        }
                        VrSwitch { id: wordWrapSwitch; objectName: "wordWrapSwitch"; checked: frontend.wordWrap; onToggled: root.applyTypography() }
                    }
                }
                }
            }

            // ----------------------------------------------------------- Browser
            Item {
                Flickable {
                    anchors.fill: parent
                    clip: true
                    contentWidth: width
                    contentHeight: browserContent.implicitHeight + Theme.spaceLg
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    ColumnLayout {
                        id: browserContent
                        width: parent.width - Theme.spaceSm
                        x: Theme.spaceXs
                        spacing: 0
                        Text { Layout.bottomMargin: Theme.spaceLg; text: "Browser"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.headingSize; font.weight: Font.DemiBold }
                        RowLayout {
                            Layout.fillWidth: true; Layout.preferredHeight: 82
                            ColumnLayout { Layout.fillWidth: true; Text { text: "Acesso do agente ao browser"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold } Text { Layout.fillWidth: true; text: "Permite que agentes abram e controlem a superfície Browser durante uma sessão."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; wrapMode: Text.WordWrap } }
                            VrSwitch { objectName: "browserAgentAccessSwitch"; checked: frontend.browserAgentAccess; onToggled: frontend.setBrowserAgentAccess(checked) }
                        }
                        RowLayout {
                            Layout.fillWidth: true; Layout.preferredHeight: 82
                            ColumnLayout { Layout.fillWidth: true; Text { text: "Viewport padrão"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold } Text { text: "Define o tamanho inicial usado em novas superfícies do browser."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize } }
                            VrComboBox { objectName: "browserViewportCombo"; Layout.preferredWidth: 210; model: ["Preencher painel", "Desktop 1280 × 720", "Desktop 1440 × 900", "Mobile 390 × 844"]; property var values: ["fill", "1280x720", "1440x900", "390x844"]; currentIndex: Math.max(0, values.indexOf(frontend.browserViewport)); onActivated: index => frontend.setBrowserViewport(values[index]) }
                        }
                        RowLayout {
                            Layout.fillWidth: true; Layout.preferredHeight: 82
                            ColumnLayout { Layout.fillWidth: true; Text { text: "Zoom padrão"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold } Text { text: "Zoom aplicado a novas abas do browser."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize } }
                            VrComboBox { objectName: "browserZoomCombo"; Layout.preferredWidth: 210; model: ["75%", "90%", "100%", "110%", "125%", "150%"]; property var values: ["75", "90", "100", "110", "125", "150"]; currentIndex: Math.max(0, values.indexOf(frontend.browserZoom)); onActivated: index => frontend.setBrowserZoom(values[index]) }
                        }
                        RowLayout {
                            Layout.fillWidth: true; Layout.preferredHeight: 82
                            ColumnLayout { Layout.fillWidth: true; Text { text: "Aparência padrão"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold } Text { text: "Preferência de cores para páginas compatíveis; Sistema acompanha o aplicativo."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize } }
                            VrComboBox { objectName: "browserAppearanceCombo"; Layout.preferredWidth: 210; model: ["Sistema", "Claro", "Escuro"]; property var values: ["system", "light", "dark"]; currentIndex: Math.max(0, values.indexOf(frontend.browserAppearance)); onActivated: index => frontend.setBrowserAppearance(values[index]) }
                        }
                        RowLayout {
                            Layout.fillWidth: true; Layout.preferredHeight: 82
                            ColumnLayout { Layout.fillWidth: true; Text { text: "Mostrar preview automaticamente"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; font.weight: Font.DemiBold } Text { Layout.fillWidth: true; text: "Expande o Browser quando uma navegação é iniciada pelo agente."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; wrapMode: Text.WordWrap } }
                            VrSwitch { objectName: "browserAutoShowSwitch"; checked: frontend.browserAutoShowPreview; onToggled: frontend.setBrowserAutoShowPreview(checked) }
                        }
                    }
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
                            radius: 0
                            color: index % 2 ? frontend.palette.chatSidebar : "transparent"
                            border.width: 0
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
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text { Layout.fillWidth: true; text: "A conversa, o histórico e o workspace local associado serão removidos. Esta ação não pode ser desfeita."; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }
            RowLayout {
                Layout.fillWidth: true
                VrButton { text: "Cancelar"; onClicked: deleteDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton {
                    text: "Excluir definitivamente"
                    variant: "danger"
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
