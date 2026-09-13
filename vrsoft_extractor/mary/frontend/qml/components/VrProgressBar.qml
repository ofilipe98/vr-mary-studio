import QtQuick
import QtQuick.Controls
import "../theme"

ProgressBar {
    id: root

    property color accentColor: Theme.palette.brandOrange
    property real barHeight: 6
    property color trackColor: {
        if (typeof Theme !== "undefined" && Theme.palette && Theme.palette.chatControl) {
            return Qt.tint(Theme.palette.chatControl, Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.12))
        }
        return Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.15)
    }

    readonly property real clampedPosition: Math.max(0, Math.min(1, root.position))
    property real animatedPosition: clampedPosition

    Behavior on animatedPosition {
        enabled: !root.indeterminate && (typeof frontend === "undefined" || !frontend.reduceMotion)
        NumberAnimation {
            duration: root.clampedPosition < root.animatedPosition ? 0 : 220
            easing.type: Easing.OutCubic
        }
    }

    implicitHeight: barHeight
    implicitWidth: 200
    clip: true

    background: Rectangle {
        implicitHeight: root.barHeight
        radius: root.barHeight / 2
        color: root.trackColor
    }

    contentItem: Item {
        implicitHeight: root.barHeight
        clip: true

        // Indeterminate Primary Beam
        Rectangle {
            id: beam1
            visible: root.indeterminate && (typeof frontend === "undefined" || !frontend.reduceMotion)
            height: root.barHeight
            radius: root.barHeight / 2
            width: Math.max(70, root.width * 0.38)
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.0) }
                GradientStop { position: 0.25; color: root.accentColor }
                GradientStop { position: 0.75; color: root.accentColor }
                GradientStop { position: 1.0; color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.0) }
            }

            SequentialAnimation on x {
                running: root.indeterminate && root.visible && (typeof frontend === "undefined" || !frontend.reduceMotion)
                loops: Animation.Infinite
                NumberAnimation {
                    from: -beam1.width
                    to: Math.max(1, root.width)
                    duration: 1350
                    easing.type: Easing.InOutQuad
                }
            }
        }

        // Indeterminate Secondary Pulse Beam (Faster, luminous accent)
        Rectangle {
            id: beam2
            visible: root.indeterminate && (typeof frontend === "undefined" || !frontend.reduceMotion)
            height: root.barHeight
            radius: root.barHeight / 2
            width: Math.max(36, root.width * 0.20)
            opacity: 0.8
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.0) }
                GradientStop { position: 0.5; color: Qt.lighter(root.accentColor, 1.25) }
                GradientStop { position: 1.0; color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.0) }
            }

            SequentialAnimation on x {
                running: root.indeterminate && root.visible && (typeof frontend === "undefined" || !frontend.reduceMotion)
                loops: Animation.Infinite
                PauseAnimation { duration: 250 }
                NumberAnimation {
                    from: -beam2.width
                    to: Math.max(1, root.width)
                    duration: 1050
                    easing.type: Easing.InOutCubic
                }
            }
        }

        // Reduced motion fallback for indeterminate mode
        Rectangle {
            visible: root.indeterminate && typeof frontend !== "undefined" && frontend.reduceMotion
            anchors.centerIn: parent
            height: root.barHeight
            radius: root.barHeight / 2
            width: root.width * 0.5
            color: root.accentColor
            opacity: 0.6
        }

        // Determinate fill
        Rectangle {
            id: fillBar
            visible: !root.indeterminate && root.animatedPosition > 0
            height: root.barHeight
            radius: root.barHeight / 2
            width: Math.max(0, Math.min(root.width, root.animatedPosition * root.width))

            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: root.accentColor }
                GradientStop { position: 1.0; color: Qt.lighter(root.accentColor, 1.10) }
            }
        }
    }
}
