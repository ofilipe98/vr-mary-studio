import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    Rectangle { anchors.fill: parent; color: frontend.palette.chatBackground }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: Theme.scaledGeometry(12)
        VrPageHeader {
            Layout.fillWidth: true
            title: "Logs"
            subtitle: "Eventos operacionais sem credenciais."
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "transparent"
            border.width: 0
            ListView {
                id: logList
                objectName: "logList"
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(14)
                clip: true
                reuseItems: true
                cacheBuffer: 240
                spacing: 2
                model: studio.logModel
                property bool followTail: true
                delegate: TextEdit {
                    required property string lineText
                    width: logList.width - 12
                    height: paintedHeight + 4
                    text: lineText
                    textFormat: TextEdit.PlainText
                    color: frontend.palette.text
                    readOnly: true
                    activeFocusOnPress: false
                    selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    font.family: Theme.monospaceFontFamily
                    font.pixelSize: Theme.monospaceFontSize(11)
                }
                ScrollBar.vertical: VrScrollBar { }
                onMovementStarted: followTail = atYEnd
                onMovementEnded: followTail = atYEnd
                onCountChanged: {
                    if (followTail)
                        Qt.callLater(function() { logList.positionViewAtEnd() })
                }
            }

            VrMiddleAutoScroller {
                objectName: "logAutoScroller"
                anchors.fill: logList
                target: logList
                enabled: logList.count > 0
            }

            VrEmptyState {
                anchors.centerIn: parent
                visible: logList.count === 0
                title: "Nenhum evento nesta sessão"
                description: "Credenciais configuradas são redigidas automaticamente."
            }
        }
    }
}
