import QtQuick
import QtQuick.Controls
import "../theme"

Item {
    id: root

    property var model: []
    property int currentIndex: 0
    readonly property int count: model.length
    signal activated(int index)

    implicitHeight: Theme.compactControlHeight
    implicitWidth: tabRow.implicitWidth

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
                height: root.height
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData
                Accessible.selected: root.currentIndex === index

                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusControl
                    color: root.currentIndex === tab.index
                        ? frontend.palette.accentSoft
                        : tabHover.hovered || tab.activeFocus
                            ? frontend.palette.hover : "transparent"
                    border.width: tab.activeFocus ? 2 : 0
                    border.color: frontend.palette.focus

                    Behavior on color {
                        ColorAnimation { duration: Theme.fastDuration }
                    }
                }

                Text {
                    id: tabLabel
                    anchors.centerIn: parent
                    text: tab.modelData
                    color: root.currentIndex === tab.index
                        ? frontend.palette.text : frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.bodySize
                    font.weight: root.currentIndex === tab.index
                        ? Font.DemiBold : Font.Medium
                }

                HoverHandler { id: tabHover }

                TapHandler {
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

    function activate(index) {
        if (index < 0 || index >= root.count)
            return
        const target = tabRepeater.itemAt(index)
        if (target)
            target.forceActiveFocus()
        if (index === root.currentIndex)
            return
        root.currentIndex = index
        root.activated(index)
    }
}
