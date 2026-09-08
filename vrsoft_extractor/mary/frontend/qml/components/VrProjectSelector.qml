pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    property var model: []
    property int currentIndex: 0
    property string popupObjectName: ""
    readonly property var currentItem: currentIndex >= 0 && currentIndex < model.length
        ? model[currentIndex] : ({})
    signal activated(int index)
    signal settingsRequested(int index)

    function openSelectorMenu() {
        selectorPopup.open()
    }

    function clickSettingsButton(index) {
        var row = projectList.itemAtIndex(index)
        if (!row || !row.configurable)
            return false
        row.clickSettings()
        return true
    }

    function clickProjectButton(index) {
        var row = projectList.itemAtIndex(index)
        if (!row)
            return false
        row.activateSelection()
        return true
    }

    implicitHeight: Theme.compactControlHeight
    leftPadding: 8
    rightPadding: 8
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    onClicked: selectorPopup.opened ? selectorPopup.close() : selectorPopup.open()

    contentItem: RowLayout {
        spacing: 7
        VrLineIcon {
            Layout.preferredWidth: 15
            Layout.preferredHeight: 15
            kind: "folder"
            foreground: Theme.palette.mutedText
            strokeWidth: 1.55
        }
        Text {
            Layout.fillWidth: true
            text: control.currentItem.label || "Todos os projetos"
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(11)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        VrLineIcon {
            Layout.preferredWidth: 12
            Layout.preferredHeight: 12
            kind: selectorPopup.opened ? "chevronUp" : "chevronDown"
            foreground: Theme.palette.mutedText
            strokeWidth: 1.45
        }
    }

    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.down || control.hovered || selectorPopup.opened
            ? Theme.palette.chatControl : Theme.palette.surfaceRaised
        border.width: 1
        border.color: control.activeFocus
            ? Theme.palette.focus : Theme.palette.border
    }

    Popup {
        id: selectorPopup
        objectName: control.popupObjectName
        parent: control
        x: 0
        y: 0
        width: control.width
        height: Math.min(6, control.model.length) * 33 + 8
        padding: 4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: projectList.positionViewAtIndex(control.currentIndex, ListView.Contain)

        contentItem: ListView {
            id: projectList
            clip: true
            spacing: 1
            model: selectorPopup.opened ? control.model : []
            currentIndex: control.currentIndex
            ScrollIndicator.vertical: ScrollIndicator { }

            delegate: Rectangle {
                id: projectRow
                required property int index
                required property var modelData
                readonly property bool selected: control.currentIndex === index
                readonly property bool configurable: String(modelData.path || "").length > 0
                function activateSettings() {
                    control.settingsRequested(projectRow.index)
                    selectorPopup.close()
                }
                function activateSelection() {
                    control.activated(projectRow.index)
                    selectorPopup.close()
                }
                function clickSettings() {
                    activateSettings()
                }
                width: projectList.width
                height: 32
                radius: 6
                color: selected ? Theme.palette.selection
                    : rowHover.hovered ? Theme.palette.chatControl : "transparent"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 7
                    anchors.rightMargin: 3
                    spacing: 7
                    VrLineIcon {
                        Layout.preferredWidth: 14
                        Layout.preferredHeight: 14
                        kind: "folder"
                        foreground: projectRow.selected
                            ? Theme.palette.text : Theme.palette.mutedText
                        strokeWidth: 1.5
                    }
                    Text {
                        Layout.fillWidth: true
                        text: projectRow.modelData.label
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(11)
                        font.weight: projectRow.selected ? Font.DemiBold : Font.Normal
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                    }
                    VrIconButton {
                        id: settingsButton
                        objectName: "projectSettingsButton"
                        property int projectIndex: projectRow.index
                        visible: projectRow.configurable
                        Layout.preferredWidth: visible ? 24 : 0
                        Layout.preferredHeight: 24
                        iconKind: "settings"
                        iconSize: 13
                        foreground: hovered
                            ? Theme.palette.text : Theme.palette.mutedText
                        ToolTip.visible: hovered
                        ToolTip.text: "Configurar pasta"
                        Accessible.name: "Configurar " + projectRow.modelData.label
                        onClicked: projectRow.activateSettings()
                        z: 2
                    }
                    VrLineIcon {
                        visible: projectRow.selected && !projectRow.configurable
                        Layout.preferredWidth: visible ? 12 : 0
                        Layout.preferredHeight: 12
                        kind: "chevronDown"
                        foreground: Theme.palette.mutedText
                        strokeWidth: 1.45
                    }
                }

                HoverHandler { id: rowHover }
                MouseArea {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.right: parent.right
                    anchors.rightMargin: projectRow.configurable ? 28
                        : projectRow.selected ? 20 : 0
                    onClicked: projectRow.activateSelection()
                }
            }
        }

        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.border
            radius: 10
        }
    }
}
