import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root

    property string title
    property string subtitle

    spacing: 3
    Text {
        text: root.title
        color: frontend.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.titleSize
        font.weight: Font.DemiBold
    }
    Text {
        Layout.fillWidth: true
        text: root.subtitle
        color: frontend.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySize
        elide: Text.ElideRight
    }
}
