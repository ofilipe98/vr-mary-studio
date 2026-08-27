import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import "../theme"

Item {
    id: root

    required property string title
    required property url iconSource
    property bool selected: false
    property bool compact: false
    signal activated()

    implicitHeight: 42
    implicitWidth: compact ? 42 : navLabel.implicitWidth + 70
    focus: false
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: "Abrir " + title
    Keys.onReturnPressed: activated()
    Keys.onEnterPressed: activated()
    Keys.onSpacePressed: activated()

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusControl
        color: root.selected ? frontend.palette.accessibleOrange
            : pointer.hovered || root.activeFocus ? frontend.palette.navHover : "transparent"
        border.width: root.activeFocus ? 2 : 0
        border.color: frontend.palette.brandYellow

        Behavior on color {
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Row {
        anchors.fill: parent
        anchors.leftMargin: root.compact ? 0 : 13
        spacing: 11

        Item {
            width: root.compact ? parent.width : Theme.iconSize
            height: parent.height

            Image {
                id: navIconSource
                visible: false
                anchors.centerIn: parent
                width: Theme.iconSize
                height: Theme.iconSize
                source: root.iconSource
                sourceSize.width: 24
                sourceSize.height: 24
                fillMode: Image.PreserveAspectFit
            }
            MultiEffect {
                anchors.centerIn: parent
                width: Theme.iconSize
                height: Theme.iconSize
                source: navIconSource
                colorization: 1.0
                colorizationColor: root.selected ? "#FFFFFF" : frontend.palette.navText
                opacity: root.selected ? 1 : 0.88
            }
        }

        Text {
            id: navLabel
            visible: !root.compact
            width: Math.max(0, parent.width - Theme.iconSize - 36)
            height: parent.height
            text: root.title
            color: root.selected ? "#FFFFFF" : frontend.palette.navText
            font.family: Theme.fontFamily
            font.pixelSize: 13
            font.weight: root.selected ? Font.DemiBold : Font.Medium
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    HoverHandler { id: pointer }
    TapHandler {
        onTapped: {
            root.forceActiveFocus()
            root.activated()
        }
    }

    ToolTip.visible: root.compact && pointer.hovered
    ToolTip.text: root.title
    ToolTip.delay: 450
}
