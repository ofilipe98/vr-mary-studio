import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    property var effortModel: []
    property var tierModel: []
    property int currentEffortIndex: 0
    property int currentTierIndex: 0
    property bool popupAbove: true
    property bool outlined: false
    readonly property var currentEffort: currentEffortIndex >= 0
        && currentEffortIndex < effortModel.length ? effortModel[currentEffortIndex] : ({})
    readonly property var currentTier: currentTierIndex >= 0
        && currentTierIndex < tierModel.length ? tierModel[currentTierIndex] : ({})
    readonly property string compactLabel: {
        var effort = control.currentEffort.label || ""
        var tier = control.currentTier.label || ""
        if (effort.length && tier.length) return effort + " · " + tier
        return effort.length ? effort : tier
    }
    signal effortActivated(int index)
    signal tierActivated(int index)

    function openPicker() {
        if ((control.effortModel && control.effortModel.length > 0) || (control.tierModel && control.tierModel.length > 0)) {
            optionsPopup.open()
        }
    }

    implicitHeight: Theme.compactControlHeight
    implicitWidth: Math.max(96, compactRow.implicitWidth + 14)
    leftPadding: 7
    rightPadding: 7
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && control.down ? 0.97 : 1
    onClicked: {
        if (!((control.effortModel && control.effortModel.length > 0) || (control.tierModel && control.tierModel.length > 0))) return
        optionsPopup.opened ? optionsPopup.close() : optionsPopup.open()
    }

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    contentItem: RowLayout {
        id: compactRow
        spacing: 7
        Text {
            text: control.compactLabel || "Medium"
            color: control.hovered || optionsPopup.opened ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(12.5)
            renderType: Text.NativeRendering
        }
        VrLineIcon {
            Layout.preferredWidth: 11
            Layout.preferredHeight: 11
            kind: "chevronDown"
            foreground: control.hovered || optionsPopup.opened ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8")
        }
    }

    background: Rectangle {
        radius: 6
        color: control.down || control.hovered || optionsPopup.opened
            ? Qt.rgba(255, 255, 255, 0.07) : (control.outlined ? Theme.palette.chatControl : "transparent")
        border.width: control.outlined || control.activeFocus ? 1 : 0
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Popup {
        id: optionsPopup
        objectName: "reasoningPickerPopup"
        parent: control
        x: 0
        y: control.popupAbove ? -height - 7 : control.height + 7
        width: 220
        height: 38 + control.effortModel.length * 32
            + (control.tierModel.length > 0 ? 34 + control.tierModel.length * 48 : 0)
        padding: 6
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: 11
        }

        contentItem: ColumnLayout {
            spacing: 2

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 7
                Layout.preferredHeight: 24
                text: "Raciocínio"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
                verticalAlignment: Text.AlignVCenter
            }

            Repeater {
                model: control.effortModel
                delegate: Rectangle {
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 30
                    radius: 7
                    color: control.currentEffortIndex === index
                        ? Theme.palette.chatControl : effortHover.hovered
                            ? Theme.palette.surfaceRaised : "transparent"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        Text {
                            Layout.fillWidth: true
                            text: modelData.label
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: control.currentEffortIndex === index ? Font.DemiBold : Font.Normal
                        }
                        Rectangle {
                            visible: modelData.default === true
                            Layout.preferredWidth: defaultLabel.implicitWidth + 8
                            Layout.preferredHeight: 18
                            radius: 5
                            color: Theme.palette.surfaceRaised
                            Text {
                                id: defaultLabel
                                anchors.centerIn: parent
                                text: "Padrão"
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(9)
                            }
                        }
                    }
                    HoverHandler { id: effortHover }
                    TapHandler {
                        onTapped: {
                            control.effortActivated(index)
                            optionsPopup.close()
                        }
                    }
                }
            }

            Rectangle {
                visible: control.tierModel.length > 0
                Layout.fillWidth: true
                Layout.leftMargin: 7
                Layout.rightMargin: 7
                Layout.preferredHeight: 1
                color: Theme.palette.chatBorder
            }

            Text {
                visible: control.tierModel.length > 0
                Layout.fillWidth: true
                Layout.leftMargin: 7
                Layout.preferredHeight: 24
                text: "Service Tier"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
                verticalAlignment: Text.AlignVCenter
            }

            Repeater {
                model: control.tierModel
                delegate: Rectangle {
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: modelData.description ? 46 : 32
                    radius: 7
                    color: control.currentTierIndex === index
                        ? Theme.palette.chatControl : tierHover.hovered
                            ? Theme.palette.surfaceRaised : "transparent"
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        spacing: 1
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: control.currentTierIndex === index ? Font.DemiBold : Font.Normal
                            }
                            Rectangle {
                                visible: modelData.default === true
                                Layout.preferredWidth: tierDefault.implicitWidth + 8
                                Layout.preferredHeight: 18
                                radius: 5
                                color: Theme.palette.surfaceRaised
                                Text {
                                    id: tierDefault
                                    anchors.centerIn: parent
                                    text: "Padrão"
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(9)
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: modelData.description
                            text: modelData.description || ""
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(10)
                            elide: Text.ElideRight
                        }
                    }
                    HoverHandler { id: tierHover }
                    TapHandler {
                        onTapped: {
                            control.tierActivated(index)
                            optionsPopup.close()
                        }
                    }
                }
            }
        }
    }
}
