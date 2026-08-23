import QtQuick
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root

    property string pageTitle: ""

    VrCard {
        width: Math.min(parent.width, 720)
        height: 220
        anchors.centerIn: parent

        VrStatusBadge {
            text: "MIGRAÇÃO PENDENTE"
            kind: "warning"
        }
        Text {
            text: root.pageTitle
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: 24
            font.weight: Font.DemiBold
        }
        Text {
            Layout.fillWidth: true
            text: "Esta superfície ainda permanece no frontend Qt Widgets. Ela será ativada em QML somente depois dos testes de paridade."
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            wrapMode: Text.WordWrap
        }
        VrButton {
            text: "Voltar ao Dashboard"
            onClicked: frontend.setCurrentPage(0)
        }
    }
}
