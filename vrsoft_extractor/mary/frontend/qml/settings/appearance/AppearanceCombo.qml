import QtQuick
import QtQuick.Controls
import "../../theme"
import "../../components"

ComboBox {
    id: control
    implicitWidth: 160; implicitHeight: Math.max(28, font.pixelSize + 14)
    leftPadding: 10; rightPadding: 24
    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
    background: Rectangle {
        radius: 9
        color: control.hovered ? Theme.palette.hover : Theme.palette.chatControl
        border.color: control.activeFocus ? Theme.palette.focus : (Theme.palette.controlBorder || Theme.palette.border)
    }
    contentItem: Text {
        text: control.displayText; color: Theme.palette.text; font: control.font
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: VrLineIcon {
        x: control.width - width - 8; y: (control.height - height) / 2
        width: 10; height: 10; kind: "chevronDown"; foreground: Theme.palette.mutedText
    }
    delegate: ItemDelegate {
        required property int index
        required property var modelData
        width: control.width
        text: control.textRole ? modelData[control.textRole] : modelData
        font: control.font
        contentItem: Text { text: parent.text; color: Theme.palette.text; font: control.font }
        background: Rectangle { color: parent.highlighted ? Theme.palette.hover : "transparent" }
        highlighted: control.highlightedIndex === index
    }
    popup: Popup {
        y: control.height + 4; width: control.width
        implicitHeight: Math.min(300, contentItem.implicitHeight + 8)
        padding: 4
        background: Rectangle { color: Qt.alpha(Theme.palette.surface, Theme.glassOpacity); radius: 9; border.color: Theme.palette.border }
        contentItem: ListView {
            clip: true; implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }
    }
}
