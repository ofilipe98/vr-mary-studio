import QtQuick
import "../theme"

VrButton {
    id: control
    implicitHeight: 34
    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.variant === "primary" && control.enabled ? frontend.palette.accessibleOrange
            : control.hovered || control.down ? frontend.palette.chatControl : "transparent"
        border.width: control.activeFocus ? 2 : control.variant === "ghost" ? 0 : 1
        border.color: control.activeFocus ? frontend.palette.focus : frontend.palette.chatBorder
        opacity: control.enabled ? 1 : 0.5
        Behavior on color { enabled: !frontend.reduceMotion; ColorAnimation { duration: Theme.fastDuration } }
    }
}
