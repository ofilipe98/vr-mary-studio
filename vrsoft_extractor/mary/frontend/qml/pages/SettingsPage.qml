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
    property bool vrUltraVisited: false
    property bool providersVisited: false
    property bool skillsVisited: false
    onTabIndexChanged: {
        if (tabIndex === 1) providersVisited = true
        if (tabIndex === 2) vrUltraVisited = true
        if (tabIndex === 6) skillsVisited = true
    }

    function openSearchResult(index) {
        root.tabIndex = Math.max(0, Math.min(6, Number(index)))
    }

    function applyTypography() {
        frontend.setTypography(
            interfaceFontCombo.currentText,
            Number(interfaceFontSizeCombo.currentText.replace(" px", "")),
            monospaceFontCombo.currentText,
            Number(monospaceFontSizeCombo.currentText.replace(" px", "")),
            wordWrapSwitch.checked)
    }

    Rectangle { anchors.fill: parent; color: Theme.palette.chatBackground }

    VrIconButton {
        objectName: "settingsCompactReturn"
        z: 2
        visible: root.width < 980
        anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: Theme.pageMargin
        iconKind: "back"
        Accessible.name: "Retornar ao Chat VR"
        ToolTip.text: Accessible.name; ToolTip.visible: hovered || activeFocus
        onClicked: frontend.setCurrentPage(1)
    }

    VrPageColumn {
        spacing: Theme.pageSpacing
        maximumWidth: 1200

        VrPageHeader {
            compact: true
            Layout.minimumWidth: 0
            Layout.fillWidth: true
            title: "Configurações"
            subtitle: "Provedores, agentes VR Ultra, aparência e preferências locais."
        }

        VrTabBar {
            understated: true
            Layout.minimumWidth: 0
            objectName: "settingsTabBar"
            Layout.fillWidth: true
            model: ["Geral", "Provedores", "VR Ultra", "Aparência", "Browser", "Projetos arquivados", "Skills"]
            currentIndex: root.tabIndex
            onActivated: index => root.tabIndex = index
        }

        StackLayout {
            Layout.minimumWidth: 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.tabIndex

            // ------------------------------------------------------------ Geral
            ScrollView {
                id: generalScroll
                objectName: "generalScroll"
                clip: true
                contentWidth: availableWidth
                topPadding: 4
                rightPadding: 12
                bottomPadding: 20
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                ColumnLayout {
                    width: generalScroll.availableWidth
                    spacing: 16


                    // Header
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 36
                            radius: Theme.radiusSmall
                            color: Theme.palette.codeSurface
                            border.width: 1
                            border.color: Theme.palette.chatBorder

                            VrLineIcon {
                                anchors.centerIn: parent
                                width: 18
                                height: 18
                                kind: "folder"
                                foreground: Theme.palette.brandOrange
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Configurações Gerais"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(16)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Repositório local de conhecimento, credenciais de sincronização e diagnóstico."
                                color: Theme.palette.subtleText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    // Section 1: Base de conhecimento
                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Base de conhecimento"
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Diretório local com a documentação do ecossistema VR. O Chat VR e os agentes consultam esta pasta para fundamentar respostas."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 8

                        VrTextField {
                            id: rootField
                            objectName: "rootField"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 140
                            implicitHeight: 38
                            text: studio.settingsValues.root || ""
                            placeholderText: "Caminho da pasta do repositório VR..."
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: rootField.activeFocus ? 2 : 1
                                border.color: rootField.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }

                        VrProviderAction {
                            text: "Procurar…"
                            variant: "secondary"
                            onClicked: {
                                var value = studio.chooseKnowledgeRoot()
                                if (value.length) rootField.text = value
                            }
                        }
                    }

                    // Section 2: Credenciais de sincronização
                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Credenciais de sincronização"
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Credenciais de acesso para baixar automaticamente chamados, bases de conhecimento e documentações técnicas da Movidesk e Wiki Endoo."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    // Movidesk card
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: movideskContent.implicitHeight + 28
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        ColumnLayout {
                            id: movideskContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 12

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Text {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: "Movidesk"
                                    color: Theme.palette.headingText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(13)
                                    font.weight: Font.DemiBold
                                    wrapMode: Text.WordWrap
                                }
                                VrProviderStatus {
                                    text: studio.settingsValues.movideskPasswordConfigured ? "Senha configurada" : "Pendente"
                                    tone: studio.settingsValues.movideskPasswordConfigured ? "success" : "muted"
                                }
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                columns: root.width < 680 ? 1 : 2
                                columnSpacing: 12
                                rowSpacing: 8

                                VrTextField {
                                    id: movideskEmail
                                    objectName: "movideskEmail"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitHeight: 38
                                    placeholderText: "Email Movidesk"
                                    text: studio.settingsValues.movideskEmail || ""
                                    background: Rectangle {
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: movideskEmail.activeFocus ? 2 : 1
                                        border.color: movideskEmail.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                    }
                                }

                                VrTextField {
                                    id: movideskPassword
                                    objectName: "movideskPassword"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitHeight: 38
                                    placeholderText: studio.settingsValues.movideskPasswordConfigured ? "Senha configurada — deixe vazio para manter" : "Senha Movidesk"
                                    text: ""
                                    echoMode: TextInput.Password
                                    background: Rectangle {
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: movideskPassword.activeFocus ? 2 : 1
                                        border.color: movideskPassword.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                    }
                                }
                            }
                        }
                    }

                    // Endoo card
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: endooContent.implicitHeight + 28
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        ColumnLayout {
                            id: endooContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 12

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Text {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: "Wiki Endoo"
                                    color: Theme.palette.headingText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(13)
                                    font.weight: Font.DemiBold
                                    wrapMode: Text.WordWrap
                                }
                                VrProviderStatus {
                                    text: studio.settingsValues.endooPasswordConfigured ? "Senha configurada" : "Pendente"
                                    tone: studio.settingsValues.endooPasswordConfigured ? "success" : "muted"
                                }
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                columns: root.width < 680 ? 1 : 2
                                columnSpacing: 12
                                rowSpacing: 8

                                VrTextField {
                                    id: endooEmail
                                    objectName: "endooEmail"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitHeight: 38
                                    placeholderText: "Email Endoo"
                                    text: studio.settingsValues.endooEmail || ""
                                    background: Rectangle {
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: endooEmail.activeFocus ? 2 : 1
                                        border.color: endooEmail.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                    }
                                }

                                VrTextField {
                                    id: endooPassword
                                    objectName: "endooPassword"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitHeight: 38
                                    placeholderText: studio.settingsValues.endooPasswordConfigured ? "Senha configurada — deixe vazio para manter" : "Senha Endoo"
                                    text: ""
                                    echoMode: TextInput.Password
                                    background: Rectangle {
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: endooPassword.activeFocus ? 2 : 1
                                        border.color: endooPassword.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                    }
                                }
                            }
                        }
                    }

                    // Section 3: Sincronização e diagnóstico
                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Sincronização e diagnóstico"
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Repetir sincronização"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Frequência para sincronização de chamados e bases em segundo plano."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            id: interval
                            Layout.preferredWidth: 210
                            implicitHeight: 38
                            model: ["A cada 15 minutos", "A cada 30 minutos", "A cada 1 hora", "A cada 2 horas", "A cada 4 horas", "A cada 8 horas", "A cada 24 horas"]
                            property var values: ["15", "30", "60", "120", "240", "480", "1440"]
                            Component.onCompleted: {
                                var found = values.indexOf(studio.settingsValues.interval || "120")
                                currentIndex = found >= 0 ? found : 3
                            }
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: interval.activeFocus ? 2 : 1
                                border.color: interval.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 6

                        Text {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: "Diagnóstico local"
                            color: Theme.palette.headingText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                            wrapMode: Text.WordWrap
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: Math.max(44, diagnosticText.implicitHeight + 20)
                            radius: Theme.radiusSmall
                            color: Theme.palette.codeSurface
                            border.width: 1
                            border.color: Theme.palette.chatBorder

                            Text {
                                id: diagnosticText
                                anchors.fill: parent
                                anchors.margins: 10
                                text: studio.settingsValues.diagnostic || "Ambiente pronto e sem inconsistências reportadas."
                                color: Theme.palette.mutedText
                                font.family: Theme.monospaceFontFamily
                                font.pixelSize: Theme.monospaceFontSize(12)
                                wrapMode: Text.WordWrap
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }

                    // Section 4: Ações
                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Ações do sistema"
                    }

                    GridLayout {
                        id: systemActions
                        objectName: "systemActions"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        readonly property bool compact: generalScroll.availableWidth < 520
                        columns: compact ? 1 : 4
                        columnSpacing: 8
                        rowSpacing: 8

                        VrProviderAction {
                            objectName: "installOcrAction"
                            text: "Instalar OCR portátil"
                            variant: "secondary"
                            onClicked: studio.runSync("ocr")
                        }

                        VrProviderAction {
                            objectName: "openCodexAction"
                            text: "Abrir no Codex"
                            variant: "secondary"
                            onClicked: studio.openVrInCodex()
                        }

                        VrButton {
                            objectName: "saveSettingsAction"
                            Layout.alignment: Qt.AlignLeft
                            text: "Salvar .env"
                            variant: "primary"
                            implicitHeight: 34
                            onClicked: studio.saveSettings(rootField.text, movideskEmail.text, movideskPassword.text, endooEmail.text, endooPassword.text, interval.values[interval.currentIndex])
                        }

                        Item {
                            visible: !systemActions.compact
                            Layout.fillWidth: true
                        }
                    }

                    Item { Layout.preferredHeight: 16 }
                }
            }

            // -------------------------------------------------------- Provedores
            Loader {
                id: providerSettingsLoader
                objectName: "providerSettingsLoader"
                active: root.tabIndex === 1 || root.providersVisited
                asynchronous: root.tabIndex !== 1
                sourceComponent: Component { VrProviderSettings { } }
            }

            // --------------------------------------------------------- VR Ultra
            Loader {
                id: vrUltraSettingsLoader
                objectName: "vrUltraSettingsLoader"
                active: root.tabIndex === 2 || root.vrUltraVisited
                visible: root.tabIndex === 2
                // Finish an explicit navigation immediately. Preload remains asynchronous: true.
                asynchronous: root.tabIndex !== 2
                sourceComponent: vrUltraSettingsComponent
            }

            // ------------------------------------------------------------ Temas
            ScrollView {
                id: appearanceScroll
                objectName: "appearanceSettingsScroll"
                clip: true
                contentWidth: availableWidth
                topPadding: 4
                rightPadding: 12
                bottomPadding: 20
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                ColumnLayout {
                    width: appearanceScroll.availableWidth
                    spacing: 16


                    // Header
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 36
                            radius: Theme.radiusSmall
                            color: Theme.palette.codeSurface
                            border.width: 1
                            border.color: Theme.palette.chatBorder

                            VrLineIcon {
                                anchors.centerIn: parent
                                width: 18
                                height: 18
                                kind: "settings"
                                foreground: Theme.palette.brandOrange
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Aparência e Tipografia"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(16)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Tema visual, movimento e tipografia aplicados a todas as superfícies."
                                color: Theme.palette.subtleText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    // Section 1: Tema e Interface
                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Tema e Interface"
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Tema"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "A alteração é aplicada imediatamente e salva neste computador."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            Layout.preferredWidth: 210
                            implicitHeight: 38
                            model: ["Claro", "Dark & Orange"]
                            currentIndex: frontend.themeId === "dark_orange" ? 1 : 0
                            onActivated: index => frontend.setTheme(index === 1 ? "dark_orange" : "light")
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: parent.activeFocus ? 2 : 1
                                border.color: parent.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Reduzir movimento"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Evita pulsos e transições decorativas sem remover feedback de estado."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            text: "Reduzir movimento"
                            checked: frontend.reduceMotion
                            onToggled: frontend.setReduceMotion(checked)
                        }
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                objectName: "uiScalePreviewText"
                                text: "Escala da interface"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                objectName: "uiScaleDescription"
                                text: frontend.uiScale === "auto"
                                    ? "Automática ativa: " + Theme.automaticScalePercent + "%. Acompanha a janela sem alterar painéis e controles."
                                    : "Ajusta a tipografia imediatamente, sem alterar as proporções de painéis e controles."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            id: uiScaleCombo
                            objectName: "uiScaleCombo"
                            Layout.preferredWidth: 210
                            implicitHeight: 38
                            model: ["Automática", "100%", "101%", "102%", "103%", "104%", "105%", "110%", "125%", "150%"]
                            property var values: ["auto", "100", "101", "102", "103", "104", "105", "110", "125", "150"]
                            currentIndex: Math.max(0, values.indexOf(frontend.uiScale))
                            onActivated: index => frontend.setUiScale(values[index])
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: uiScaleCombo.activeFocus ? 2 : 1
                                border.color: uiScaleCombo.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }
                    }

                    // Section 2: Tipografia
                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Tipografia"
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Ajuste separadamente a leitura da interface e de código, com prévia em tempo real."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Fonte da interface"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Mensagens, menus e áreas fora de blocos de código."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        RowLayout {
                            Layout.alignment: Qt.AlignRight
                            spacing: 8

                            VrComboBox {
                                id: interfaceFontCombo
                                objectName: "interfaceFontCombo"
                                Layout.preferredWidth: 160
                                implicitHeight: 38
                                model: ["Segoe UI", "Arial", "Inter", "Tahoma"]
                                currentIndex: Math.max(0, model.indexOf(frontend.interfaceFontFamily))
                                onActivated: root.applyTypography()
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: interfaceFontCombo.activeFocus ? 2 : 1
                                    border.color: interfaceFontCombo.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }

                            VrComboBox {
                                id: interfaceFontSizeCombo
                                objectName: "interfaceFontSizeCombo"
                                Layout.preferredWidth: 100
                                implicitHeight: 38
                                model: ["12 px", "13 px", "14 px", "15 px", "16 px", "18 px", "20 px", "22 px"]
                                currentIndex: Math.max(0, model.indexOf(frontend.interfaceFontSize + " px"))
                                onActivated: root.applyTypography()
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: interfaceFontSizeCombo.activeFocus ? 2 : 1
                                    border.color: interfaceFontSizeCombo.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: Math.max(52, interfacePreview.implicitHeight + 24)
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        Text {
                            anchors.fill: parent
                            anchors.margins: 12
                            id: interfacePreview
                            wrapMode: Text.WordWrap
                            text: "Prévia da interface — converse, pesquise e revise com conforto."
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Fonte monoespaçada"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Blocos de código, caminhos, diffs e terminal."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        RowLayout {
                            Layout.alignment: Qt.AlignRight
                            spacing: 8

                            VrComboBox {
                                id: monospaceFontCombo
                                objectName: "monospaceFontCombo"
                                Layout.preferredWidth: 160
                                implicitHeight: 38
                                model: ["Consolas", "Cascadia Code", "Courier New"]
                                currentIndex: Math.max(0, model.indexOf(frontend.monospaceFontFamily))
                                onActivated: root.applyTypography()
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: monospaceFontCombo.activeFocus ? 2 : 1
                                    border.color: monospaceFontCombo.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }

                            VrComboBox {
                                id: monospaceFontSizeCombo
                                objectName: "monospaceFontSizeCombo"
                                Layout.preferredWidth: 100
                                implicitHeight: 38
                                model: ["10 px", "11 px", "12 px", "13 px", "14 px", "16 px", "18 px", "20 px"]
                                currentIndex: Math.max(0, model.indexOf(frontend.monospaceFontSize + " px"))
                                onActivated: root.applyTypography()
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: monospaceFontSizeCombo.activeFocus ? 2 : 1
                                    border.color: monospaceFontSizeCombo.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: Math.max(68, codePreview.implicitHeight + 24)
                        radius: Theme.radiusSmall
                        color: frontend.themeId === "dark_orange" ? "#111113" : "#F4F4F6"
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        Text {
                            anchors.fill: parent
                            anchors.margins: 12
                            id: codePreview
                            clip: true
                            text: "const contexto = provider.contextWindow\nreturn contexto ?? ocultarIcone()"
                            color: Theme.palette.text
                            font.family: Theme.monospaceFontFamily
                            font.pixelSize: Theme.monospaceFontSize(12)
                            wrapMode: frontend.wordWrap ? Text.Wrap : Text.NoWrap
                        }
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Quebra automática de linha"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Quebra linhas longas em código e prévias por padrão."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            id: wordWrapSwitch
                            objectName: "wordWrapSwitch"
                            Accessible.name: "Quebra automática de linha"
                            checked: frontend.wordWrap
                            onToggled: root.applyTypography()
                        }
                    }

                    Item { Layout.preferredHeight: 16 }
                }
            }

            // ----------------------------------------------------------- Browser
            ScrollView {
                id: browserScroll
                objectName: "browserSettingsScroll"
                clip: true
                contentWidth: availableWidth
                topPadding: 4
                rightPadding: 12
                bottomPadding: 20
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                ColumnLayout {
                    width: browserScroll.availableWidth
                    spacing: 16


                    // Header
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 36
                            radius: Theme.radiusSmall
                            color: Theme.palette.codeSurface
                            border.width: 1
                            border.color: Theme.palette.chatBorder

                            VrLineIcon {
                                anchors.centerIn: parent
                                width: 18
                                height: 18
                                kind: "browser"
                                foreground: Theme.palette.brandOrange
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Superfície Browser"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(16)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Integração do agente com a navegação web e preferências visuais de tela."
                                color: Theme.palette.subtleText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    // Section 1: Automação e agente
                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Integração com o Agente"
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Acesso do agente ao browser"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Permite que agentes abram e controlem a superfície Browser durante uma sessão."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            objectName: "browserAgentAccessSwitch"
                            Accessible.name: "Acesso do agente ao browser"
                            checked: frontend.browserAgentAccess
                            onToggled: frontend.setBrowserAgentAccess(checked)
                        }
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Mostrar preview automaticamente"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Expande o painel do Browser quando uma navegação é iniciada pelo agente."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            objectName: "browserAutoShowSwitch"
                            Accessible.name: "Mostrar preview automaticamente"
                            checked: frontend.browserAutoShowPreview
                            onToggled: frontend.setBrowserAutoShowPreview(checked)
                        }
                    }

                    // Section 2: Visualização e dimensões
                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Visualização e Dimensões"
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Viewport padrão"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Define o tamanho inicial usado em novas superfícies do browser."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            objectName: "browserViewportCombo"
                            Layout.preferredWidth: 210
                            implicitHeight: 38
                            model: ["Preencher painel", "Desktop 1280 × 720", "Desktop 1440 × 900", "Mobile 390 × 844"]
                            property var values: ["fill", "1280x720", "1440x900", "390x844"]
                            currentIndex: Math.max(0, values.indexOf(frontend.browserViewport))
                            onActivated: index => frontend.setBrowserViewport(values[index])
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: parent.activeFocus ? 2 : 1
                                border.color: parent.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Zoom padrão"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Zoom aplicado a novas abas do browser."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            objectName: "browserZoomCombo"
                            Layout.preferredWidth: 210
                            implicitHeight: 38
                            model: ["75%", "90%", "100%", "110%", "125%", "150%"]
                            property var values: ["75", "90", "100", "110", "125", "150"]
                            currentIndex: Math.max(0, values.indexOf(frontend.browserZoom))
                            onActivated: index => frontend.setBrowserZoom(values[index])
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: parent.activeFocus ? 2 : 1
                                border.color: parent.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Aparência padrão"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Preferência de cores para páginas compatíveis; Sistema acompanha o aplicativo."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            objectName: "browserAppearanceCombo"
                            Layout.preferredWidth: 210
                            implicitHeight: 38
                            model: ["Sistema", "Claro", "Escuro"]
                            property var values: ["system", "light", "dark"]
                            currentIndex: Math.max(0, values.indexOf(frontend.browserAppearance))
                            onActivated: index => frontend.setBrowserAppearance(values[index])
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: parent.activeFocus ? 2 : 1
                                border.color: parent.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }
                    }

                    Item { Layout.preferredHeight: 16 }
                }
            }

            // ------------------------------------------------ Projetos arquivados
            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 0
                    anchors.rightMargin: 12
                    anchors.topMargin: 4
                    anchors.bottomMargin: 24
                    spacing: 16

                    // Header
                    RowLayout {
                        Layout.fillHeight: false
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 36
                            radius: Theme.radiusSmall
                            color: Theme.palette.codeSurface
                            border.width: 1
                            border.color: Theme.palette.chatBorder

                            VrLineIcon {
                                anchors.centerIn: parent
                                width: 18
                                height: 18
                                kind: "archive"
                                foreground: Theme.palette.brandOrange
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Projetos Arquivados"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(16)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Conversas arquivadas ficam separadas do Chat VR e podem ser restauradas a qualquer momento."
                                color: Theme.palette.subtleText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    VrProviderSection {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: false
                        title: "Histórico de conversas arquivadas"
                    }

                    RowLayout {
                        Layout.fillHeight: false
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 8

                        VrTextField {
                            id: archivedSearch
                            objectName: "archivedSearch"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: 38
                            placeholderText: "Buscar por título, repositório ou data…"
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: archivedSearch.activeFocus ? 2 : 1
                                border.color: archivedSearch.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                            onTextChanged: archiveDelay.restart()
                        }
                    }

                    ListView {
                        id: archivedList
                        objectName: "archivedList"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.fillHeight: true
                        Layout.minimumHeight: 100
                        clip: true
                        spacing: 6
                        model: studio.archivedModel
                        delegate: Rectangle {
                            objectName: "archivedConversationRow"
                            required property int index
                            required property string conversationId
                            required property string title
                            required property string project
                            required property string provider
                            required property string updatedAt
                            width: archivedList.width
                            height: Math.max(68, archivedRowContent.implicitHeight + 24)
                            radius: Theme.radiusSmall
                            color: index % 2 ? Theme.palette.chatSidebar : "transparent"
                            border.width: 1
                            border.color: Theme.palette.chatBorder

                            GridLayout {
                                id: archivedRowContent
                                columns: width < 520 ? 1 : 3
                                columnSpacing: 12
                                rowSpacing: 8
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14

                                Rectangle {
                                    visible: archivedRowContent.columns > 1
                                    Layout.preferredWidth: 32
                                    Layout.preferredHeight: 32
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: 1
                                    border.color: Theme.palette.chatBorder

                                    VrLineIcon {
                                        anchors.centerIn: parent
                                        width: 16
                                        height: 16
                                        kind: "archive"
                                        foreground: Theme.palette.brandOrange
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 3

                                    Text {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        text: title
                                        color: Theme.palette.headingText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(13)
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        text: (project ? project + " · " : "") + provider + " · " + updatedAt
                                        color: Theme.palette.subtleText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(12)
                                        elide: Text.ElideRight
                                    }
                                }

                                RowLayout {
                                    spacing: 8

                                    VrProviderAction {
                                        text: "Restaurar"
                                        variant: "secondary"
                                        implicitHeight: 32
                                        onClicked: studio.restoreArchived(conversationId)
                                    }

                                    VrProviderAction {
                                        text: "Excluir"
                                        variant: "ghost"
                                        implicitHeight: 32
                                        onClicked: {
                                            root.pendingDeleteId = conversationId
                                            deleteDialog.open()
                                        }
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            anchors.centerIn: parent
                            width: Math.max(0, parent.width - 24)
                            visible: archivedList.count === 0
                            spacing: 8

                            VrLineIcon {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.preferredWidth: 32
                                Layout.preferredHeight: 32
                                kind: "archive"
                                foreground: Theme.palette.mutedText
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Layout.alignment: Qt.AlignHCenter
                                horizontalAlignment: Text.AlignHCenter
                                text: archivedSearch.text.length ? "Nenhum resultado para esta busca." : "Nenhum projeto arquivado."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }

            // ----------------------------------------------------------- Skills
            Loader {
                id: skillsSettingsLoader
                objectName: "skillsSettingsLoader"
                active: root.tabIndex === 6 || root.skillsVisited
                asynchronous: root.tabIndex !== 6
                sourceComponent: Component { VrSkillsSettings { studio: root.studio } }
            }
        }
    }

    Component {
        id: vrUltraSettingsComponent
        VRUltraSettingsPage { }
    }

    Timer { id: archiveDelay; interval: 180; onTriggered: studio.refreshArchived(archivedSearch.text) }

    Dialog {
        id: deleteDialog
        anchors.centerIn: parent
        width: Math.min(460, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Excluir conversa definitivamente?"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "A conversa, o histórico e o workspace local associado serão removidos. Esta ação não pode ser desfeita."
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
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
        background: Rectangle { color: Theme.palette.surface; border.width: 1; border.color: Theme.palette.danger; radius: Theme.radiusPopup }
    }
}
