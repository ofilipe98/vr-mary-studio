import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root
    property string title: ""
    default property alias content: body.data
    spacing: Theme.scaledGeometry(8)
    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.palette.chatDivider }
    Text {
        Layout.topMargin: Theme.scaledGeometry(4)
        text: root.title; color: Theme.palette.headingText
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold
    }
    ColumnLayout { id: body; Layout.fillWidth: true; spacing: Theme.scaledGeometry(6) }
}
