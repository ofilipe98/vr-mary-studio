import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    Rectangle { anchors.fill: parent; color: frontend.palette.background }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: 12
        VrPageHeader {
            Layout.fillWidth: true
            title: "Logs"
            subtitle: "Eventos operacionais sem credenciais."
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radiusCard
            color: frontend.palette.surfaceRaised
            border.width: 1
            border.color: frontend.palette.border
            ScrollView {
                anchors.fill: parent
                anchors.margins: 14
                TextArea {
                    width: parent.width
                    text: studio.logText.length ? studio.logText : "Nenhum evento nesta sessão. Senhas e cookies nunca são exibidos."
                    color: studio.logText.length ? frontend.palette.text : frontend.palette.mutedText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextArea.Wrap
                    background: Item { }
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                }
            }
        }
    }
}
