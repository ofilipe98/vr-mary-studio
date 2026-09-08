import QtQuick
import QtQuick.Controls
import "../theme"

Item {
    id: root

    property var model: []
    property int currentIndex: 0
    property bool understated: false
    readonly property int count: model.length
    signal activated(int index)

    implicitHeight: Math.max(Theme.compactControlHeight, tabRow.implicitHeight)
    implicitWidth: tabRow.implicitWidth

    Flickable {
        id: tabFlick
        anchors.fill: parent
        contentWidth: tabRow.implicitWidth
        contentHeight: height
        clip: contentWidth > width
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.HorizontalFlick
        interactive: contentWidth > width

        Row {
            id: tabRow
            spacing: Theme.spaceXs

            Repeater {
                id: tabRepeater
                model: root.model

                delegate: Item {
                id: tab

                required property int index
                required property string modelData

                width: tabLabel.implicitWidth + 28
                height: Theme.compactControlHeight
                activeFocusOnTab: true
                transformOrigin: Item.Center
                scale: !frontend.reduceMotion && tabTap.pressed ? 0.97 : 1
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData
                Accessible.selected: root.currentIndex === index

                Behavior on scale {
                    enabled: !frontend.reduceMotion
                    NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
                }

                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusControl
                    color: root.currentIndex === tab.index
                        ? (root.understated ? "transparent" : Theme.palette.accentSoft)
                        : tabHover.hovered || tab.activeFocus
                            ? (root.understated ? Theme.palette.chatControl : Theme.palette.hover) : "transparent"
                    border.width: tab.activeFocus ? 2 : 0
                    border.color: Theme.palette.focus

                    Behavior on color {
                        enabled: !frontend.reduceMotion
                        ColorAnimation { duration: Theme.fastDuration }
                    }
                }

                Rectangle {
                    visible: root.understated && root.currentIndex === tab.index
                    anchors.bottom: parent.bottom
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: tabLabel.width; height: 2; radius: 1
                    color: Theme.palette.text
                }
                Text {
                    id: tabLabel
                    anchors.centerIn: parent
                    text: tab.modelData
                    color: root.currentIndex === tab.index
                        ? Theme.palette.text : Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: root.understated ? Theme.fontSize(13) : Theme.bodySize
                    font.weight: root.currentIndex === tab.index
                        ? Font.DemiBold : Font.Medium
                }

                HoverHandler { id: tabHover }

                TapHandler {
                    id: tabTap
                    onTapped: {
                        tab.forceActiveFocus()
                        root.activate(tab.index)
                    }
                }

                Keys.onReturnPressed: root.activate(tab.index)
                Keys.onSpacePressed: root.activate(tab.index)
                Keys.onLeftPressed: root.activate(Math.max(0, tab.index - 1))
                Keys.onRightPressed: root.activate(
                    Math.min(root.count - 1, tab.index + 1))
                }
            }
        }
    }

    function activate(index) {
        if (index < 0 || index >= root.count)
            return
        const target = tabRepeater.itemAt(index)
        if (target) {
            target.forceActiveFocus()
            const left = target.x
            const right = target.x + target.width
            if (left < tabFlick.contentX)
                tabFlick.contentX = left
            else if (right > tabFlick.contentX + tabFlick.width)
                tabFlick.contentX = Math.max(0, right - tabFlick.width)
        }
        if (index === root.currentIndex)
            return
        root.currentIndex = index
        root.activated(index)
    }
}
