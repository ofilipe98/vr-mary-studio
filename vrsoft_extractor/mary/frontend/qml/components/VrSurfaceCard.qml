import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    property url iconSource
    property string iconKind: ""
    property string title: ""
    property string description: ""

    implicitHeight: 118
    leftPadding: 15
    rightPadding: 15
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && control.down ? 0.975 : 1

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    contentItem: RowLayout {
        spacing: 11
        Image {
            visible: !control.iconKind.length
            Layout.preferredWidth: 25
            Layout.preferredHeight: 25
            source: control.iconSource
            fillMode: Image.PreserveAspectFit
            opacity: control.enabled ? 0.9 : 0.45
        }
        VrLineIcon {
            visible: control.iconKind.length > 0
            Layout.preferredWidth: 25
            Layout.preferredHeight: 25
            kind: control.iconKind
            foreground: Theme.palette.mutedText
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Text {
                Layout.fillWidth: true
                text: control.title
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(14)
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: control.description
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeCaption
                font.weight: Font.Normal
                wrapMode: Text.WordWrap
            }
        }
    }

    background: Rectangle {
        radius: 10
        color: control.down || control.hovered
            ? Theme.palette.chatControl : Theme.palette.chatComposer
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }
}
