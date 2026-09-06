import QtQuick
import "../theme"

Item {
    id: root

    required property Flickable target
    property bool active: false
    property point origin: Qt.point(0, 0)
    property real pointerY: origin.y

    function stop() {
        active = false
    }

    function beginAt(position) {
        origin = Qt.point(position.x, position.y)
        pointerY = position.y
        active = true
    }

    HoverHandler {
        id: pointerTracker
        enabled: root.active && root.visible
        onPointChanged: root.pointerY = point.position.y
    }

    TapHandler {
        acceptedButtons: Qt.MiddleButton
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: function(eventPoint) {
            if (root.active)
                root.stop()
            else
                root.beginAt(eventPoint.position)
        }
    }

    TapHandler {
        enabled: root.active
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onTapped: root.stop()
    }

    Timer {
        interval: 16
        repeat: true
        running: root.active && root.enabled && root.target
        onTriggered: {
            var delta = root.pointerY - root.origin.y
            var deadZone = 18
            if (Math.abs(delta) <= deadZone)
                return
            var direction = delta < 0 ? -1 : 1
            var velocity = direction * Math.min(34,
                1.2 + (Math.abs(delta) - deadZone) / 7)
            var maximum = Math.max(0,
                root.target.contentHeight - root.target.height)
            root.target.contentY = Math.max(0,
                Math.min(maximum, root.target.contentY + velocity))
        }
    }

    Rectangle {
        visible: root.active
        x: Math.max(2, Math.min(root.width - width - 2,
            root.origin.x - width / 2))
        y: Math.max(2, Math.min(root.height - height - 2,
            root.origin.y - height / 2))
        width: 30
        height: 44
        radius: 15
        z: 1000
        color: Theme.palette.chatComposer
        border.width: 1
        border.color: Theme.palette.focus

        Column {
            anchors.centerIn: parent
            spacing: 3
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "⌃"
                color: root.pointerY < root.origin.y - 18
                    ? Theme.palette.text : Theme.palette.mutedText
                font.pixelSize: 13
            }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 5
                height: 5
                radius: 3
                color: Theme.palette.brandOrange
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "⌄"
                color: root.pointerY > root.origin.y + 18
                    ? Theme.palette.text : Theme.palette.mutedText
                font.pixelSize: 13
            }
        }
    }
}
