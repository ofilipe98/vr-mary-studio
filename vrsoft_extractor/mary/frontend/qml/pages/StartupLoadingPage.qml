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
        // Same compact central envelope as the setup page: concentrated
        // content with generous outer margins on wide windows.
        // Tuned for the ~760 px bootstrap window (content ~520 px) so
        // setup and loading read as parts of the same flow.
        anchors.centerIn: parent
        width: Math.min(520, parent.width - 64)
        height: Math.min(contentCol.implicitHeight, parent.height - 32)

        ColumnLayout {
            id: contentCol
            anchors.fill: parent
            spacing: Theme.scaledGeometry(16)

            // Brand Header
            ColumnLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: Theme.scaledGeometry(8)

                Image {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: Theme.scaledGeometry(48)
                    Layout.preferredHeight: Theme.scaledGeometry(48)
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
                spacing: Theme.scaledGeometry(4)

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
                objectName: "startupCatalogProgress"
                Layout.fillWidth: true
                barHeight: Theme.scaledGeometry(6)
                indeterminate: typeof bootstrap === "undefined" || !bootstrap
                    || (bootstrap.state !== "ready" && bootstrap.state !== "error")
                visible: typeof bootstrap === "undefined" || !bootstrap || bootstrap.state !== "error"
                accentColor: Theme.palette.brandOrange
                accessibleName: "Carregando ambiente"
            }

            // Step status card
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: stepsCol.implicitHeight + 20
                radius: Theme.scaledGeometry(12)
                color: Theme.palette.surfaceRaised
                border.width: 1
                border.color: Theme.palette.border

                ColumnLayout {
                    id: stepsCol
                    anchors.fill: parent
                    anchors.margins: Theme.scaledGeometry(12)
                    spacing: Theme.scaledGeometry(10)

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
            // NOTE: children use anchor/binding geometry only (no nested
            // layouts). A nested ColumnLayout sized by anchors does not run
            // its arrangement pass for a card driven by a `visible` binding,
            // leaving children at implicit widths overflowing the card.
            Rectangle {
                visible: typeof bootstrap !== "undefined" && bootstrap && bootstrap.state === "error"
                Layout.fillWidth: true
                implicitHeight: errRetryButton.y + errRetryButton.height + 12
                radius: Theme.scaledGeometry(12)
                color: Qt.alpha(Theme.palette.danger, 0.08)
                border.width: 1
                border.color: Theme.palette.danger

                VrLineIcon {
                    id: errIcon
                    x: 12
                    y: 12
                    width: Theme.iconMedium
                    height: Theme.iconMedium
                    kind: "warning"
                    foreground: Theme.palette.danger
                }

                Text {
                    id: errTitle
                    x: errIcon.x + errIcon.width + 8
                    y: 12
                    width: parent.width - x - 12
                    text: "Não foi possível preparar o ambiente"
                    color: Theme.palette.danger
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.Bold
                    wrapMode: Text.WordWrap
                    renderType: Theme.textRenderType
                }

                Text {
                    id: errMessage
                    x: 12
                    y: errTitle.y + errTitle.height + 12
                    width: parent.width - 24
                    text: typeof bootstrap !== "undefined" && bootstrap ? bootstrap.errorMessage : ""
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    wrapMode: Text.WordWrap
                    renderType: Theme.textRenderType
                }

                VrButton {
                    id: errRetryButton
                    x: 12
                    y: errMessage.y + errMessage.height + 12
                    width: (parent.width - 24 - 8) / 2
                    implicitHeight: Theme.scaledGeometry(32)
                    text: "Tentar novamente"
                    variant: "primary"
                    onClicked: {
                        if (typeof bootstrap !== "undefined" && bootstrap) {
                            bootstrap.retryBootstrap();
                        }
                    }
                }

                VrButton {
                    x: errRetryButton.x + errRetryButton.width + 8
                    y: errRetryButton.y
                    width: errRetryButton.width
                    implicitHeight: Theme.scaledGeometry(32)
                    text: "Revisar configurações"
                    variant: "secondary"
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
