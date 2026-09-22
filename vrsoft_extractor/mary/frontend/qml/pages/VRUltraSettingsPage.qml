import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"
import "../settings/appearance"

Item {
    id: root
    objectName: "vrUltraSettingsPage"

    signal openApplicationsRequested()

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
        topPadding: Theme.scaledGeometry(4)
        rightPadding: Theme.scaledGeometry(12)
        bottomPadding: Theme.scaledGeometry(24)
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        Item {
            width: settingsScroll.availableWidth
            implicitHeight: vrUltraColumn.implicitHeight

            ColumnLayout {
                id: vrUltraColumn
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(848, parent.width)
                spacing: Theme.scaledGeometry(24)

                VrRetrievalSettings {
                    Layout.fillWidth: true
                    bridge: chat.retrievalSettings
                }

                // Orchestrator banner
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Theme.scaledGeometry(46)
                    radius: Theme.scaledGeometry(14)
                    color: Theme.palette.background
                    border.width: 1
                    border.color: Theme.palette.border

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.scaledGeometry(16)
                        anchors.rightMargin: Theme.scaledGeometry(16)
                        spacing: Theme.scaledGeometry(12)

                        VrLineIcon {
                            Layout.preferredWidth: Theme.iconSmall
                            Layout.preferredHeight: Theme.iconSmall
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
                Text {
                    text: "Perfil especialista sênior"
                    Layout.leftMargin: Theme.scaledGeometry(16)
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }

                Rectangle {
                    objectName: "vrUltraSeniorProfileCard"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    implicitHeight: vrUltraSeniorProfileCardContent.implicitHeight + 2
                    radius: Theme.scaledGeometry(14)
                    color: Theme.palette.background
                    border.width: 1
                    border.color: Theme.palette.border

                    ColumnLayout {
                        id: vrUltraSeniorProfileCardContent
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 1
                        spacing: 0

                        AppearanceRow {
                            title: "Ativar perfil especialista sênior"
                            description: "Aplica diretrizes de nível sênior em suporte, treinamento e implantação VR."
                            divider: true

                            VrSwitch {
                                subdued: true
                                objectName: "vrUltraSeniorProfileToggle"
                                Accessible.name: "Ativar perfil especialista sênior"
                                checked: chat.seniorProfileEnabled
                                onToggled: chat.setSeniorProfileEnabled(checked)
                            }
                        }

                        AppearanceRow {
                            title: "Modo de resposta"
                            description: "Direcionamento comportamental das respostas do especialista."
                            divider: false

                            VrComboBox {
                                id: vrResponseModePicker
                                objectName: "vrUltraResponseModePicker"
                                Layout.preferredWidth: Theme.scaledGeometry(320)
                                implicitHeight: Theme.scaledGeometry(34)
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
                                background: Rectangle {
                                    radius: Theme.scaledGeometry(8)
                                    color: Theme.palette.codeSurface
                                    border.width: vrResponseModePicker.activeFocus ? 2 : 1
                                    border.color: vrResponseModePicker.activeFocus ? Theme.palette.focus : Theme.palette.border
                                }
                            }
                        }
                    }
                }

                // Section 2: Pool de pesquisadores
                Text {
                    text: "Pool de pesquisadores"
                    Layout.leftMargin: Theme.scaledGeometry(16)
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }

                Rectangle {
                    objectName: "vrUltraAgentPool"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    implicitHeight: vrUltraAgentPoolContent.implicitHeight + 2
                    radius: Theme.scaledGeometry(14)
                    color: Theme.palette.background
                    border.width: 1
                    border.color: Theme.palette.border

                    ColumnLayout {
                        id: vrUltraAgentPoolContent
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 1
                        spacing: 0

                        AppearanceRow {
                            title: "Modelo dos pesquisadores"
                            description: chat.researchModelKeys.length
                                ? "Os agentes usarão " + (agentModelPicker.currentItem.displayName || agentModelPicker.currentItem.label || "o modelo selecionado") + "."
                                : "A mesma escolha é usada pelos três pesquisadores base e pelo worker opcional de código."
                            divider: false

                            RowLayout {
                                spacing: Theme.scaledGeometry(8)
                                Layout.alignment: Qt.AlignRight

                                Rectangle {
                                    Layout.preferredWidth: Theme.scaledGeometry(84)
                                    Layout.preferredHeight: Theme.scaledGeometry(28)
                                    radius: Theme.scaledGeometry(8)
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

                                VrModelPicker {
                                    id: agentModelPicker
                                    objectName: "vrUltraAgentModelPicker"
                                    Layout.preferredWidth: Theme.scaledGeometry(260)
                                    implicitHeight: Theme.scaledGeometry(34)
                                    outlined: true
                                    popupAbove: false
                                    model: chat.modelItems
                                    currentIndex: root.selectedModelIndex
                                    onActivated: index => chat.setResearchModels([chat.modelItems[index].key])
                                    onFavoriteToggled: index => chat.toggleModelFavorite(index)
                                }
                            }
                        }
                    }
                }

                // Section 3: Contexto de Código e Aplicativo no VR Ultra
                Text {
                    text: "Contexto de código no VR Ultra"
                    Layout.leftMargin: Theme.scaledGeometry(16)
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }

                Rectangle {
                    objectName: "vrUltraCodeAnalysisCard"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    implicitHeight: vrUltraCodeAnalysisCardContent.implicitHeight + 2
                    radius: Theme.scaledGeometry(14)
                    color: Theme.palette.background
                    border.width: 1
                    border.color: Theme.palette.border

                    ColumnLayout {
                        id: vrUltraCodeAnalysisCardContent
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 1
                        spacing: 0

                        AppearanceRow {
                            title: "Análise de código JAR"
                            description: "Consulta os aplicativos, versões e origens selecionados após os outros agentes delimitarem o escopo."
                            divider: true

                            VrSwitch {
                                subdued: true
                                objectName: "vrUltraCodeAnalysisToggle"
                                Accessible.name: "Análise de código JAR"
                                checked: chat.codeAnalysisEnabled
                                enabled: checked || chat.ultraApplicationContextsReady
                                onToggled: chat.setCodeAnalysisEnabled(checked)
                            }
                        }

                        Item {
                            Layout.fillWidth: true
                            implicitHeight: contextCol.implicitHeight + 24

                            ColumnLayout {
                                id: contextCol
                                anchors.fill: parent
                                anchors.leftMargin: Theme.scaledGeometry(16)
                                anchors.rightMargin: Theme.scaledGeometry(16)
                                anchors.topMargin: Theme.scaledGeometry(12)
                                anchors.bottomMargin: Theme.scaledGeometry(12)
                                spacing: Theme.scaledGeometry(12)

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
                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: Theme.scaledGeometry(10)

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 2
                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.label
                                                color: Theme.palette.headingText
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSize(13)
                                                font.weight: Font.Medium
                                                wrapMode: Text.WrapAnywhere
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                visible: text.length > 0
                                                text: modelData.warning
                                                color: Theme.palette.warning
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSizeCaption
                                                wrapMode: Text.WordWrap
                                            }
                                        }

                                        VrButton {
                                            text: "Remover"
                                            variant: "ghost"
                                            implicitHeight: Theme.scaledGeometry(28)
                                            onClicked: chat.removeApplicationContext(modelData.app_id)
                                        }
                                    }
                                }

                                VrButton {
                                    objectName: "vrUltraManageAppsButton"
                                    text: "Gerenciar aplicativos…"
                                    variant: "secondary"
                                    implicitHeight: Theme.scaledGeometry(32)
                                    onClicked: {
                                        root.openApplicationsRequested()
                                        var p = root.parent
                                        while (p) {
                                            if (p.hasOwnProperty("tabIndex") || p.tabIndex !== undefined) {
                                                p.tabIndex = 3
                                                break
                                            }
                                            p = p.parent
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Item { Layout.preferredHeight: Theme.scaledGeometry(16) }
            }
        }
    }

    Component.onCompleted: {
        chat.refreshCodeAnalysisReleases()
    }
}
