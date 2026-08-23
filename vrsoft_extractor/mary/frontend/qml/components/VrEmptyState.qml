import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root

    property string title
    property string description
    property string actionText: ""
    signal action()

    width: Math.min(parent ? parent.width - 40 : 520, 560)
    spacing: 12

    Rectangle {
        Layout.alignment: Qt.AlignHCenter
        width: 42
        height: 42
        radius: 21
        color: frontend.palette.selection
        Text {
            anchors.centerIn: parent
            text: "—"
            color: frontend.palette.brandOrange
            font.pixelSize: 22
        }
    }
    Text {
        Layout.fillWidth: true
        text: root.title
        color: frontend.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.headingSize
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
    }
    Text {
        Layout.fillWidth: true
        text: root.description
        color: frontend.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySize
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
    }
    VrButton {
        visible: root.actionText.length > 0
        Layout.alignment: Qt.AlignHCenter
        text: root.actionText
        onClicked: root.action()
    }
}
