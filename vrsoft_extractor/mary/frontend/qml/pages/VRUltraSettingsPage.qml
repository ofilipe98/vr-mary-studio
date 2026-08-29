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

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXs
        spacing: Theme.spaceLg

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            Text {
                text: "VR Ultra · agentes"
                color: frontend.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.headingSize
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: "Escolha um modelo para os três agentes base e, quando habilitado, para o Agente de Código. O Chat VR continua sendo o orquestrador."
                color: frontend.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                wrapMode: Text.WordWrap
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            radius: Theme.radiusControl
            color: Qt.rgba(1.0, 0.45, 0.0, 0.09)
            border.width: 1
            border.color: Qt.rgba(1.0, 0.45, 0.0, 0.45)

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceMd
                anchors.rightMargin: Theme.spaceMd
                spacing: Theme.spaceSm
                VrLineIcon {
                    Layout.preferredWidth: 18
                    Layout.preferredHeight: 18
                    kind: "models"
                    foreground: frontend.palette.brandOrange
                }
                Text {
                    Layout.fillWidth: true
                    text: "Orquestrador: definido pelo seletor de provedor/modelo no compositor do Chat VR"
                    color: frontend.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    elide: Text.ElideRight
                }
            }
        }

        Rectangle {
            objectName: "vrUltraSeniorProfileCard"
            Layout.fillWidth: true
            Layout.preferredHeight: 146
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Perfil especialista sênior"
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Libera no Chat VR e VR Ultra a escolha manual do formato. É preferência de trabalho, não autorização."
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            wrapMode: Text.WordWrap
                        }
                    }
                    VrCheckBox {
                        objectName: "vrUltraSeniorProfileToggle"
                        text: "Ativo"
                        checked: chat.seniorProfileEnabled
                        onToggled: chat.setSeniorProfileEnabled(checked)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Modo de resposta"
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.captionSize
                    }
                    VrComboBox {
                        id: responseModePicker
                        objectName: "vrUltraResponseModePicker"
                        Layout.fillWidth: true
                        enabled: chat.seniorProfileEnabled
                        model: ["Automático", "Treinamento", "Suporte", "Implantação"]
                        property var values: ["auto", "training", "support", "implementation"]
                        currentIndex: Math.max(0, values.indexOf(chat.vrResponseMode))
                        onActivated: index => chat.setVrResponseMode(values[index])
                    }
                }
            }
        }

        Rectangle {
            objectName: "vrUltraAgentPool"
            Layout.fillWidth: true
            Layout.preferredHeight: 152
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm
                    VrLineIcon {
                        Layout.preferredWidth: 20
                        Layout.preferredHeight: 20
                        kind: "agents"
                        foreground: frontend.palette.text
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text {
                            text: "Modelo dos agentes de pesquisa"
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "A mesma escolha é usada pelos três pesquisadores base e pelo worker opcional de código."
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                        }
                    }
                    Rectangle {
                        Layout.preferredWidth: 78
                        Layout.preferredHeight: 24
                        radius: 8
                        color: Qt.rgba(1.0, 0.45, 0.0, 0.12)
                        Text {
                            anchors.centerIn: parent
                            text: chat.codeAnalysisEnabled ? "4 agentes" : "3 agentes"
                            color: frontend.palette.brandOrange
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            font.weight: Font.DemiBold
                        }
                    }
                }

                VrModelPicker {
                    id: agentModelPicker
                    objectName: "vrUltraAgentModelPicker"
                    Layout.fillWidth: true
                    implicitHeight: 42
                    popupAbove: false
                    model: chat.modelItems
                    currentIndex: root.selectedModelIndex
                    onActivated: index => chat.setResearchModels([chat.modelItems[index].key])
                    onFavoriteToggled: index => chat.toggleModelFavorite(index)
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: chat.researchModelKeys.length
                ? "Os agentes usarão " + (agentModelPicker.currentItem.displayName
                    || agentModelPicker.currentItem.label || "o modelo selecionado") + "."
                : "Selecione o modelo dos agentes do VR Ultra."
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.captionSize
            wrapMode: Text.WordWrap
        }

        Rectangle {
            objectName: "vrUltraCodeAnalysisCard"
            Layout.fillWidth: true
            Layout.preferredHeight: 126
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Agente de Código / JAR"
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "Opt-in: consulta somente o índice da release após os outros agentes delimitarem o escopo."
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            wrapMode: Text.WordWrap
                        }
                    }
                    VrCheckBox {
                        objectName: "vrUltraCodeAnalysisToggle"
                        text: "Ativo"
                        checked: chat.codeAnalysisEnabled
                        enabled: chat.codeAnalysisReleaseItems.length > 0
                        onToggled: chat.setCodeAnalysisEnabled(checked)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Release"
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.captionSize
                    }
                    VrComboBox {
                        id: codeReleasePicker
                        objectName: "vrUltraCodeAnalysisRelease"
                        Layout.fillWidth: true
                        enabled: chat.codeAnalysisReleaseItems.length > 0
                        model: chat.codeAnalysisReleaseItems.length
                            ? chat.codeAnalysisReleaseItems
                            : [{"label": "Nenhuma release inventariada", "releaseId": ""}]
                        textRole: "label"
                        currentIndex: {
                            for (var index = 0; index < chat.codeAnalysisReleaseItems.length; ++index) {
                                if (chat.codeAnalysisReleaseItems[index].releaseId === chat.codeAnalysisRelease)
                                    return index
                            }
                            return 0
                        }
                        onActivated: index => {
                            if (index < chat.codeAnalysisReleaseItems.length)
                                chat.setCodeAnalysisRelease(chat.codeAnalysisReleaseItems[index].releaseId)
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }

    Component.onCompleted: {
        chat.refreshModels()
        chat.refreshCodeAnalysisReleases()
    }
}
