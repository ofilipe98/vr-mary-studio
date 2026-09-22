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
    // T3 keeps the section popup snug around its items instead of using a
    // fixed menu width; measurements use the same font as the rows.
    readonly property real chipReserve: Theme.scaledGeometry(52)
    signal effortActivated(int index)
    signal tierActivated(int index)

    function openPicker() {
        if ((control.effortModel && control.effortModel.length > 0) || (control.tierModel && control.tierModel.length > 0)) {
            optionsPopup.open()
        }
    }

    function labelAdvance(text) {
        return labelFont.advanceWidth(String(text || ""))
    }

    function captionAdvance(text) {
        return captionFont.advanceWidth(String(text || ""))
    }

    function rowWidth(label, withChip) {
        return labelAdvance(label) + (withChip ? chipReserve : 0)
    }

    function popupWidth() {
        var widest = Math.max(labelAdvance("Raciocínio"), labelAdvance("Service Tier"))
        for (var e = 0; e < control.effortModel.length; ++e) {
            var effort = control.effortModel[e] || ({})
            widest = Math.max(widest, rowWidth(effort.label, effort.default === true))
            widest = Math.max(widest, captionAdvance(effort.description))
        }
        for (var t = 0; t < control.tierModel.length; ++t) {
            var tier = control.tierModel[t] || ({})
            widest = Math.max(widest, rowWidth(tier.label, tier.default === true))
            widest = Math.max(widest, captionAdvance(tier.description))
        }
        return Math.max(Theme.scaledGeometry(148),
            Math.min(Theme.scaledGeometry(280), widest + Theme.scaledGeometry(34)))
    }

    FontMetrics {
        id: labelFont
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeControl
        font.weight: Font.Medium
    }

    FontMetrics {
        id: captionFont
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeCaption
    }

    implicitHeight: Theme.scaledGeometry(28)
    implicitWidth: Math.max(96, compactRow.implicitWidth + 14)
    leftPadding: Theme.scaledGeometry(7)
    rightPadding: Theme.scaledGeometry(7)
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
        spacing: Theme.scaledGeometry(7)
        Text {
            text: control.compactLabel || "Medium"
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeControl
            renderType: Theme.textRenderType
        }
        VrLineIcon {
            Layout.preferredWidth: Theme.iconMicro
            Layout.preferredHeight: Theme.iconMicro
            kind: "chevronDown"
            foreground: Theme.palette.mutedText
        }
    }

    background: Rectangle {
        radius: Theme.scaledGeometry(6)
        color: control.down || control.hovered || optionsPopup.opened
            ? Theme.palette.hover : Theme.palette.chatControl
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
        width: control.popupWidth()
        padding: Theme.scaledGeometry(6)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: Theme.scaledGeometry(11)
        }

        contentItem: ColumnLayout {
            spacing: 2

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.scaledGeometry(7)
                Layout.preferredHeight: Theme.scaledGeometry(24)
                text: "Raciocínio"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeCompact
                font.weight: Theme.weightMedium
                renderType: Theme.textRenderType
                verticalAlignment: Text.AlignVCenter
            }

            Repeater {
                model: control.effortModel
                delegate: Rectangle {
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.scaledGeometry(28)
                    radius: Theme.scaledGeometry(7)
                    color: control.currentEffortIndex === index
                        ? (Theme.palette.appearance === "light"
                            ? Qt.rgba(0, 0, 0, 0.05) : Qt.rgba(1, 1, 1, 0.09))
                        : effortHover.hovered
                            ? (Theme.palette.appearance === "light"
                                ? Qt.rgba(0, 0, 0, 0.035) : Qt.rgba(1, 1, 1, 0.05))
                            : "transparent"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.scaledGeometry(8)
                        anchors.rightMargin: Theme.scaledGeometry(8)
                        spacing: Theme.scaledGeometry(8)
                        Text {
                            Layout.fillWidth: true
                            text: modelData.label
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeControl
                            font.weight: control.currentEffortIndex === index ? Font.Medium : Font.Normal
                            renderType: Theme.textRenderType
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            visible: modelData.default === true
                            Layout.preferredWidth: defaultLabel.implicitWidth + 12
                            Layout.preferredHeight: Theme.scaledGeometry(18)
                            radius: Theme.scaledGeometry(6)
                            color: Qt.rgba(Theme.palette.focus.r, Theme.palette.focus.g,
                                Theme.palette.focus.b, 0.14)
                            Text {
                                id: defaultLabel
                                anchors.centerIn: parent
                                text: "Padrão"
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeMicro
                                renderType: Theme.textRenderType
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
                Layout.leftMargin: Theme.scaledGeometry(7)
                Layout.rightMargin: Theme.scaledGeometry(7)
                Layout.preferredHeight: 1
                color: Theme.palette.chatBorder
            }

            Text {
                visible: control.tierModel.length > 0
                Layout.fillWidth: true
                Layout.leftMargin: Theme.scaledGeometry(7)
                Layout.preferredHeight: Theme.scaledGeometry(24)
                text: "Service Tier"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeCompact
                font.weight: Theme.weightMedium
                renderType: Theme.textRenderType
                verticalAlignment: Text.AlignVCenter
            }

            Repeater {
                model: control.tierModel
                delegate: Rectangle {
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: modelData.description ? 44 : Theme.scaledGeometry(28)
                    radius: Theme.scaledGeometry(7)
                    color: control.currentTierIndex === index
                        ? (Theme.palette.appearance === "light"
                            ? Qt.rgba(0, 0, 0, 0.05) : Qt.rgba(1, 1, 1, 0.09))
                        : tierHover.hovered
                            ? (Theme.palette.appearance === "light"
                                ? Qt.rgba(0, 0, 0, 0.035) : Qt.rgba(1, 1, 1, 0.05))
                            : "transparent"
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.scaledGeometry(8)
                        anchors.rightMargin: Theme.scaledGeometry(8)
                        spacing: 1
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.scaledGeometry(8)
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeControl
                                font.weight: control.currentTierIndex === index ? Font.Medium : Font.Normal
                                renderType: Theme.textRenderType
                                elide: Text.ElideRight
                            }
                            Rectangle {
                                visible: modelData.default === true
                                Layout.preferredWidth: tierDefault.implicitWidth + 12
                                Layout.preferredHeight: Theme.scaledGeometry(18)
                                radius: Theme.scaledGeometry(6)
                                color: Qt.rgba(Theme.palette.focus.r, Theme.palette.focus.g,
                                    Theme.palette.focus.b, 0.14)
                                Text {
                                    id: tierDefault
                                    anchors.centerIn: parent
                                    text: "Padrão"
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                    renderType: Theme.textRenderType
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: modelData.description
                            text: modelData.description || ""
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeCaption
                            renderType: Theme.textRenderType
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
