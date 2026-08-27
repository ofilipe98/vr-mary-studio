import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "vrUltraSettingsPage"

    property string selectionWarning: ""

    function modelMatches(item) {
        var query = modelSearch.text.trim().toLowerCase()
        if (!query.length) return true
        return String(item.label || item.value || "").toLowerCase().indexOf(query) >= 0
            || String(item.provider || "").toLowerCase().indexOf(query) >= 0
            || String(item.description || "").toLowerCase().indexOf(query) >= 0
    }

    function toggleModel(key) {
        var values = chat.researchModelKeys.slice()
        var current = values.indexOf(key)
        if (current >= 0) {
            values.splice(current, 1)
            selectionWarning = ""
        } else if (values.length < 3) {
            values.push(key)
            selectionWarning = ""
        } else {
            selectionWarning = "O VR Ultra aceita no máximo 3 agentes."
        }
        chat.setResearchModels(values)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXs
        spacing: Theme.spaceMd

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
                text: "Escolha até 3 modelos para atuar como agentes de pesquisa. O provedor e o modelo selecionados no Chat VR continuam sendo o orquestrador."
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

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm
            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                VrTextField {
                    id: modelSearch
                    objectName: "vrUltraAgentSearch"
                    anchors.fill: parent
                    leftPadding: 34
                    placeholderText: "Buscar agentes por modelo ou provedor"
                }
                VrLineIcon {
                    anchors.left: parent.left
                    anchors.leftMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    width: 15
                    height: 15
                    kind: "search"
                    foreground: frontend.palette.mutedText
                }
            }
            Text {
                text: chat.researchModelKeys.length + "/3 selecionados"
                color: chat.researchModelKeys.length > 0
                    ? frontend.palette.brandOrange : frontend.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.captionSize
                font.weight: Font.DemiBold
            }
            VrButton {
                text: "Limpar"
                variant: "ghost"
                enabled: chat.researchModelKeys.length > 0
                onClicked: {
                    root.selectionWarning = ""
                    chat.setResearchModels([])
                }
            }
        }

        Rectangle {
            id: agentPool
            objectName: "vrUltraAgentPool"
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border

            ListView {
                id: agentList
                objectName: "vrUltraAgentModelList"
                anchors.fill: parent
                anchors.margins: Theme.spaceSm
                clip: true
                spacing: 5
                model: chat.researchModelItems
                ScrollIndicator.vertical: ScrollIndicator { }

                delegate: Button {
                    id: agentRow
                    required property var modelData
                    readonly property bool selected: chat.researchModelKeys.indexOf(modelData.key) >= 0
                    readonly property bool matchesFilter: root.modelMatches(modelData)
                    width: agentList.width
                    height: matchesFilter ? 62 : 0
                    visible: matchesFilter
                    padding: 0
                    hoverEnabled: true
                    onClicked: root.toggleModel(modelData.key)

                    background: Rectangle {
                        radius: Theme.radiusControl
                        color: agentRow.selected
                            ? Qt.rgba(1.0, 0.45, 0.0, 0.13)
                            : agentRow.hovered ? frontend.palette.chatControl : "transparent"
                        border.width: agentRow.selected ? 1 : 0
                        border.color: frontend.palette.brandOrange
                    }

                    contentItem: RowLayout {
                        spacing: Theme.spaceSm
                        Rectangle {
                            Layout.preferredWidth: 20
                            Layout.preferredHeight: 20
                            radius: 5
                            color: agentRow.selected
                                ? frontend.palette.brandOrange : "transparent"
                            border.width: 1
                            border.color: agentRow.selected
                                ? frontend.palette.brandOrange : frontend.palette.mutedText
                            Text {
                                anchors.centerIn: parent
                                visible: agentRow.selected
                                text: "✓"
                                color: "#FFFFFF"
                                font.pixelSize: 12
                                font.weight: Font.Bold
                            }
                        }
                        VrProviderIcon {
                            Layout.preferredWidth: 24
                            Layout.preferredHeight: 24
                            provider: agentRow.modelData.provider || "codex"
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                Layout.fillWidth: true
                                text: agentRow.modelData.label
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.bodySize
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: agentRow.modelData.description || agentRow.modelData.value
                                color: frontend.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.captionSize
                                elide: Text.ElideRight
                            }
                        }
                        Rectangle {
                            Layout.preferredWidth: providerText.implicitWidth + 16
                            Layout.preferredHeight: 22
                            radius: 7
                            color: frontend.palette.chatControl
                            Text {
                                id: providerText
                                anchors.centerIn: parent
                                text: String(agentRow.modelData.provider || "").toUpperCase()
                                color: agentRow.selected
                                    ? frontend.palette.brandOrange : frontend.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.captionSize
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    width: parent.width - 40
                    visible: chat.researchModelItems.length === 0
                    text: "Nenhum modelo disponível. Ative ou configure os provedores na aba Provedores."
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.bodySize
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: root.selectionWarning.length > 0
            text: root.selectionWarning
            color: frontend.palette.warning
            font.family: Theme.fontFamily
            font.pixelSize: Theme.captionSize
        }
        Text {
            Layout.fillWidth: true
            text: chat.researchModelKeys.length === 0
                ? "Sem seleção, o VR Ultra escolhe automaticamente entre os modelos disponíveis."
                : "Os modelos selecionados serão iniciados como agentes quando o modo VR Ultra estiver ativo no Chat."
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.captionSize
            wrapMode: Text.WordWrap
        }
    }

    Component.onCompleted: chat.refreshModels()
}
