import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root

    property bool showToggle: false
    property color primaryColor: Theme.palette.text
    property color toggleColor: Theme.palette.mutedText
    signal toggleRequested()
    signal brandActivated()

    implicitHeight: 62

    RowLayout {
        anchors.fill: parent
        spacing: 10

        Item {
            Layout.preferredWidth: 40
            Layout.preferredHeight: 40

            Rectangle {
                objectName: "environmentArtwork"
                anchors.fill: parent; radius: 10
                visible: frontend.environmentStage !== "" && frontend.environmentIdentification === "artwork"
                color: Qt.alpha(Theme.palette.focus, .2)
                border.color: Theme.palette.focus
            }

            Image {
                anchors.fill: parent
                source: frontend.brandSymbolUrl
                sourceSize.width: 96
                sourceSize.height: 96
                fillMode: Image.PreserveAspectFit
            }

            TapHandler { onTapped: root.brandActivated() }
        }

        Column {
            Layout.fillWidth: true
            spacing: 0

            Text {
                text: "VR NORTE"
                color: root.primaryColor
                font.family: Theme.fontFamily
                font.pixelSize: Theme.headingSize
                font.weight: Font.DemiBold
                font.letterSpacing: 1.05
                renderType: Theme.textRenderType
            }
            Row {
                spacing: 6
                Text {
                    text: "STUDIO"
                    color: Theme.palette.brandYellow
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMicro
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.7
                    renderType: Theme.textRenderType
                }
                Rectangle {
                    objectName: "environmentVersionPill"
                    visible: frontend.environmentStage !== "" && frontend.environmentIdentification === "pill"
                    width: stageLabel.implicitWidth + 10; height: stageLabel.implicitHeight + 2; radius: height / 2
                    color: Theme.palette.accentSoft
                    Text {
                        id: stageLabel; anchors.centerIn: parent
                        text: frontend.appVersion + " " + frontend.environmentStage
                        color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro
                        renderType: Theme.textRenderType
                    }
                }
            }
        }

        VrIconButton {
            visible: root.showToggle
            implicitWidth: 32
            implicitHeight: 32
            iconKind: "panelLeft"
            foreground: root.toggleColor
            ToolTip.visible: hovered
            ToolTip.text: "Recolher barra lateral"
            Accessible.name: "Recolher barra lateral"
            onClicked: root.toggleRequested()
        }
    }
}
