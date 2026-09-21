import QtQuick
import "../theme"

VrButton {
    id: control
    implicitHeight: Theme.scaledGeometry(34)
    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.variant === "primary" && control.enabled ? Theme.palette.accessibleOrange
            : control.hovered || control.down ? Theme.palette.chatControl : "transparent"
        border.width: control.activeFocus ? 2 : control.variant === "ghost" ? 0 : 1
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
        opacity: control.enabled ? 1 : 0.5
        Behavior on color { enabled: !frontend.reduceMotion; ColorAnimation { duration: Theme.fastDuration } }
    }
}
