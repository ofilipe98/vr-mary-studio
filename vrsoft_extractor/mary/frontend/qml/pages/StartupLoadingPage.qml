pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"

Rectangle {
    id: root
    objectName: "startupLoadingPage"
    color: Theme.palette.background

    Item {
        anchors.centerIn: parent
        width: Math.min(480, parent.width - 48)
        height: contentCol.implicitHeight

        ColumnLayout {
            id: contentCol
            anchors.fill: parent
            spacing: 20

            // Brand Header
            ColumnLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 8

                Image {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 48
                    Layout.preferredHeight: 48
                    source: (typeof frontend !== "undefined" && frontend && frontend.brandSymbolUrl) ? frontend.brandSymbolUrl : ""
                    sourceSize.width: 96
                    sourceSize.height: 96
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: (typeof frontend !== "undefined" && frontend && frontend.appName) ? frontend.appName : "VR Norte Studio"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeHeading
                    font.weight: Font.Bold
                    renderType: Theme.textRenderType
                }
            }

            // Status message
            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                spacing: 4

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: typeof bootstrap !== "undefined" && bootstrap ? bootstrap.statusMessage : "Preparando seu ambiente"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(15)
                    font.weight: Font.DemiBold
                    renderType: Theme.textRenderType
                }

                Text {
                    id: detailText
                    Layout.alignment: Qt.AlignHCenter
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: typeof bootstrap !== "undefined" && bootstrap ? bootstrap.detailMessage : "Carregando…"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    renderType: Theme.textRenderType
                    wrapMode: Text.WordWrap
                }
            }

            // Progress Bar
            VrProgressBar {
                id: progressBar
                Layout.fillWidth: true
                barHeight: 5
                indeterminate: typeof bootstrap === "undefined" || !bootstrap || (bootstrap.state !== "ready" && bootstrap.state !== "error")
                visible: typeof bootstrap === "undefined" || !bootstrap || bootstrap.state !== "error"
                accentColor: Theme.palette.brandOrange
            }

            // Step status card
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: stepsCol.implicitHeight + 20
                radius: 12
                color: Theme.palette.surfaceRaised
                border.width: 1
                border.color: Theme.palette.border

                ColumnLayout {
                    id: stepsCol
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    // Step 1: Apps
                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            text: "Aplicativos"
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                        }

                        Item { Layout.fillWidth: true }

                        Text {
                            text: {
                                if (typeof bootstrap === "undefined" || !bootstrap) return "Detectando…";
                                if (bootstrap.state === "initializing" || bootstrap.state === "loading_apps") return "Detectando…";
                                if (bootstrap.appsCount > 0 || bootstrap.state === "loading_versions" || bootstrap.state === "ready") {
                                    return bootstrap.appsCount + " encontrados";
                                }
                                if (bootstrap.state === "ready" && bootstrap.appsCount === 0) return "Nenhum aplicativo";
                                return "Aguardando…";
                            }
                            color: (typeof bootstrap !== "undefined" && bootstrap && (bootstrap.appsCount > 0 || bootstrap.state === "ready"))
                                ? Theme.palette.success : Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            font.weight: Font.Medium
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 1
                        color: Theme.palette.border
                    }

                    // Step 2: Versions & metadata
                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            text: "Versões e metadados"
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                        }

                        Item { Layout.fillWidth: true }

                        Text {
                            text: {
                                if (typeof bootstrap === "undefined" || !bootstrap) return "Aguardando…";
                                if (bootstrap.state === "initializing" || bootstrap.state === "loading_apps") return "Aguardando…";
                                if (bootstrap.state === "loading_versions") return "Carregando…";
                                if (bootstrap.state === "ready") return "Carregadas";
                                if (bootstrap.state === "error") return "Interrompido";
                                return "Aguardando…";
                            }
                            color: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.state === "ready")
                                ? Theme.palette.success : Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            font.weight: Font.Medium
                        }
                    }
                }
            }

            // Error Card
            Rectangle {
                visible: typeof bootstrap !== "undefined" && bootstrap && bootstrap.state === "error"
                Layout.fillWidth: true
                implicitHeight: errCol.implicitHeight + 24
                radius: 12
                color: Qt.alpha(Theme.palette.danger, 0.08)
                border.width: 1
                border.color: Theme.palette.danger

                ColumnLayout {
                    id: errCol
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    RowLayout {
                        spacing: 8
                        Layout.fillWidth: true

                        VrLineIcon {
                            Layout.preferredWidth: 18
                            Layout.preferredHeight: 18
                            kind: "warning"
                            foreground: Theme.palette.danger
                        }

                        Text {
                            text: "Não foi possível preparar o ambiente"
                            color: Theme.palette.danger
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.Bold
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: typeof bootstrap !== "undefined" && bootstrap ? bootstrap.errorMessage : ""
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        VrButton {
                            text: "Tentar novamente"
                            variant: "primary"
                            implicitHeight: 32
                            onClicked: {
                                if (typeof bootstrap !== "undefined" && bootstrap) {
                                    bootstrap.retryBootstrap();
                                }
                            }
                        }

                        VrButton {
                            text: "Revisar configurações"
                            variant: "secondary"
                            implicitHeight: 32
                            onClicked: {
                                if (typeof bootstrap !== "undefined" && bootstrap) {
                                    bootstrap.openSetup();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
