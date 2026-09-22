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
        if (key === "full_access") return "unlock"
        return "auto"
    }

    readonly property color rowHighlight: Theme.palette.appearance === "light"
        ? Qt.rgba(0, 0, 0, 0.05) : Qt.rgba(1, 1, 1, 0.09)
    readonly property color rowHover: Theme.palette.appearance === "light"
        ? Qt.rgba(0, 0, 0, 0.035) : Qt.rgba(1, 1, 1, 0.05)

    property bool compact: false
    implicitHeight: compact ? Theme.scaledGeometry(26) : Theme.scaledGeometry(28)
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
            Layout.preferredWidth: control.compact ? Theme.iconCompact : Theme.iconSmall
            Layout.preferredHeight: control.compact ? Theme.iconCompact : Theme.iconSmall
            kind: control.permissionIconKind(control.currentItem.value)
            foreground: Theme.palette.mutedText
        }
        Text {
            text: control.currentItem.label || "Auto"
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: control.compact ? Theme.fontSizeCaption : Theme.fontSizeControl
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
        width: Math.min(Theme.scaledGeometry(360), Theme.viewportWidth - 24)
        height: permissionColumn.implicitHeight + 2 * padding
        padding: Theme.scaledGeometry(5)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: Theme.scaledGeometry(11)
        }

        contentItem: ColumnLayout {
            id: permissionColumn
            spacing: 2
            Repeater {
                model: control.model
                delegate: Rectangle {
                    required property int index
                    required property var modelData
                    readonly property bool selected: control.currentIndex === index
                    Layout.fillWidth: true
                    implicitHeight: Math.max(Theme.scaledGeometry(54),
                        permissionContent.implicitHeight + Theme.scaledGeometry(14))
                    radius: Theme.scaledGeometry(8)
                    color: selected
                        ? control.rowHighlight
                        : permissionHover.hovered ? control.rowHover : "transparent"

                    RowLayout {
                        id: permissionContent
                        anchors.fill: parent
                        anchors.leftMargin: Theme.scaledGeometry(9)
                        anchors.rightMargin: Theme.scaledGeometry(9)
                        anchors.topMargin: Theme.scaledGeometry(7)
                        anchors.bottomMargin: Theme.scaledGeometry(7)
                        spacing: Theme.scaledGeometry(8)
                        VrLineIcon {
                            Layout.preferredWidth: Theme.iconSmall
                            Layout.preferredHeight: Theme.iconSmall
                            Layout.alignment: Qt.AlignTop
                            kind: control.permissionIconKind(modelData.value)
                            foreground: Theme.palette.mutedText
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeControl
                                font.weight: Font.DemiBold
                                renderType: Theme.textRenderType
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.description || ""
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeCompact
                                renderType: Theme.textRenderType
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
