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
    property bool popupAbove: false
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

    // T3 keeps the section list on a neutral overlay: the selected row
    // lightens the popup surface instead of tinting it with the brand accent.
    readonly property color rowHighlight: frontend.resolvedAppearance === "light"
        ? Qt.rgba(0, 0, 0, 0.05) : Qt.rgba(1, 1, 1, 0.09)
    readonly property color rowHover: frontend.resolvedAppearance === "light"
        ? Qt.rgba(0, 0, 0, 0.035) : Qt.rgba(1, 1, 1, 0.05)
    // T3 keeps the section popup snug around its items instead of using a
    // fixed menu width; measurements use the same font as the rows.
    readonly property real chipReserve: Theme.scaledGeometry(52)

    function labelAdvance(text) {
        return labelFont.advanceWidth(String(text || ""))
    }

    function captionAdvance(text) {
        return captionFont.advanceWidth(String(text || ""))
    }

    function rowWidth(label, withChip) {
        return labelAdvance(label) + (withChip ? chipReserve : 0)
    }

    // The popup width is measured from the model lists; pass them as arguments
    // so the binding re-evaluates when efforts or tiers arrive asynchronously.
    function popupWidth(efforts, tiers) {
        var widest = Math.max(labelAdvance("Raciocínio"), labelAdvance("Service Tier"))
        for (var e = 0; e < efforts.length; ++e) {
            var effort = efforts[e] || ({})
            widest = Math.max(widest, rowWidth(effort.label, effort.default === true))
            widest = Math.max(widest, captionAdvance(effort.description))
        }
        for (var t = 0; t < tiers.length; ++t) {
            var tier = tiers[t] || ({})
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

    implicitHeight: Theme.compactControlHeight
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
            color: control.hovered || optionsPopup.opened
                ? Theme.palette.text : Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeControl
            renderType: Theme.textRenderType
        }
        VrLineIcon {
            Layout.preferredWidth: Theme.iconMicro
            Layout.preferredHeight: Theme.iconMicro
            kind: "chevronDown"
            foreground: control.hovered || optionsPopup.opened
                ? Theme.palette.text : Theme.palette.mutedText
        }
    }

    background: Rectangle {
        radius: Theme.scaledGeometry(6)
        // Ghost control like the T3 composer: no chrome at rest, only the
        // hover/open tint; focus keeps an accessibility ring.
        color: control.down || control.hovered || optionsPopup.opened
            ? Theme.palette.hover : "transparent"
        // Ring only for keyboard focus; mouse clicks stay chrome-free like T3.
        border.width: control.visualFocus ? 1 : 0
        border.color: Theme.palette.focus
        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Popup {
        id: optionsPopup
        objectName: "reasoningPickerPopup"
        parent: control
        // Opens below the composer control; flips up only when the sections
        // would not fit in the remaining window space (no content is clipped).
        // The popup hugs its sections like T3 instead of reserving a fixed menu.
        readonly property real naturalHeight: reasoningColumn.implicitHeight + 2 * padding
        readonly property real spaceBelow: Theme.viewportHeight
            - control.mapToItem(null, 0, 0).y - control.height - Theme.scaledGeometry(14)
        readonly property bool openAbove: control.popupAbove || spaceBelow < naturalHeight
        x: 0
        y: openAbove ? -height - 7 : control.height + 7
        width: control.popupWidth(control.effortModel, control.tierModel)
        height: naturalHeight
        padding: Theme.scaledGeometry(5)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: Theme.scaledGeometry(11)
        }

        contentItem: ColumnLayout {
            id: reasoningColumn
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
                    readonly property bool selected: control.currentEffortIndex === index
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.scaledGeometry(28)
                    radius: Theme.scaledGeometry(7)
                    color: selected
                        ? control.rowHighlight
                        : effortHover.hovered ? control.rowHover : "transparent"
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
                            font.weight: selected ? Font.Medium : Font.Normal
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
                    readonly property bool selected: control.currentTierIndex === index
                    Layout.fillWidth: true
                    Layout.preferredHeight: modelData.description ? 44 : Theme.scaledGeometry(28)
                    radius: Theme.scaledGeometry(7)
                    color: selected
                        ? control.rowHighlight
                        : tierHover.hovered ? control.rowHover : "transparent"
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
                                font.weight: selected ? Font.Medium : Font.Normal
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
