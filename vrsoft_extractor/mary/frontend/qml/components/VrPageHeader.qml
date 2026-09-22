import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root

    property string title
    property string subtitle
    property bool compact: false

    readonly property real resolvedTitleSize: root.compact ? Theme.fontSizeTitle : Theme.titleSize

    spacing: Theme.scaledGeometry(3)
    Text {
        Layout.fillWidth: true
        text: root.title
        color: Theme.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: root.resolvedTitleSize
        font.weight: Font.DemiBold
        font.letterSpacing: Theme.tracking(root.resolvedTitleSize, Theme.trackingTight)
        lineHeight: Theme.headingLineHeight
        wrapMode: Text.WordWrap
        renderType: Theme.textRenderType
    }
    Text {
        Layout.fillWidth: true
        text: root.subtitle
        color: Theme.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeControl
        wrapMode: Text.WordWrap
        lineHeight: Theme.bodyLineHeight
        renderType: Theme.textRenderType
    }
}
