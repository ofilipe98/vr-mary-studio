import QtQuick
import QtQuick.Controls
import "../theme"

Item {
    id: root

    property string title: ""
    property var iconSource: ""
    property bool selected: false
    property bool compact: false
    signal activated()

    implicitHeight: 34
    implicitWidth: compact ? 34 : navLabel.implicitWidth + 50
    focus: false
    activeFocusOnTab: true
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && navTap.pressed ? 0.975 : 1
    Accessible.role: Accessible.Button
    Accessible.name: "Abrir " + title
    Keys.onReturnPressed: activated()
    Keys.onEnterPressed: activated()
    Keys.onSpacePressed: activated()

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        radius: 6
        color: root.selected
            ? Theme.palette.chatControl
            : (pointer.hovered || root.activeFocus ? Theme.palette.navHover : "transparent")
        border.width: root.activeFocus ? 1 : (root.selected ? 1 : 0)
        border.color: root.activeFocus
            ? Theme.palette.focus
            : (root.selected ? Qt.rgba(255, 255, 255, 0.08) : "transparent")

        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Row {
        anchors.fill: parent
        anchors.leftMargin: root.compact ? 0 : 10
        anchors.rightMargin: root.compact ? 0 : 10
        spacing: 9

        Item {
            width: root.compact ? parent.width : 18
            height: parent.height

            Image {
                id: navIcon
                visible: root.iconSource ? true : false
                anchors.centerIn: parent
                width: 16
                height: 16
                source: root.iconSource
                sourceSize.width: 32
                sourceSize.height: 32
                fillMode: Image.PreserveAspectFit
                opacity: root.selected ? 1.0 : (pointer.hovered ? 0.95 : 0.72)
            }
        }

        Text {
            id: navLabel
            visible: !root.compact
            width: Math.max(0, parent.width - 27)
            height: parent.height
            text: root.title
            color: root.selected ? "#FFFFFF" : Theme.palette.navText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
            font.weight: root.selected ? Font.Medium : Font.Normal
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            renderType: Theme.textRenderType
        }
    }

    HoverHandler { id: pointer }
    TapHandler {
        id: navTap
        onTapped: {
            root.forceActiveFocus()
            root.activated()
        }
    }

    ToolTip.visible: root.compact && pointer.hovered
    ToolTip.text: root.title
    ToolTip.delay: 450
}
