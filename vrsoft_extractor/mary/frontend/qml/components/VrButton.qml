import QtQuick
import QtQuick.Controls
import "../theme"

Button {
    id: control

    property string variant: "secondary"
    property int textAlignment: Text.AlignHCenter
    property bool showFocusRing: true

    implicitHeight: Theme.controlHeight
    implicitWidth: Math.max(96, contentItem.implicitWidth + 28)
    leftPadding: 14
    rightPadding: 14
    focusPolicy: Qt.StrongFocus
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && control.down && control.enabled ? 0.965 : 1

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    contentItem: Text {
        text: control.text
        color: !control.enabled ? Theme.palette.mutedText
            : control.variant === "primary" || control.variant === "danger"
                ? "#FFFFFF" : Theme.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.controlSize
        font.weight: Theme.weightMedium
        horizontalAlignment: control.textAlignment
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        renderType: Theme.textRenderType
    }

    background: Rectangle {
        radius: Theme.radiusControl
        color: {
            if (!control.enabled)
                return control.variant === "ghost" ? "transparent" : Theme.palette.surface
            if (control.variant === "primary")
                return control.down ? Theme.palette.brandOrange : Theme.palette.accessibleOrange
            if (control.variant === "danger")
                return control.down
                    ? Qt.darker(Theme.palette.danger, 1.2) : Theme.palette.danger
            if (control.down || control.hovered)
                return Theme.palette.hover
            return control.variant === "ghost" ? "transparent" : Theme.palette.surface
        }
        border.width: control.activeFocus && control.showFocusRing ? 2 : (control.variant === "ghost" ? 0 : 1)
        border.color: control.activeFocus && control.showFocusRing ? Theme.palette.focus
            : control.variant === "danger" ? Theme.palette.danger
            : Theme.palette.border

        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }
}
