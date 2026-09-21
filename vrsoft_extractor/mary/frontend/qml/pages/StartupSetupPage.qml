pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"

Rectangle {
    id: root
    objectName: "startupSetupPage"
    color: Theme.palette.background

    ScrollView {
        id: scroller
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            // Compact central envelope: same contained card principle as the
            // loading page, with generous outer margins on wide windows.
            // Tuned for the ~760 px bootstrap window (content ~600 px).
            width: Math.min(600, scroller.width - 64)
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Theme.scaledGeometry(16)

            Item { Layout.preferredHeight: Theme.scaledGeometry(12) }

            // Header
            RowLayout {
                spacing: Theme.scaledGeometry(12)
                Layout.fillWidth: true

                Image {
                    Layout.preferredWidth: Theme.scaledGeometry(36)
                    Layout.preferredHeight: Theme.scaledGeometry(36)
                    source: (typeof frontend !== "undefined" && frontend && frontend.brandSymbolUrl) ? frontend.brandSymbolUrl : ""
                    sourceSize.width: 72
                    sourceSize.height: 72
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }

                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true

                    Text {
                        text: "Configuração Inicial"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeHeading
                        font.weight: Font.Bold
                        renderType: Theme.textRenderType
                    }

                    Text {
                        text: "Defina a pasta local de trabalho e as credenciais para inicializar o VRStudio."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        renderType: Theme.textRenderType
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            // Error banner if any
            Rectangle {
                id: errorBanner
                visible: typeof bootstrap !== "undefined" && bootstrap && bootstrap.errorMessage.length > 0
                Layout.fillWidth: true
                implicitHeight: errorLayout.implicitHeight + 16
                radius: Theme.scaledGeometry(8)
                color: Qt.alpha(Theme.palette.danger, 0.12)
                border.width: 1
                border.color: Theme.palette.danger

                RowLayout {
                    id: errorLayout
                    anchors.fill: parent
                    anchors.margins: Theme.scaledGeometry(10)
                    spacing: Theme.scaledGeometry(8)

                    VrLineIcon {
                        Layout.preferredWidth: Theme.scaledGeometry(16)
                        Layout.preferredHeight: Theme.scaledGeometry(16)
                        kind: "warning"
                        foreground: Theme.palette.danger
                    }

                    Text {
                        Layout.fillWidth: true
                        text: typeof bootstrap !== "undefined" && bootstrap ? bootstrap.errorMessage : ""
                        color: Theme.palette.danger
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.Medium
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Section 1: Local Root
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.scaledGeometry(6)

                Text {
                    text: "Repositório local de documentação VR"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "Diretório onde ficam armazenados o banco de dados e arquivos locais."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.scaledGeometry(8)

                    VrTextField {
                        id: rootField
                        objectName: "setupRootField"
                        Layout.fillWidth: true
                        implicitHeight: Theme.scaledGeometry(34)
                        placeholderText: "Ex: D:\\Codex\\VRProject"
                        text: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues) ? (bootstrap.settingsValues.root || "") : ""
                    }

                    VrButton {
                        text: "Procurar…"
                        variant: "secondary"
                        implicitHeight: Theme.scaledGeometry(34)
                        onClicked: {
                            if (typeof bootstrap !== "undefined" && bootstrap) {
                                var chosen = bootstrap.chooseKnowledgeRoot();
                                if (chosen && chosen.length > 0) {
                                    rootField.text = chosen;
                                }
                            }
                        }
                    }
                }
            }

            // Section 2: Credenciais
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.scaledGeometry(12)

                Text {
                    text: "Credenciais de sincronização"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.DemiBold
                }

                // Movidesk
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: movideskCol.implicitHeight + 20
                    radius: Theme.scaledGeometry(10)
                    color: Theme.palette.surfaceRaised
                    border.width: 1
                    border.color: Theme.palette.border

                    ColumnLayout {
                        id: movideskCol
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(12)
                        spacing: Theme.scaledGeometry(8)

                        RowLayout {
                            Layout.fillWidth: true

                            Text {
                                text: "Movidesk"
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.Medium
                            }

                            Item { Layout.fillWidth: true }

                            VrProviderStatus {
                                text: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues && bootstrap.settingsValues.movideskPasswordConfigured) ? "Senha configurada" : "Pendente"
                                tone: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues && bootstrap.settingsValues.movideskPasswordConfigured) ? "success" : "muted"
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: root.width < 500 ? 1 : 2
                            columnSpacing: Theme.scaledGeometry(8)
                            rowSpacing: Theme.scaledGeometry(8)

                            VrTextField {
                                id: movideskEmail
                                objectName: "setupMovideskEmail"
                                Layout.fillWidth: true
                                implicitHeight: Theme.scaledGeometry(34)
                                placeholderText: "Email Movidesk"
                                text: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues) ? (bootstrap.settingsValues.movideskEmail || "") : ""
                            }

                            VrTextField {
                                id: movideskPassword
                                objectName: "setupMovideskPassword"
                                Layout.fillWidth: true
                                implicitHeight: Theme.scaledGeometry(34)
                                echoMode: TextInput.Password
                                placeholderText: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues && bootstrap.settingsValues.movideskPasswordConfigured) ? "Senha configurada" : "Senha Movidesk"
                                text: ""
                            }
                        }
                    }
                }

                // Endoo Wiki
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: endooCol.implicitHeight + 20
                    radius: Theme.scaledGeometry(10)
                    color: Theme.palette.surfaceRaised
                    border.width: 1
                    border.color: Theme.palette.border

                    ColumnLayout {
                        id: endooCol
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(12)
                        spacing: Theme.scaledGeometry(8)

                        RowLayout {
                            Layout.fillWidth: true

                            Text {
                                text: "Wiki Endoo"
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.Medium
                            }

                            Item { Layout.fillWidth: true }

                            VrProviderStatus {
                                text: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues && bootstrap.settingsValues.endooPasswordConfigured) ? "Senha configurada" : "Pendente"
                                tone: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues && bootstrap.settingsValues.endooPasswordConfigured) ? "success" : "muted"
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: root.width < 500 ? 1 : 2
                            columnSpacing: Theme.scaledGeometry(8)
                            rowSpacing: Theme.scaledGeometry(8)

                            VrTextField {
                                id: endooEmail
                                objectName: "setupEndooEmail"
                                Layout.fillWidth: true
                                implicitHeight: Theme.scaledGeometry(34)
                                placeholderText: "Email Wiki Endoo"
                                text: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues) ? (bootstrap.settingsValues.endooEmail || "") : ""
                            }

                            VrTextField {
                                id: endooPassword
                                objectName: "setupEndooPassword"
                                Layout.fillWidth: true
                                implicitHeight: Theme.scaledGeometry(34)
                                echoMode: TextInput.Password
                                placeholderText: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues && bootstrap.settingsValues.endooPasswordConfigured) ? "Senha configurada" : "Senha Wiki Endoo"
                                text: ""
                            }
                        }
                    }
                }
            }

            // Section 3: Sync & Diagnostic
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.scaledGeometry(8)

                Text {
                    text: "Sincronização e diagnóstico"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.DemiBold
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.scaledGeometry(12)

                    Text {
                        text: "Frequência de sincronização:"
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                    }

                    VrComboBox {
                        id: interval
                        objectName: "setupInterval"
                        Layout.preferredWidth: Theme.scaledGeometry(210)
                        implicitHeight: Theme.scaledGeometry(34)
                        model: ["A cada 15 minutos", "A cada 30 minutos", "A cada 1 hora", "A cada 2 horas", "A cada 4 horas", "A cada 8 horas", "A cada 24 horas"]
                        property var values: ["15", "30", "60", "120", "240", "480", "1440"]
                        Component.onCompleted: {
                            var current = (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues) ? (bootstrap.settingsValues.interval || "120") : "120"
                            var found = values.indexOf(current)
                            currentIndex = found >= 0 ? found : 3
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: diagText.implicitHeight + 16
                    radius: Theme.scaledGeometry(8)
                    color: Theme.palette.surfaceRaised
                    border.width: 1
                    border.color: Theme.palette.border

                    Text {
                        id: diagText
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(8)
                        text: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.settingsValues) ? (bootstrap.settingsValues.diagnostic || "") : ""
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Footer Action
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.scaledGeometry(8)
                spacing: Theme.scaledGeometry(12)

                Item { Layout.fillWidth: true }

                VrButton {
                    id: saveButton
                    objectName: "setupSaveButton"
                    text: (typeof bootstrap !== "undefined" && bootstrap && bootstrap.isBusy) ? "Salvando…" : "Salvar e Continuar"
                    variant: "primary"
                    implicitHeight: Theme.scaledGeometry(36)
                    implicitWidth: Theme.scaledGeometry(160)
                    enabled: rootField.text.trim().length > 0 && !(typeof bootstrap !== "undefined" && bootstrap && bootstrap.isBusy)
                    onClicked: {
                        if (typeof bootstrap !== "undefined" && bootstrap) {
                            var selectedInterval = interval.values[interval.currentIndex] || "120";
                            bootstrap.saveSetup(
                                rootField.text.trim(),
                                movideskEmail.text.trim(),
                                movideskPassword.text,
                                endooEmail.text.trim(),
                                endooPassword.text,
                                selectedInterval
                            );
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: Theme.scaledGeometry(20) }
        }
    }
}
