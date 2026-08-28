import QtQuick
import QtQuick.Controls
import "../theme"

Button {
    id: control

    property string variant: "secondary"
    property int textAlignment: Text.AlignHCenter

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
        color: !control.enabled ? frontend.palette.mutedText
            : control.variant === "primary" || control.variant === "danger"
                ? "#FFFFFF" : frontend.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySize
        font.weight: Font.DemiBold
        horizontalAlignment: control.textAlignment
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: Theme.radiusControl
        color: {
            if (!control.enabled)
                return control.variant === "ghost" ? "transparent" : frontend.palette.surface
            if (control.variant === "primary")
                return control.down ? frontend.palette.brandOrange : frontend.palette.accessibleOrange
            if (control.variant === "danger")
                return control.down
                    ? Qt.darker(frontend.palette.danger, 1.2) : frontend.palette.danger
            if (control.down || control.hovered)
                return frontend.palette.hover
            return control.variant === "ghost" ? "transparent" : frontend.palette.surface
        }
        border.width: control.activeFocus ? 2 : (control.variant === "ghost" ? 0 : 1)
        border.color: control.activeFocus ? frontend.palette.focus
            : control.variant === "danger" ? frontend.palette.danger
            : frontend.palette.border

        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }
}
