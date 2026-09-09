import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../components"

Popup {
    id: modal

    property string feedbackMessage: ""
    property bool isError: false

    signal themeImported(string themeId)

    modal: true
    focus: true
    dim: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(620, parent ? parent.width - 40 : 620)
    height: Math.min(520, parent ? parent.height - 40 : 520)
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: Theme.radiusCard
        color: Theme.palette.surface
        border.width: 1
        border.color: Theme.palette.border
    }

    contentItem: ColumnLayout {
        spacing: 0

        // Header
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 52
            color: Theme.palette.surfaceRaised
            radius: Theme.radiusCard

            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: 10
                color: Theme.palette.surfaceRaised
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceLg
                anchors.rightMargin: Theme.spaceLg

                Text {
                    text: "Importar Tema JSON"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.subtitleSize
                    font.weight: Font.DemiBold
                    color: Theme.palette.text
                    Layout.fillWidth: true
                }

                VrIconButton {
                    iconKind: "close"
                    ToolTip.text: "Fechar"
                    onClicked: modal.close()
                }
            }
        }

        // Content
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            anchors.margins: Theme.spaceLg
            spacing: Theme.spaceMd

            Text {
                text: "Cole abaixo a definição em JSON do tema. Formatos suportados: Harness nativo, T3 Code ou VS Code."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.captionSize
                color: Theme.palette.mutedText
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radiusControl
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: Theme.spaceSm

                    TextArea {
                        id: jsonArea
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.monospaceFontSize(12)
                        color: Theme.palette.text
                        placeholderText: "{\n  \"name\": \"Meu Tema\",\n  \"canvas\": \"#1a1b26\",\n  \"accent\": \"#7aa2f7\"\n}"
                        placeholderTextColor: Theme.palette.mutedText
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                    }
                }
            }

            // Feedback Banner
            Rectangle {
                visible: modal.feedbackMessage.length > 0
                Layout.fillWidth: true
                implicitHeight: 36
                radius: Theme.radiusSmall
                color: modal.isError ? Qt.alpha(Theme.palette.danger, 0.15) : Qt.alpha(Theme.palette.success, 0.15)
                border.width: 1
                border.color: modal.isError ? Theme.palette.danger : Theme.palette.success

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceMd

                    Text {
                        text: modal.feedbackMessage
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.captionSize
                        color: modal.isError ? Theme.palette.danger : Theme.palette.success
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }
        }

        // Footer Actions
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 56
            color: Theme.palette.surfaceRaised
            radius: Theme.radiusCard

            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 10
                color: Theme.palette.surfaceRaised
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceLg
                anchors.rightMargin: Theme.spaceLg
                spacing: Theme.spaceMd

                Item { Layout.fillWidth: true }

                VrButton {
                    text: "Cancelar"
                    variant: "secondary"
                    onClicked: modal.close()
                }

                VrButton {
                    text: "Importar"
                    variant: "primary"
                    enabled: jsonArea.text.trim().length > 0
                    onClicked: {
                        var res = frontend.importThemeJson(jsonArea.text)
                        if (res && res.success) {
                            modal.isError = false
                            modal.feedbackMessage = res.message
                            modal.themeImported(res.themeId)
                            modal.close()
                        } else {
                            modal.isError = true
                            modal.feedbackMessage = res ? res.message : "Falha na importação do JSON."
                        }
                    }
                }
            }
        }
    }
}
