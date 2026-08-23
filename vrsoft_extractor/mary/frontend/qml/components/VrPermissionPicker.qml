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

    implicitHeight: Theme.compactControlHeight
    implicitWidth: Math.max(106, compactRow.implicitWidth + 14)
    leftPadding: 7
    rightPadding: 7
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    onClicked: optionsPopup.open()

    contentItem: RowLayout {
        id: compactRow
        spacing: 7
        VrLineIcon {
            Layout.preferredWidth: 16
            Layout.preferredHeight: 16
            kind: control.permissionIconKind(control.currentItem.value)
            foreground: frontend.palette.mutedText
        }
        Text {
            text: control.currentItem.label || "Auto"
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: 13
        }
        VrLineIcon {
            Layout.preferredWidth: 13
            Layout.preferredHeight: 13
            kind: "chevronDown"
            foreground: frontend.palette.mutedText
        }
    }

    background: Rectangle {
        radius: 8
        color: control.down || control.hovered || optionsPopup.opened
            ? frontend.palette.chatControl : "transparent"
        border.width: control.activeFocus ? 1 : 0
        border.color: frontend.palette.focus
    }

    Popup {
        id: optionsPopup
        objectName: "permissionPickerPopup"
        parent: control
        x: 0
        y: -height - 7
        width: 372
        height: 250
        padding: 5
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: frontend.palette.chatComposer
            border.width: 1
            border.color: frontend.palette.chatBorder
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
                        ? frontend.palette.chatControl : permissionHover.hovered
                            ? frontend.palette.surfaceRaised : "transparent"
                    border.width: control.currentIndex === index ? 1 : 0
                    border.color: frontend.palette.chatBorder

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
                                ? frontend.palette.text : frontend.palette.mutedText
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.description || ""
                                color: frontend.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: 10
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
