import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root

    Rectangle { anchors.fill: parent; color: frontend.palette.chatBackground }

    ScrollView {
        id: dashboardScroll
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
        width: dashboardScroll.availableWidth
        spacing: Theme.spaceLg

        VrPageHeader {
            Layout.fillWidth: true
            title: "Visão geral"
            subtitle: "Wikis, KB e Vídeos possuem saúde, inventário e ações independentes."
        }

        GridLayout {
            Layout.fillWidth: true
            columns: width < 820 ? 1 : 2
            columnSpacing: Theme.spaceMd
            rowSpacing: Theme.spaceMd

            Repeater {
                model: studio.dashboardSources
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(Theme.scaledGeometry(210), sourceContent.implicitHeight + Theme.space2Xl)
                    color: Theme.palette.surface
                    radius: Theme.radiusCard
                    border.width: 1
                    border.color: Theme.palette.border

                    ColumnLayout {
                        id: sourceContent
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(16)
                        spacing: Theme.scaledGeometry(5)
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

                    Rectangle {
                        visible: false
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: frontend.palette.chatDivider
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

        GridLayout {
            Layout.fillWidth: true
            columns: width < Theme.scaledGeometry(480) ? 2 : 4
            columnSpacing: Theme.scaledGeometry(6)
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
                    Layout.preferredHeight: Theme.scaledGeometry(80)
                    color: "transparent"
                    Column {
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(10)
                        spacing: Theme.scaledGeometry(6)
                        Text { text: modelData.label; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                        Text { text: modelData.value; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(26); font.weight: Font.DemiBold }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: dashboardActions.implicitHeight + Theme.spaceLg
            color: "transparent"
            GridLayout {
                id: dashboardActions
                columns: width < Theme.scaledGeometry(800) ? (width < Theme.scaledGeometry(480) ? 1 : 2) : 4
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(10)
                columnSpacing: Theme.scaledGeometry(8)
                VrButton { text: "Sincronizar Wikis + KB"; variant: "primary"; onClicked: studio.runSync("wiki_kb") }
                VrButton { text: "Nova conversa VR"; onClicked: { chat.startNewChat(); frontend.setCurrentPage(1) } }
                VrButton { text: "Revisar classificações"; onClicked: frontend.setCurrentPage(4) }
                VrButton { text: "Abrir VR no Codex"; onClicked: studio.openVrInCodex() }
            }
        }
        }
    }
}
