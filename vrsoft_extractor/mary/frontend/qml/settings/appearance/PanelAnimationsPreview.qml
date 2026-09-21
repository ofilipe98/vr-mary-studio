import QtQuick
import QtQuick.Layouts
import "../../theme"

Rectangle {
    id: root

    objectName: "panelAnimationsPreview"
    property bool panelsOpen: true
    property int animDuration: frontend.reduceMotion ? 0 : frontend.rawPanelAnimationDurationMs

    implicitWidth: Theme.scaledGeometry(112)
    implicitHeight: Theme.scaledGeometry(40)
    radius: Theme.scaledGeometry(10)
    color: previewArea.containsMouse ? Theme.palette.hover : Theme.palette.background
    border.width: 1
    border.color: Theme.palette.controlBorder || Theme.palette.border
    clip: true

    MouseArea {
        id: previewArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.panelsOpen = !root.panelsOpen
    }

    Row {
        anchors.fill: parent
        anchors.margins: Theme.scaledGeometry(4)
        spacing: Theme.scaledGeometry(3)

        // Left sidebar
        Rectangle {
            id: leftBar
            height: parent.height
            width: root.panelsOpen ? 16 : 0
            radius: Theme.scaledGeometry(3)
            color: Theme.palette.previewSidebar || Theme.palette.surface
            clip: true

            Behavior on width {
                enabled: !frontend.reduceMotion && root.animDuration > 0
                NumberAnimation { duration: root.animDuration; easing.type: Easing.OutCubic }
            }
        }

        // Center content area
        Item {
            height: parent.height
            width: parent.width - leftBar.width - rightBar.width - 6

            Column {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.topMargin: Theme.scaledGeometry(3)
                spacing: Theme.scaledGeometry(3)

                Rectangle {
                    width: parent.width
                    height: 2
                    radius: 1
                    color: Qt.alpha(Theme.palette.text, .20)
                }
                Rectangle {
                    width: Math.floor(parent.width * 0.8)
                    height: 2
                    radius: 1
                    color: Qt.alpha(Theme.palette.text, .15)
                }
                Rectangle {
                    width: Math.floor(parent.width * 0.6)
                    height: 2
                    radius: 1
                    color: Qt.alpha(Theme.palette.text, .10)
                }
            }

            // Bottom drawer
            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: root.panelsOpen ? 6 : 0
                color: Qt.alpha(Theme.palette.text, .08)
                clip: true

                Behavior on height {
                    enabled: !frontend.reduceMotion && root.animDuration > 0
                    NumberAnimation { duration: root.animDuration; easing.type: Easing.OutCubic }
                }
            }
        }

        // Right panel
        Rectangle {
            id: rightBar
            height: parent.height
            width: root.panelsOpen ? 20 : 0
            radius: Theme.scaledGeometry(3)
            color: Theme.palette.mutedSurface || Theme.palette.surfaceRaised
            clip: true

            Behavior on width {
                enabled: !frontend.reduceMotion && root.animDuration > 0
                NumberAnimation { duration: root.animDuration; easing.type: Easing.OutCubic }
            }
        }
    }
}
