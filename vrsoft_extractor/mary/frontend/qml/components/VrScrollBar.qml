import QtQuick
import QtQuick.Controls

ScrollBar {
    id: root

    policy: ScrollBar.AsNeeded
    visible: policy === ScrollBar.AlwaysOn || size < 0.999
    minimumSize: 0.08
    implicitWidth: 9
    implicitHeight: 9
    padding: 2

    background: Rectangle {
        color: "transparent"
    }

    contentItem: Rectangle {
        implicitWidth: 5
        implicitHeight: 5
        radius: width / 2
        color: frontend.palette.mutedText
        opacity: root.pressed ? 0.78 : root.hovered ? 0.58 : 0.34

        Behavior on opacity {
            NumberAnimation { duration: 120 }
        }
    }
}
