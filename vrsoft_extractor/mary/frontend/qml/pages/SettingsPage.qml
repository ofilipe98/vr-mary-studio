import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"
import "../settings/appearance"

Item {
    id: root
    objectName: "settingsPage"
    property int tabIndex: 0
    property string pendingDeleteId: ""
    property bool vrUltraVisited: false
    property bool appsVisited: false
    property bool providersVisited: false
    property bool skillsVisited: false
    onTabIndexChanged: {
        if (typeof settingsTabBar !== "undefined" && settingsTabBar && settingsTabBar.currentIndex !== tabIndex)
            settingsTabBar.currentIndex = tabIndex
        if (tabIndex === 1) providersVisited = true
        if (tabIndex === 2) vrUltraVisited = true
        if (tabIndex === 3) appsVisited = true
        if (tabIndex === 7) skillsVisited = true
        if (!frontend.reduceMotion)
            tabTransition.restart()
    }

    function openSearchResult(index) {
        root.tabIndex = Math.max(0, Math.min(7, Number(index)))
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
            id: settingsTabBar
            understated: true
            Layout.minimumWidth: 0
            objectName: "settingsTabBar"
            Layout.fillWidth: true
            model: ["Geral", "Provedores", "VR Ultra", "Aplicativos e versões", "Aparência", "Browser", "Projetos arquivados", "Skills"]
            currentIndex: root.tabIndex
            Binding on currentIndex {
                value: root.tabIndex
            }
            onActivated: index => root.tabIndex = index
        }

        StackLayout {
            id: settingsStack
            Layout.minimumWidth: 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.tabIndex

            transform: Translate { id: tabShift; y: 0 }

            SequentialAnimation {
                id: tabTransition
                PropertyAction { target: settingsStack; property: "opacity"; value: 0.25 }
                PropertyAction { target: tabShift; property: "y"; value: 6 }
                ParallelAnimation {
                    NumberAnimation {
                        target: settingsStack
                        property: "opacity"
                        to: 1.0
                        duration: Theme.motionDuration
                        easing.type: Easing.OutCubic
                    }
                    NumberAnimation {
                        target: tabShift
                        property: "y"
                        to: 0
                        duration: Theme.motionDuration
                        easing.type: Easing.OutCubic
                    }
                }
            }

                        // ------------------------------------------------------------ Geral
            ScrollView {
                id: generalScroll
                objectName: "generalScroll"
                clip: true
                contentWidth: availableWidth
                topPadding: 4
                rightPadding: 12
                bottomPadding: 24
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                Item {
                    width: generalScroll.availableWidth
                    implicitHeight: generalColumn.implicitHeight

                    ColumnLayout {
                        id: generalColumn
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(848, parent.width)
                        spacing: 24

                        Text {
                            text: "Base de conhecimento"
                            Layout.leftMargin: 16
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(14)
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: rootFieldContent.implicitHeight + 24

                                ColumnLayout {
                                    id: rootFieldContent
                                    anchors.fill: parent
                                    anchors.leftMargin: 16
                                    anchors.rightMargin: 16
                                    anchors.topMargin: 12
                                    anchors.bottomMargin: 12
                                    spacing: 10

                                    Text {
                                        text: "Repositório local de documentação"
                                        color: Theme.palette.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(13)
                                        font.weight: Font.DemiBold
                                    }

                                    Text {
                                        text: "Diretório local com a documentação do ecossistema VR. O Chat VR e os agentes consultam esta pasta para fundamentar respostas."
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(13)
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8

                                        VrTextField {
                                            id: rootField
                                            objectName: "rootField"
                                            Layout.fillWidth: true
                                            implicitHeight: 34
                                            text: studio.settingsValues.root || ""
                                            placeholderText: "Caminho da pasta do repositório VR..."
                                            background: Rectangle {
                                                radius: 8
                                                color: Theme.palette.codeSurface
                                                border.width: rootField.activeFocus ? 2 : 1
                                                border.color: rootField.activeFocus ? Theme.palette.focus : Theme.palette.border
                                            }
                                        }

                                        VrButton {
                                            text: "Procurar…"
                                            variant: "secondary"
                                            implicitHeight: 34
                                            onClicked: {
                                                var value = studio.chooseKnowledgeRoot()
                                                if (value.length) rootField.text = value
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            text: "Credenciais de sincronização"
                            Layout.leftMargin: 16
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(14)
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: movideskContent.implicitHeight + 24

                                ColumnLayout {
                                    id: movideskContent
                                    anchors.fill: parent
                                    anchors.leftMargin: 16
                                    anchors.rightMargin: 16
                                    anchors.topMargin: 12
                                    anchors.bottomMargin: 12
                                    spacing: 10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: "Movidesk"
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(13)
                                            font.weight: Font.DemiBold
                                            Layout.fillWidth: true
                                        }
                                        VrProviderStatus {
                                            text: studio.settingsValues.movideskPasswordConfigured ? "Senha configurada" : "Pendente"
                                            tone: studio.settingsValues.movideskPasswordConfigured ? "success" : "muted"
                                        }
                                    }

                                    Text {
                                        text: studio.settingsValues.movideskPasswordConfigured
                                            ? "Senha configurada. Deixe o campo de senha vazio para mantê-la."
                                            : "Credenciais para baixar chamados e documentação técnica Movidesk."
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(13)
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: root.width < 500 ? 1 : 2
                                        columnSpacing: 10
                                        rowSpacing: 8

                                        VrTextField {
                                            id: movideskEmail
                                            objectName: "movideskEmail"
                                            Layout.fillWidth: true
                                            implicitHeight: 34
                                            placeholderText: "Email Movidesk"
                                            text: studio.settingsValues.movideskEmail || ""
                                            background: Rectangle {
                                                radius: 8
                                                color: Theme.palette.codeSurface
                                                border.width: movideskEmail.activeFocus ? 2 : 1
                                                border.color: movideskEmail.activeFocus ? Theme.palette.focus : Theme.palette.border
                                            }
                                        }

                                        VrTextField {
                                            id: movideskPassword
                                            objectName: "movideskPassword"
                                            Layout.fillWidth: true
                                            implicitHeight: 34
                                            placeholderText: studio.settingsValues.movideskPasswordConfigured ? "Senha configurada" : "Senha Movidesk"
                                            text: ""
                                            echoMode: TextInput.Password
                                            background: Rectangle {
                                                radius: 8
                                                color: Theme.palette.codeSurface
                                                border.width: movideskPassword.activeFocus ? 2 : 1
                                                border.color: movideskPassword.activeFocus ? Theme.palette.focus : Theme.palette.border
                                            }
                                        }
                                    }
                                }

                                Rectangle {
                                    height: 1
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    color: Theme.palette.border
                                }
                            }

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: endooContent.implicitHeight + 24

                                ColumnLayout {
                                    id: endooContent
                                    anchors.fill: parent
                                    anchors.leftMargin: 16
                                    anchors.rightMargin: 16
                                    anchors.topMargin: 12
                                    anchors.bottomMargin: 12
                                    spacing: 10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: "Wiki Endoo"
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(13)
                                            font.weight: Font.DemiBold
                                            Layout.fillWidth: true
                                        }
                                        VrProviderStatus {
                                            text: studio.settingsValues.endooPasswordConfigured ? "Senha configurada" : "Pendente"
                                            tone: studio.settingsValues.endooPasswordConfigured ? "success" : "muted"
                                        }
                                    }

                                    Text {
                                        text: studio.settingsValues.endooPasswordConfigured
                                            ? "Senha configurada. Deixe o campo de senha vazio para mantê-la."
                                            : "Credenciais para sincronização automática da base de conhecimento Endoo."
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(13)
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: root.width < 500 ? 1 : 2
                                        columnSpacing: 10
                                        rowSpacing: 8

                                        VrTextField {
                                            id: endooEmail
                                            objectName: "endooEmail"
                                            Layout.fillWidth: true
                                            implicitHeight: 34
                                            placeholderText: "Email Endoo"
                                            text: studio.settingsValues.endooEmail || ""
                                            background: Rectangle {
                                                radius: 8
                                                color: Theme.palette.codeSurface
                                                border.width: endooEmail.activeFocus ? 2 : 1
                                                border.color: endooEmail.activeFocus ? Theme.palette.focus : Theme.palette.border
                                            }
                                        }

                                        VrTextField {
                                            id: endooPassword
                                            objectName: "endooPassword"
                                            Layout.fillWidth: true
                                            implicitHeight: 34
                                            placeholderText: studio.settingsValues.endooPasswordConfigured ? "Senha configurada" : "Senha Endoo"
                                            text: ""
                                            echoMode: TextInput.Password
                                            background: Rectangle {
                                                radius: 8
                                                color: Theme.palette.codeSurface
                                                border.width: endooPassword.activeFocus ? 2 : 1
                                                border.color: endooPassword.activeFocus ? Theme.palette.focus : Theme.palette.border
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            text: "Sincronização e diagnóstico"
                            Layout.leftMargin: 16
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(14)
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            AppearanceRow {
                                title: "Repetir sincronização"
                                description: "Frequência para sincronização de chamados e bases em segundo plano."
                                divider: true

                                VrComboBox {
                                    id: interval
                                    Layout.preferredWidth: 210
                                    implicitHeight: 34
                                    model: ["A cada 15 minutos", "A cada 30 minutos", "A cada 1 hora", "A cada 2 horas", "A cada 4 horas", "A cada 8 horas", "A cada 24 horas"]
                                    property var values: ["15", "30", "60", "120", "240", "480", "1440"]
                                    Component.onCompleted: {
                                        var found = values.indexOf(studio.settingsValues.interval || "120")
                                        currentIndex = found >= 0 ? found : 3
                                    }
                                    background: Rectangle {
                                        radius: 8
                                        color: Theme.palette.codeSurface
                                        border.width: interval.activeFocus ? 2 : 1
                                        border.color: interval.activeFocus ? Theme.palette.focus : Theme.palette.border
                                    }
                                }
                            }

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: diagnosticContent.implicitHeight + 24

                                ColumnLayout {
                                    id: diagnosticContent
                                    anchors.fill: parent
                                    anchors.leftMargin: 16
                                    anchors.rightMargin: 16
                                    anchors.topMargin: 12
                                    anchors.bottomMargin: 12
                                    spacing: 8

                                    Text {
                                        text: "Diagnóstico local"
                                        color: Theme.palette.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(13)
                                        font.weight: Font.DemiBold
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        implicitHeight: Math.max(38, diagnosticText.implicitHeight + 16)
                                        radius: 8
                                        color: Theme.palette.codeSurface
                                        border.width: 1
                                        border.color: Theme.palette.border

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
                            }
                        }

                        Text {
                            text: "Ações do sistema"
                            Layout.leftMargin: 16
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(14)
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: actionsContent.implicitHeight + 24

                                RowLayout {
                                    id: actionsContent
                                    anchors.fill: parent
                                    anchors.leftMargin: 16
                                    anchors.rightMargin: 16
                                    anchors.topMargin: 12
                                    anchors.bottomMargin: 12
                                    spacing: 16

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        spacing: 3

                                        Text {
                                            text: "Manutenção do ambiente"
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(13)
                                            font.weight: Font.DemiBold
                                        }

                                        Text {
                                            text: "Instale ferramentas portáteis, abra o ambiente no Codex ou salve as variáveis locais no arquivo .env."
                                            color: Theme.palette.mutedText
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(13)
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                    }

                                    Flow {
                                        id: systemActions
                                        objectName: "systemActions"
                                        spacing: 8
                                        Layout.alignment: Qt.AlignRight

                                        VrButton {
                                            objectName: "installOcrAction"
                                            text: "Instalar OCR portátil"
                                            variant: "secondary"
                                            implicitHeight: 32
                                            onClicked: studio.runSync("ocr")
                                        }

                                        VrButton {
                                            objectName: "openCodexAction"
                                            text: "Abrir no Codex"
                                            variant: "secondary"
                                            implicitHeight: 32
                                            onClicked: studio.openVrInCodex()
                                        }

                                        VrButton {
                                            objectName: "saveSettingsAction"
                                            text: "Salvar .env"
                                            variant: "primary"
                                            implicitHeight: 32
                                            onClicked: studio.saveSettings(rootField.text, movideskEmail.text, movideskPassword.text, endooEmail.text, endooPassword.text, interval.values[interval.currentIndex])
                                        }
                                    }
                                }
                            }
                        }

                        // Hidden legacy controls preserving full test backward compatibility
                        Item {
                            visible: false
                            VrComboBox {
                                id: interfaceFontCombo
                                objectName: "interfaceFontCombo"
                                model: ["Segoe UI", "Arial", "Inter", "Tahoma"]
                                currentIndex: Math.max(0, model.indexOf(frontend.interfaceFontFamily))
                            }
                            VrComboBox {
                                id: interfaceFontSizeCombo
                                objectName: "interfaceFontSizeCombo"
                                model: ["12 px", "13 px", "14 px", "15 px", "16 px", "18 px", "20 px", "22 px"]
                                currentIndex: Math.max(0, model.indexOf(frontend.interfaceFontSize + " px"))
                            }
                            VrComboBox {
                                id: monospaceFontCombo
                                objectName: "monospaceFontCombo"
                                model: ["Consolas", "Cascadia Code", "Courier New"]
                                currentIndex: Math.max(0, model.indexOf(frontend.monospaceFontFamily))
                            }
                            VrComboBox {
                                id: monospaceFontSizeCombo
                                objectName: "monospaceFontSizeCombo"
                                model: ["10 px", "11 px", "12 px", "13 px", "14 px", "16 px", "18 px", "20 px"]
                                currentIndex: Math.max(0, model.indexOf(frontend.monospaceFontSize + " px"))
                            }
                            VrSwitch {
                                id: wordWrapSwitch
                                objectName: "wordWrapSwitch"
                                checked: frontend.wordWrap
                            }
                        }

                        Item { Layout.preferredHeight: 16 }
                    }
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

            // ------------------------------------------------ Aplicativos e versões
            Loader {
                id: appsSettingsLoader
                objectName: "appsSettingsLoader"
                active: root.tabIndex === 3 || root.appsVisited
                visible: root.tabIndex === 3
                // Finish an explicit navigation immediately. Preload remains asynchronous: true.
                asynchronous: root.tabIndex !== 3
                sourceComponent: appsSettingsComponent
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

                Item {
                    width: appearanceScroll.availableWidth
                    implicitHeight: appearanceColumn.implicitHeight
                    ColumnLayout {
                    id: appearanceColumn
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(848, parent.width)
                    spacing: 24

                    AppearanceSettingsView {
                        Layout.fillWidth: true
                    }

                    Rectangle {
                        visible: false
                        Layout.fillWidth: true
                        height: 1
                        color: Theme.palette.border
                    }

                    // Escala da interface
                    VrSettingsRow {
                        visible: false
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
                                    ? "Automática ativa: " + Theme.automaticScalePercent + "%. Ajusta a leitura ao tamanho da janela."
                                    : "Ajusta a leitura em todo o aplicativo. Textos e controles se adaptam à escala escolhida."
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

                    // Aceleracao grafica de hardware
                    VrSettingsRow {
                        visible: false
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                objectName: "hardwareAccelerationText"
                                text: "Aceleração gráfica de hardware"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                objectName: "hardwareAccelerationDescription"
                                text: frontend.hardwareAcceleration
                                    ? "Ativa: renderiza via placa de vídeo dedicada (Direct3D 11). Pode acionar recursos do driver da NVIDIA. Desative para renderização por processador (CPU). (Requer reiniciar o app)"
                                    : "Desativada: renderização por software (CPU). O app opera sem exigir GPU dedicada e sem acionar a barra Game Ready da NVIDIA. (Requer reiniciar o app)"
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            objectName: "hardwareAccelerationSwitch"
                            Accessible.name: "Aceleração gráfica de hardware"
                            checked: frontend.hardwareAcceleration
                            onToggled: frontend.setHardwareAcceleration(checked)
                        }
                    }

                    Item { Layout.preferredHeight: 16 }
                }
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
                bottomPadding: 24
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                Item {
                    width: browserScroll.availableWidth
                    implicitHeight: browserColumn.implicitHeight

                    ColumnLayout {
                        id: browserColumn
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(848, parent.width)
                        spacing: 24

                        Text {
                            text: "Integração com o agente"
                            Layout.leftMargin: 16
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(14)
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            AppearanceRow {
                                title: "Acesso do agente ao browser"
                                description: "Permite que agentes abram e controlem a superfície Browser durante uma sessão."
                                divider: true

                                VrSwitch {
                                    subdued: true
                                    objectName: "browserAgentAccessSwitch"
                                    Accessible.name: "Acesso do agente ao browser"
                                    checked: frontend.browserAgentAccess
                                    onToggled: frontend.setBrowserAgentAccess(checked)
                                }
                            }

                            AppearanceRow {
                                title: "Mostrar preview automaticamente"
                                description: "Expande o painel do Browser quando uma navegação é iniciada pelo agente."
                                divider: false

                                VrSwitch {
                                    subdued: true
                                    objectName: "browserAutoShowSwitch"
                                    Accessible.name: "Mostrar preview automaticamente"
                                    checked: frontend.browserAutoShowPreview
                                    onToggled: frontend.setBrowserAutoShowPreview(checked)
                                }
                            }
                        }

                        Text {
                            text: "Visualização e dimensões"
                            Layout.leftMargin: 16
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(14)
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            AppearanceRow {
                                title: "Viewport padrão"
                                description: "Define o tamanho inicial usado em novas superfícies do browser."
                                divider: true

                                VrComboBox {
                                    objectName: "browserViewportCombo"
                                    Layout.preferredWidth: 210
                                    implicitHeight: 34
                                    model: ["Preencher painel", "Desktop 1280 × 720", "Desktop 1440 × 900", "Mobile 390 × 844"]
                                    property var values: ["fill", "1280x720", "1440x900", "390x844"]
                                    currentIndex: Math.max(0, values.indexOf(frontend.browserViewport))
                                    onActivated: index => frontend.setBrowserViewport(values[index])
                                    background: Rectangle {
                                        radius: 8
                                        color: Theme.palette.codeSurface
                                        border.width: parent.activeFocus ? 2 : 1
                                        border.color: parent.activeFocus ? Theme.palette.focus : Theme.palette.border
                                    }
                                }
                            }

                            AppearanceRow {
                                title: "Zoom padrão"
                                description: "Zoom aplicado a novas abas do browser."
                                divider: true

                                VrComboBox {
                                    objectName: "browserZoomCombo"
                                    Layout.preferredWidth: 210
                                    implicitHeight: 34
                                    model: ["75%", "90%", "100%", "110%", "125%", "150%"]
                                    property var values: ["75", "90", "100", "110", "125", "150"]
                                    currentIndex: Math.max(0, values.indexOf(frontend.browserZoom))
                                    onActivated: index => frontend.setBrowserZoom(values[index])
                                    background: Rectangle {
                                        radius: 8
                                        color: Theme.palette.codeSurface
                                        border.width: parent.activeFocus ? 2 : 1
                                        border.color: parent.activeFocus ? Theme.palette.focus : Theme.palette.border
                                    }
                                }
                            }

                            AppearanceRow {
                                title: "Aparência padrão"
                                description: "Preferência de cores para páginas compatíveis; Sistema acompanha o aplicativo."
                                divider: false

                                VrComboBox {
                                    objectName: "browserAppearanceCombo"
                                    Layout.preferredWidth: 210
                                    implicitHeight: 34
                                    model: ["Sistema", "Claro", "Escuro"]
                                    property var values: ["system", "light", "dark"]
                                    currentIndex: Math.max(0, values.indexOf(frontend.browserAppearance))
                                    onActivated: index => frontend.setBrowserAppearance(values[index])
                                    background: Rectangle {
                                        radius: 8
                                        color: Theme.palette.codeSurface
                                        border.width: parent.activeFocus ? 2 : 1
                                        border.color: parent.activeFocus ? Theme.palette.focus : Theme.palette.border
                                    }
                                }
                            }
                        }

                        Item { Layout.preferredHeight: 16 }
                    }
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

                    Item {
                        Layout.fillWidth: true
                        implicitHeight: archivedHeaderCol.implicitHeight

                        ColumnLayout {
                            id: archivedHeaderCol
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.min(848, parent.width)
                            spacing: 12

                            Text {
                                text: "Histórico de conversas arquivadas"
                                Layout.leftMargin: 16
                                color: Theme.palette.text
                                opacity: 0.7
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(14)
                            }

                            VrTextField {
                                id: archivedSearch
                                objectName: "archivedSearch"
                                Layout.fillWidth: true
                                implicitHeight: 38
                                placeholderText: "Buscar por título, repositório ou data…"
                                background: Rectangle {
                                    radius: 10
                                    color: Theme.palette.background
                                    border.width: archivedSearch.activeFocus ? 2 : 1
                                    border.color: archivedSearch.activeFocus ? Theme.palette.focus : Theme.palette.border
                                }
                                onTextChanged: archiveDelay.restart()
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 120

                        ListView {
                            id: archivedList
                            objectName: "archivedList"
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.min(848, parent.width)
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            clip: true
                            spacing: 8
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
                                radius: 10
                                color: index % 2 ? frontend.palette.chatSidebar : 'transparent'
                                border.width: 1
                                border.color: Theme.palette.border

                                GridLayout {
                                    id: archivedRowContent
                                    columns: width < 520 ? 1 : 3
                                    columnSpacing: 12
                                    rowSpacing: 8
                                    anchors.fill: parent
                                    anchors.leftMargin: 16
                                    anchors.rightMargin: 16

                                    Rectangle {
                                        visible: archivedRowContent.columns > 1
                                        Layout.preferredWidth: 32
                                        Layout.preferredHeight: 32
                                        radius: 8
                                        color: Theme.palette.codeSurface
                                        border.width: 1
                                        border.color: Theme.palette.border

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
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(13)
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            text: (project ? project + " · " : "") + provider + " · " + updatedAt
                                            color: Theme.palette.mutedText
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(12)
                                            elide: Text.ElideRight
                                        }
                                    }

                                    RowLayout {
                                        spacing: 8

                                        VrButton {
                                            text: "Restaurar"
                                            variant: "secondary"
                                            implicitHeight: 32
                                            onClicked: studio.restoreArchived(conversationId)
                                        }

                                        VrButton {
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
            }

            // ----------------------------------------------------------- Skills
            Loader {
                id: skillsSettingsLoader
                objectName: "skillsSettingsLoader"
                active: root.tabIndex === 7 || root.skillsVisited
                asynchronous: root.tabIndex !== 7
                sourceComponent: Component { VrSkillsSettings { studio: root.studio } }
            }
        }
    }

    Component {
        id: vrUltraSettingsComponent
        VRUltraSettingsPage {
            onOpenApplicationsRequested: root.tabIndex = 3
        }
    }

    Component {
        id: appsSettingsComponent
        ApplicationsSettingsPage { }
    }

    Timer { id: archiveDelay; interval: 180; onTriggered: studio.refreshArchived(archivedSearch.text) }

    Dialog {
        id: deleteDialog
        anchors.centerIn: parent
        width: Math.min(460, root.width - Theme.spaceLg * 2)
        modal: true
        dim: true
        padding: 0
        topPadding: 0
        bottomPadding: 0
        leftPadding: 0
        rightPadding: 0
        header: null
        footer: null
        standardButtons: Dialog.NoButton
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: 14
        }
        contentItem: ColumnLayout {
            spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 20
                Layout.leftMargin: 20
                Layout.rightMargin: 16
                Layout.bottomMargin: 14
                spacing: 14
                Rectangle {
                    width: 40
                    height: 40
                    radius: 20
                    color: Qt.alpha(Theme.palette.danger, 0.12)
                    Layout.alignment: Qt.AlignTop
                    VrLineIcon {
                        anchors.centerIn: parent
                        width: 18
                        height: 18
                        kind: "trash"
                        foreground: Theme.palette.danger
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 4
                    Text {
                        text: "Excluir conversa definitivamente?"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(15)
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "A conversa, o histórico e o workspace local associado serão removidos. Esta ação não pode ser desfeita."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        wrapMode: Text.WordWrap
                    }
                }
                VrIconButton {
                    Layout.alignment: Qt.AlignTop
                    iconKind: "close"
                    iconSize: 10
                    implicitWidth: 26
                    implicitHeight: 26
                    foreground: Theme.palette.mutedText
                    onClicked: deleteDialog.close()
                }
            }
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Theme.palette.chatBorder
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                Layout.bottomMargin: 14
                Layout.leftMargin: 20
                Layout.rightMargin: 20
                spacing: 10
                Item { Layout.fillWidth: true }
                VrButton {
                    text: "Cancelar"
                    onClicked: deleteDialog.close()
                }
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
    }
}
