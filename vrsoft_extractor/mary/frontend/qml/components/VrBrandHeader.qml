import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root

    property bool showToggle: false
    property color primaryColor: frontend.palette.text
    property color toggleColor: frontend.palette.mutedText
    signal toggleRequested()
    signal brandActivated()

    implicitHeight: 62

    RowLayout {
        anchors.fill: parent
        spacing: 10

        Item {
            Layout.preferredWidth: 40
            Layout.preferredHeight: 40

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
                font.pixelSize: Theme.fontSize(16)
                font.weight: Font.DemiBold
                font.letterSpacing: 1.05
            }
            Text {
                text: "STUDIO"
                color: frontend.palette.brandYellow
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(9)
                font.weight: Font.DemiBold
                font.letterSpacing: 1.7
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
