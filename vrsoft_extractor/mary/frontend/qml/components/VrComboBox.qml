import QtQuick
import QtQuick.Controls
import "../theme"

ComboBox {
    id: control

    property string popupObjectName: ""

    implicitHeight: Theme.controlHeight
    leftPadding: 13
    rightPadding: 34
    focusPolicy: Qt.StrongFocus
    font.family: Theme.fontFamily
    font.pixelSize: Theme.bodySize

    contentItem: Text {
        leftPadding: 0
        rightPadding: 0
        text: control.displayText
        color: frontend.palette.text
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
    }

    indicator: Text {
        x: control.width - width - 13
        y: (control.height - height) / 2 - 1
        text: "▾"
        color: frontend.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: 14
    }

    background: Rectangle {
        radius: Theme.radiusControl
        color: control.hovered ? frontend.palette.hover : frontend.palette.surfaceRaised
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? frontend.palette.focus : frontend.palette.border
    }

    delegate: ItemDelegate {
        required property int index
        required property var modelData

        width: control.width
        height: 40
        highlighted: control.highlightedIndex === index

        contentItem: Text {
            text: control.textRole ? modelData[control.textRole] : modelData
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideMiddle
        }
        background: Rectangle {
            color: parent.highlighted ? frontend.palette.selection : frontend.palette.surface
        }
    }

    popup: Popup {
        objectName: control.popupObjectName
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 12, 320)
        padding: 6

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }

        background: Rectangle {
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border
            radius: Theme.radiusPopup
        }
    }
}
