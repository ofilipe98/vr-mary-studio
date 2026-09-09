import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "vrUltraSettingsPage"

    readonly property int selectedModelIndex: {
        if (!chat.researchModelKeys.length) return -1
        var selectedKey = chat.researchModelKeys[0]
        for (var index = 0; index < chat.modelItems.length; ++index) {
            if (chat.modelItems[index].key === selectedKey) return index
        }
        return -1
    }

    ScrollView {
        id: settingsScroll
        objectName: "vrUltraSettingsScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        topPadding: 4
        rightPadding: 12
        bottomPadding: 20
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: settingsScroll.availableWidth
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
                        kind: "models"
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
                        text: "VR Ultra · Agentes Especialistas"
                        color: Theme.palette.headingText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(16)
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Modelos dos pesquisadores base, perfil especialista sênior e contexto de código para o Ultra."
                        color: Theme.palette.subtleText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            VrRetrievalSettings {
                Layout.fillWidth: true
                bridge: chat.retrievalSettings
            }

            // Orchestrator banner
            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: 42
                radius: Theme.radiusSmall
                color: Theme.palette.codeSurface
                border.width: 1
                border.color: Theme.palette.chatBorder

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceMd
                    spacing: Theme.spaceSm

                    VrLineIcon {
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 16
                        kind: "models"
                        foreground: Theme.palette.brandOrange
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Orquestrador: definido pelo seletor de provedor/modelo no compositor do Chat VR"
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        elide: Text.ElideRight
                    }
                }
            }

            // Section 1: Perfil especialista sênior
            VrProviderSection {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                title: "Perfil Especialista Sênior"
            }

            Rectangle {
                objectName: "vrUltraSeniorProfileCard"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: vrUltraSeniorProfileCardContent.implicitHeight
                color: "transparent"
                border.width: 0

                ColumnLayout {
                    id: vrUltraSeniorProfileCardContent
                    anchors.fill: parent
                    spacing: 12

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Ativar perfil especialista sênior"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Aplica diretrizes de nível sênior em suporte, treinamento e implantação VR."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            objectName: "vrUltraSeniorProfileToggle"
                            Accessible.name: "Ativar perfil especialista sênior"
                            checked: chat.seniorProfileEnabled
                            onToggled: chat.setSeniorProfileEnabled(checked)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 8
                        enabled: chat.seniorProfileEnabled

                        Text {
                            text: "Modo"
                            color: chat.seniorProfileEnabled ? Theme.palette.headingText : Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                            Layout.preferredWidth: 60
                        }

                        VrComboBox {
                            id: vrResponseModePicker
                            objectName: "vrUltraResponseModePicker"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: 38
                            enabled: chat.seniorProfileEnabled
                            model: [
                                { "label": "Automático — detecta a melhor abordagem pelo contexto", "value": "auto" },
                                { "label": "Treinamento — foco didático, passo a passo e regras de negócio", "value": "training" },
                                { "label": "Suporte — diagnóstico ágil, causa raiz e ação corretiva", "value": "support" },
                                { "label": "Implantação — homologação, pré-requisitos e validações", "value": "implementation" }
                            ]
                            textRole: "label"
                            currentIndex: {
                                var current = chat.vrResponseMode
                                for (var index = 0; index < model.length; ++index) {
                                    if (model[index].value === current) return index
                                }
                                return 0
                            }
                            onActivated: index => {
                                if (index >= 0 && index < model.length)
                                    chat.setVrResponseMode(model[index].value)
                            }
                        }
                    }
                }
            }

            // Section 2: Pool de pesquisadores
            VrProviderSection {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                title: "Pool de Pesquisadores"
            }

            Rectangle {
                objectName: "vrUltraAgentPool"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: vrUltraAgentPoolContent.implicitHeight
                color: "transparent"
                border.width: 0

                ColumnLayout {
                    id: vrUltraAgentPoolContent
                    anchors.fill: parent
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 10

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Pool de pesquisadores"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "A mesma escolha é usada pelos três pesquisadores base e pelo worker opcional de código."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        Rectangle {
                            Layout.preferredWidth: 84
                            Layout.preferredHeight: 26
                            radius: Theme.radiusSmall
                            color: Qt.rgba(1.0, 0.45, 0.0, 0.12)
                            border.width: 1
                            border.color: Qt.rgba(1.0, 0.45, 0.0, 0.3)

                            Text {
                                anchors.centerIn: parent
                                text: chat.codeAnalysisEnabled ? "4 agentes" : "3 agentes"
                                color: Theme.palette.brandOrange
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                            }
                        }
                    }

                    VrModelPicker {
                        id: agentModelPicker
                        objectName: "vrUltraAgentModelPicker"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 42
                        outlined: true
                        popupAbove: false
                        model: chat.modelItems
                        currentIndex: root.selectedModelIndex
                        onActivated: index => chat.setResearchModels([chat.modelItems[index].key])
                        onFavoriteToggled: index => chat.toggleModelFavorite(index)
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: chat.researchModelKeys.length
                            ? "Os agentes usarão " + (agentModelPicker.currentItem.displayName
                                || agentModelPicker.currentItem.label || "o modelo selecionado") + "."
                            : "Selecione o modelo dos agentes do VR Ultra."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Section 3: Contexto de Código e Aplicativo no VR Ultra
            VrProviderSection {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                title: "Contexto de Código no VR Ultra"
            }

            Rectangle {
                objectName: "vrUltraCodeAnalysisCard"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: vrUltraCodeAnalysisCardContent.implicitHeight
                color: "transparent"
                border.width: 0

                ColumnLayout {
                    id: vrUltraCodeAnalysisCardContent
                    anchors.fill: parent
                    spacing: 12

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Análise de código JAR"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Consulta os aplicativos, versões e origens selecionados após os outros agentes delimitarem o escopo."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            objectName: "vrUltraCodeAnalysisToggle"
                            Accessible.name: "Análise de código JAR"
                            checked: chat.codeAnalysisEnabled
                            enabled: checked || chat.ultraApplicationContextsReady
                            onToggled: chat.setCodeAnalysisEnabled(checked)
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: chat.ultraApplicationContexts.length ? "Aplicativos incluídos na próxima análise:" : "Selecione uma versão, variante e origem em Aplicativos e versões e clique em Usar no Ultra."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: chat.ultraApplicationContexts
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                wrapMode: Text.WrapAnywhere
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: text.length > 0
                                text: modelData.warning
                                color: Theme.palette.warning
                                font.family: Theme.fontFamily
                                wrapMode: Text.WordWrap
                            }
                            VrButton {
                                text: "Remover do contexto"
                                variant: "secondary"
                                onClicked: chat.removeApplicationContext(modelData.app_id)
                            }
                        }
                    }
                    VrButton {
                        text: "Gerenciar aplicativos…"
                        variant: "secondary"
                        onClicked: {
                            var p = root.parent
                            while (p && !p.hasOwnProperty("tabIndex")) p = p.parent
                            if (p) p.tabIndex = 3
                        }
                    }

                }
            }

            Item { Layout.preferredHeight: 16 }
        }
    }

    Component.onCompleted: {
        chat.refreshCodeAnalysisReleases()
    }
}
