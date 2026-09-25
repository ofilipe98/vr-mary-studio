import QtQuick
import QtQuick.Controls
import "../theme"

ProgressBar {
    id: root

    property color accentColor: Theme.palette.brandOrange
    property real barHeight: Theme.scaledGeometry(6)
    // Opt-in caption ("xx%") rendered above the track from the real position.
    property bool showPercentage: false
    // Optional vertical tick over the track (e.g. pace marker); -1 hides it.
    property real markerPosition: -1
    property color markerColor: Theme.palette.mutedText
    // Optional semantic color switch; -1 disables the threshold.
    property real warningThreshold: -1
    property real dangerThreshold: -1
    property string accessibleName: "Progresso"

    readonly property bool reducedMotion: typeof frontend !== "undefined"
        && frontend !== null && frontend.reduceMotion
    readonly property real clampedPosition: Math.max(0, Math.min(1, root.position))
    property real animatedPosition: clampedPosition

    readonly property color effectiveAccentColor: {
        if (root.dangerThreshold >= 0 && root.clampedPosition >= root.dangerThreshold)
            return Theme.palette.danger
        if (root.warningThreshold >= 0 && root.clampedPosition >= root.warningThreshold)
            return Theme.palette.warning
        return root.accentColor
    }

    property color trackColor: {
        if (typeof Theme !== "undefined" && Theme.palette && Theme.palette.chatControl) {
            return Qt.tint(Theme.palette.chatControl, Qt.rgba(root.effectiveAccentColor.r, root.effectiveAccentColor.g, root.effectiveAccentColor.b, 0.12))
        }
        return Qt.rgba(root.effectiveAccentColor.r, root.effectiveAccentColor.g, root.effectiveAccentColor.b, 0.15)
    }

    // Single percent formatter for every progress surface: whole numbers from
    // 10% up, one decimal below it (dot separator, matching the bridges).
    function formatPercent(ratio) {
        var value = Number(ratio)
        if (!(value > 0))
            return "0%"
        var percent = Math.min(1, value) * 100
        if (percent >= 100)
            return "100%"
        if (percent >= 10)
            return Math.round(percent) + "%"
        return percent.toFixed(1) + "%"
    }

    readonly property string percentageText: root.formatPercent(root.clampedPosition)

    Behavior on animatedPosition {
        enabled: !root.indeterminate && !root.reducedMotion
        NumberAnimation {
            duration: root.clampedPosition < root.animatedPosition ? 0 : 220
            easing.type: Easing.OutCubic
        }
    }

    implicitHeight: root.barHeight + (root.showPercentage ? percentageLabel.implicitHeight + Theme.spaceXs : 0)
    implicitWidth: 200
    padding: 0

    Accessible.name: root.accessibleName
    Accessible.description: root.indeterminate ? "" : root.percentageText

    // The track lives inside contentItem (caption row above it); the style
    // background would otherwise stretch behind the whole control.
    background: Item {}

    contentItem: Item {
        Item {
            id: barArea
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: root.barHeight

            Rectangle {
                id: track
                objectName: "progressTrack"
                anchors.fill: parent
                radius: root.barHeight / 2
                color: root.trackColor
            }

            Item {
                id: barClip
                anchors.fill: parent
                clip: true

                // Indeterminate beam: one soft sweep instead of competing rails.
                Rectangle {
                    id: beam
                    objectName: "progressBeam"
                    visible: root.indeterminate && !root.reducedMotion
                    height: root.barHeight
                    radius: root.barHeight / 2
                    width: Math.max(Theme.scaledGeometry(56), barClip.width * 0.45)
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Qt.rgba(root.effectiveAccentColor.r, root.effectiveAccentColor.g, root.effectiveAccentColor.b, 0.0) }
                        GradientStop { position: 0.35; color: root.effectiveAccentColor }
                        GradientStop { position: 0.65; color: root.effectiveAccentColor }
                        GradientStop { position: 1.0; color: Qt.rgba(root.effectiveAccentColor.r, root.effectiveAccentColor.g, root.effectiveAccentColor.b, 0.0) }
                    }

                    NumberAnimation on x {
                        running: root.indeterminate && root.visible && !root.reducedMotion
                        loops: Animation.Infinite
                        from: -beam.width
                        to: barClip.width
                        duration: 1200
                        easing.type: Easing.InOutCubic
                    }
                }

                // Reduced motion fallback: a settled track reads as "running",
                // never as a fabricated percentage.
                Rectangle {
                    objectName: "progressStaticBeam"
                    visible: root.indeterminate && root.reducedMotion
                    anchors.fill: parent
                    radius: root.barHeight / 2
                    color: root.effectiveAccentColor
                    opacity: 0.28
                }

                // Determinate fill. The rounded cap never collapses below the
                // track height, so low percentages stay legible as a dot.
                Rectangle {
                    id: fillBar
                    objectName: "progressFill"
                    visible: !root.indeterminate && root.animatedPosition > 0
                    height: root.barHeight
                    width: root.animatedPosition > 0
                        ? Math.max(Math.min(root.barHeight, barClip.width),
                                   Math.min(barClip.width, root.animatedPosition * barClip.width))
                        : 0
                    radius: Math.min(root.barHeight / 2, width / 2)

                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: root.effectiveAccentColor }
                        GradientStop { position: 1.0; color: Qt.lighter(root.effectiveAccentColor, 1.10) }
                    }
                }
            }

            Rectangle {
                id: marker
                objectName: "progressMarker"
                visible: root.markerPosition >= 0
                x: Math.max(0, Math.min(barClip.width - width, barClip.width * Math.max(0, Math.min(1, root.markerPosition))))
                anchors.verticalCenter: parent.verticalCenter
                width: 2
                height: root.barHeight + Theme.spaceXs
                radius: 1
                color: root.markerColor
                opacity: 0.7
            }
        }

        Text {
            id: percentageLabel
            objectName: "progressPercentage"
            visible: root.showPercentage
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            text: root.percentageText
            horizontalAlignment: Text.AlignRight
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeMicro
            font.weight: Theme.weightMedium
            renderType: Theme.textRenderType
            elide: Text.ElideRight
        }
    }
}
