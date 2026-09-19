import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../components"

Button {
    id: control
    property string iconKind: ""
    property bool quiet: false
    implicitHeight: Math.max(24, content.implicitHeight + 8)
    implicitWidth: content.implicitWidth + (quiet ? 8 : 12)
    padding: quiet ? 4 : 6
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    background: Rectangle {
        radius: 7
        color: control.hovered ? Theme.palette.hover : control.quiet ? "transparent" : Theme.palette.chatControl
        border.width: control.visualFocus || !control.quiet ? 1 : 0
        border.color: control.visualFocus ? Theme.palette.focus : (Theme.palette.controlBorder || Theme.palette.border)
    }
    contentItem: RowLayout {
        id: content
        spacing: 3
        VrLineIcon {
            visible: control.iconKind !== ""
            kind: control.iconKind
            Layout.preferredWidth: 14; Layout.preferredHeight: 14
            foreground: Theme.palette.mutedText
        }
        Text {
            visible: control.text !== ""
            text: control.text; color: Theme.palette.text
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold
        }
    }
}
