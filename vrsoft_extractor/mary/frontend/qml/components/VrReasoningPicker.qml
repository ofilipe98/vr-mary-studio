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

    function openPicker() { optionsPopup.open() }

    implicitHeight: Theme.compactControlHeight
    implicitWidth: Math.max(96, compactRow.implicitWidth + 14)
    leftPadding: 7
    rightPadding: 7
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
        spacing: 7
        Text {
            text: "✦"
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: 14
        }
        Text {
            text: control.compactLabel || "Medium"
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
        color: control.down || control.hovered || optionsPopup.opened || control.outlined
            ? frontend.palette.chatControl : "transparent"
        border.width: control.outlined || control.activeFocus ? 1 : 0
        border.color: control.activeFocus ? frontend.palette.focus : frontend.palette.chatBorder
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
            color: frontend.palette.chatComposer
            border.width: 1
            border.color: frontend.palette.chatBorder
            radius: 11
        }

        contentItem: ColumnLayout {
            spacing: 2

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 7
                Layout.preferredHeight: 24
                text: "Raciocínio"
                color: frontend.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: 11
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
                        ? frontend.palette.chatControl : effortHover.hovered
                            ? frontend.palette.surfaceRaised : "transparent"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        Text {
                            Layout.fillWidth: true
                            text: modelData.label
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: 13
                            font.weight: control.currentEffortIndex === index ? Font.DemiBold : Font.Normal
                        }
                        Rectangle {
                            visible: modelData.default === true
                            Layout.preferredWidth: defaultLabel.implicitWidth + 8
                            Layout.preferredHeight: 18
                            radius: 5
                            color: frontend.palette.surfaceRaised
                            Text {
                                id: defaultLabel
                                anchors.centerIn: parent
                                text: "Padrão"
                                color: frontend.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: 9
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
                color: frontend.palette.chatBorder
            }

            Text {
                visible: control.tierModel.length > 0
                Layout.fillWidth: true
                Layout.leftMargin: 7
                Layout.preferredHeight: 24
                text: "Service Tier"
                color: frontend.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: 11
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
                        ? frontend.palette.chatControl : tierHover.hovered
                            ? frontend.palette.surfaceRaised : "transparent"
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
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 13
                                font.weight: control.currentTierIndex === index ? Font.DemiBold : Font.Normal
                            }
                            Rectangle {
                                visible: modelData.default === true
                                Layout.preferredWidth: tierDefault.implicitWidth + 8
                                Layout.preferredHeight: 18
                                radius: 5
                                color: frontend.palette.surfaceRaised
                                Text {
                                    id: tierDefault
                                    anchors.centerIn: parent
                                    text: "Padrão"
                                    color: frontend.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 9
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: modelData.description
                            text: modelData.description || ""
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: 10
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
