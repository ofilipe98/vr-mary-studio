import QtQuick
import QtQuick.Controls
import "../theme"

CheckBox {
    id: control

    spacing: 8
    focusPolicy: Qt.StrongFocus

    indicator: Rectangle {
        implicitWidth: 20
        implicitHeight: 20
        x: control.leftPadding
        y: parent.height / 2 - height / 2
        radius: 5
        color: control.checked ? Theme.palette.accessibleOrange : Theme.palette.surfaceRaised
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.border

        Text {
            anchors.centerIn: parent
            text: "✓"
            visible: control.checked
            color: "#FFFFFF"
            font.pixelSize: Theme.fontSize(13)
            font.weight: Font.Bold
        }
    }

    contentItem: Text {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        color: Theme.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySize
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
    }
}
