import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    property var model: []
    property int currentIndex: 0
    readonly property var currentItem: currentIndex >= 0 && currentIndex < model.length
        ? model[currentIndex] : ({})
    signal activated(int index)

    function openPicker() { optionsPopup.open() }
    function permissionIconKind(value) {
        var key = String(value || "auto")
        if (key === "supervised") return "lock"
        if (key === "auto_edits") return "edit"
        if (key === "full_access") return "lock"
        return "auto"
    }

    property bool compact: false
    implicitHeight: compact ? 26 : Theme.compactControlHeight
    implicitWidth: compact
        ? (compactRow.implicitWidth + leftPadding + rightPadding)
        : Math.max(106, compactRow.implicitWidth + 14)
    leftPadding: compact ? 6 : 7
    rightPadding: compact ? 6 : 7
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && control.down ? 0.97 : 1
    onClicked: optionsPopup.opened ? optionsPopup.close() : optionsPopup.open()

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    contentItem: RowLayout {
        id: compactRow
        spacing: control.compact ? 5 : 7
        VrLineIcon {
            Layout.preferredWidth: control.compact ? 13 : 16
            Layout.preferredHeight: control.compact ? 13 : 16
            kind: control.permissionIconKind(control.currentItem.value)
            foreground: Theme.palette.mutedText
        }
        Text {
            text: control.currentItem.label || "Auto"
            color: control.compact
                ? (control.hovered || optionsPopup.opened ? Theme.palette.text : Theme.palette.mutedText)
                : (control.hovered || optionsPopup.opened ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8"))
            font.family: Theme.fontFamily
            font.pixelSize: control.compact ? Theme.fontSize(11.5) : Theme.fontSize(12.5)
            renderType: Text.NativeRendering
        }
        VrLineIcon {
            Layout.preferredWidth: control.compact ? 10 : 11
            Layout.preferredHeight: control.compact ? 10 : 11
            kind: "chevronDown"
            foreground: control.hovered || optionsPopup.opened ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8")
        }
    }

    background: Rectangle {
        radius: control.compact ? 6 : 6
        color: control.down || control.hovered || optionsPopup.opened
            ? Qt.rgba(255, 255, 255, 0.07) : "transparent"
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.palette.focus
        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Popup {
        id: optionsPopup
        objectName: "permissionPickerPopup"
        parent: control
        x: 0
        y: -height - 7
        width: Math.min(372, Theme.viewportWidth - 24)
        height: 250
        padding: 5
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: 11
        }

        contentItem: ColumnLayout {
            spacing: 2
            Repeater {
                model: control.model
                delegate: Rectangle {
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 7
                    color: control.currentIndex === index
                        ? Theme.palette.chatControl : permissionHover.hovered
                            ? Theme.palette.surfaceRaised : "transparent"
                    border.width: control.currentIndex === index ? 1 : 0
                    border.color: Theme.palette.chatBorder

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        spacing: 8
                        VrLineIcon {
                            Layout.preferredWidth: 17
                            Layout.preferredHeight: 17
                            Layout.alignment: Qt.AlignTop
                            Layout.topMargin: 5
                            kind: control.permissionIconKind(modelData.value)
                            foreground: control.currentIndex === index
                                ? Theme.palette.text : Theme.palette.mutedText
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.description || ""
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeCaption
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                    HoverHandler { id: permissionHover }
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
}
