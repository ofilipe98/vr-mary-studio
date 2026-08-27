import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    property var model: []
    property int currentIndex: 0
    property string textRole: "label"
    property url iconSource
    property string symbol: ""
    property int popupWidth: 220
    readonly property var currentItem: currentIndex >= 0 && currentIndex < model.length
        ? model[currentIndex] : ({})
    signal activated(int index)

    implicitHeight: Theme.compactControlHeight
    implicitWidth: Math.max(92, row.implicitWidth + 14)
    leftPadding: 7
    rightPadding: 7
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && control.down ? 0.97 : 1
    onClicked: optionsPopup.opened ? optionsPopup.close() : optionsPopup.open()

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    contentItem: RowLayout {
        id: row
        spacing: 7
        Image {
            visible: control.iconSource.toString().length > 0
            Layout.preferredWidth: 16
            Layout.preferredHeight: 16
            source: control.iconSource
            fillMode: Image.PreserveAspectFit
        }
        Text {
            visible: !parent.children[0].visible && control.symbol.length > 0
            text: control.symbol
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: 15
        }
        Text {
            text: control.currentItem[control.textRole] || "Selecionar"
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: 13
        }
        Text {
            text: "⌄"
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: 13
        }
    }

    background: Rectangle {
        radius: 8
        color: control.down || control.hovered || optionsPopup.opened
            ? frontend.palette.chatControl : "transparent"
        border.width: control.activeFocus ? 1 : 0
        border.color: frontend.palette.focus
        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Popup {
        id: optionsPopup
        parent: control
        x: 0
        y: -height - 7
        width: Math.max(control.popupWidth, control.width)
        implicitHeight: Math.min(optionsList.contentHeight + 12, 330)
        padding: 6
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        background: Rectangle {
            color: frontend.palette.chatComposer
            border.width: 1
            border.color: frontend.palette.chatBorder
            radius: 11
        }
        contentItem: ListView {
            id: optionsList
            clip: true
            implicitHeight: contentHeight
            model: control.model
            spacing: 2
            delegate: Rectangle {
                required property int index
                required property var modelData
                width: optionsList.width
                height: 40
                radius: 7
                color: control.currentIndex === index
                    ? frontend.palette.selection : optionHover.hovered
                        ? frontend.palette.chatControl : "transparent"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    Text {
                        Layout.fillWidth: true
                        text: modelData[control.textRole] || modelData
                        color: frontend.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                    Text {
                        visible: control.currentIndex === index
                        text: "✓"
                        color: frontend.palette.brandOrange
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                }
                HoverHandler { id: optionHover }
                TapHandler {
                    onTapped: {
                        control.activated(index)
                        optionsPopup.close()
                    }
                }
            }
        }
    }
}
