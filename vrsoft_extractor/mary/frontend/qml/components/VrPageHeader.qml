import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root

    property string title
    property string subtitle
    property bool compact: false

    spacing: Theme.scaledGeometry(3)
    Text {
        Layout.fillWidth: true
        text: root.title
        color: Theme.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: root.compact ? Theme.fontSize(24) : Theme.titleSize
        font.weight: Font.DemiBold
        lineHeight: Theme.headingLineHeight
        wrapMode: Text.WordWrap
        renderType: Theme.textRenderType
    }
    Text {
        Layout.fillWidth: true
        text: root.subtitle
        color: Theme.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(13)
        wrapMode: Text.WordWrap
        lineHeight: Theme.bodyLineHeight
        renderType: Theme.textRenderType
    }
}
