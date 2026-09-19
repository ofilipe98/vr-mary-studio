import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../components"

Popup {
    id: modal

    property string themeName: ""
    property string jsonContent: ""
    property bool copiedFeedback: false

    modal: true
    focus: true
    dim: true
    Overlay.modal: Rectangle { color: Qt.alpha(Theme.palette.background, .85) }
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(620, parent ? parent.width - 40 : 620)
    height: Math.min(520, parent ? parent.height - 40 : 520)
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: Theme.radiusCard
        color: Qt.alpha(Theme.palette.surface, Theme.glassOpacity)
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
                    text: "Exportar Tema: " + modal.themeName
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.subtitleSize
                    font.weight: Font.DemiBold
                    color: Theme.palette.text
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                VrIconButton {
                    iconKind: "close"
                    Accessible.name: "Fechar"
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
                text: "O JSON abaixo contém o tema completo. Você pode compartilhá-lo ou importá-lo em outra instalação do VRStudio."
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
                        readOnly: true
                        font.family: Theme.monospaceFontFamily
                        font.pixelSize: Theme.monospaceFontSize(12)
                        color: Theme.palette.text
                        text: modal.jsonContent
                        selectByMouse: true
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

                Text {
                    visible: modal.copiedFeedback
                    text: "Copiado para a área de transferência!"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    color: Theme.palette.success
                }

                Item { Layout.fillWidth: true }

                VrButton {
                    text: "Copiar JSON"
                    variant: "primary"
                    onClicked: {
                        jsonArea.selectAll()
                        jsonArea.copy()
                        modal.copiedFeedback = true
                    }
                }

                VrButton {
                    text: "Fechar"
                    variant: "secondary"
                    onClicked: modal.close()
                }
            }
        }
    }
}
