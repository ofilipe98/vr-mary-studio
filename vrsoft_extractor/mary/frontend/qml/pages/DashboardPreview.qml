import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root

    Rectangle { anchors.fill: parent; color: frontend.palette.background }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: 8

        VrPageHeader {
            Layout.fillWidth: true
            title: "Visão geral"
            subtitle: "Wikis, KB e Vídeos possuem saúde, inventário e ações independentes."
        }

        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: width < 820 ? 1 : 2
            rows: width < 820 ? 4 : 2
            columnSpacing: 10
            rowSpacing: 6

            Repeater {
                model: studio.dashboardSources
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 150
                    radius: Theme.radiusCard
                    color: frontend.palette.surface
                    border.width: 1
                    border.color: frontend.palette.border

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 5
                        Text {
                            text: modelData.name
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(16)
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: modelData.description
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                        }
                        Text {
                            text: modelData.count
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(29)
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: modelData.status
                            color: modelData.good ? frontend.palette.success : frontend.palette.warning
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: modelData.detail
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            wrapMode: Text.WordWrap
                        }
                        VrButton {
                            Layout.fillWidth: true
                            text: modelData.action
                            onClicked: {
                                if (modelData.key === "video") frontend.setCurrentPage(5)
                                else studio.runSync(modelData.key)
                            }
                        }
                    }
                }
            }
        }

        Text {
            text: "Resumo VR"
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(15)
            font.weight: Font.DemiBold
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: [
                    { label: "Documentos", value: studio.dashboardMetrics.documents || "0" },
                    { label: "Pendentes", value: studio.dashboardMetrics.reviews || "0" },
                    { label: "OCR", value: studio.dashboardMetrics.ocr || "0" },
                    { label: "Conversas", value: studio.dashboardMetrics.conversations || "0" }
                ]
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 80
                    radius: Theme.radiusCard
                    color: frontend.palette.surface
                    border.width: 1
                    border.color: frontend.palette.border
                    Column {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6
                        Text { text: modelData.label; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                        Text { text: modelData.value; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(26); font.weight: Font.DemiBold }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 62
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border
            RowLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 8
                VrButton { text: "Sincronizar Wikis + KB"; variant: "primary"; onClicked: studio.runSync("wiki_kb") }
                VrButton { text: "Nova conversa VR"; onClicked: { chat.startNewChat(); frontend.setCurrentPage(1) } }
                VrButton { text: "Revisar classificações"; onClicked: frontend.setCurrentPage(4) }
                VrButton { text: "Abrir VR no Codex"; onClicked: studio.openVrInCodex() }
                Item { Layout.fillWidth: true }
            }
        }
    }
}
