import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root

    property string title
    property string subtitle
    property bool compact: false

    spacing: 3
    Text {
        text: root.title
        color: Theme.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: root.compact ? Theme.fontSize(24) : Theme.titleSize
        font.weight: Font.DemiBold
        lineHeight: Theme.headingLineHeight
    }
    Text {
        Layout.fillWidth: true
        text: root.subtitle
        color: Theme.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: root.compact ? Theme.fontSize(13) : Theme.bodySize
        elide: Text.ElideRight
    }
}
