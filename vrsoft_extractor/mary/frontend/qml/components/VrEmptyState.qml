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
        color: Theme.palette.selection
        Text {
            anchors.centerIn: parent
            text: "—"
            color: Theme.palette.brandOrange
            font.pixelSize: Theme.fontSize(22)
        }
    }
    Text {
        Layout.fillWidth: true
        text: root.title
        color: Theme.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.headingSize
        font.weight: Font.DemiBold
        lineHeight: Theme.headingLineHeight
        horizontalAlignment: Text.AlignHCenter
    }
    Text {
        Layout.fillWidth: true
        text: root.description
        color: Theme.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySize
        wrapMode: Text.WordWrap
        lineHeight: Theme.bodyLineHeight
        horizontalAlignment: Text.AlignHCenter
    }
    VrButton {
        visible: root.actionText.length > 0
        Layout.alignment: Qt.AlignHCenter
        text: root.actionText
        onClicked: root.action()
    }
}
