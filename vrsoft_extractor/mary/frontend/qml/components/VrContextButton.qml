import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    property real fraction: 0
    property string usageLabel: "Aguardando dados"
    property string totalLabel: "0 tokens"
    property string note: "Atualizado conforme os dados enviados pelo provedor."
    property bool detailsPinned: false

    function openDetails() {
        detailsPinned = true
        detailsPopup.open()
    }

    implicitWidth: 30
    implicitHeight: 30
    padding: 0
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && control.down ? 0.92 : 1
    Accessible.name: "Uso da janela de contexto"

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    onClicked: {
        if (detailsPopup.opened && detailsPinned) {
            detailsPinned = false
            detailsPopup.close()
        } else {
            openDetails()
        }
    }
    onHoveredChanged: {
        if (hovered) {
            hoverClose.stop()
            if (!detailsPopup.opened) detailsPopup.open()
        } else if (!detailsPinned) {
            hoverClose.restart()
        }
    }

    contentItem: Canvas {
        id: meter
        anchors.centerIn: parent
        width: 18
        height: 18

        onPaint: {
            var context = getContext("2d")
            context.reset()
            context.lineWidth = 2.2
            context.lineCap = "round"
            context.strokeStyle = frontend.themeId === "dark_orange" ? "#424247" : "#B8B8C0"
            context.beginPath()
            context.arc(width / 2, height / 2, 6.3, 0, Math.PI * 2)
            context.stroke()
            if (control.fraction > 0) {
                context.strokeStyle = Theme.palette.brandOrange
                context.beginPath()
                context.arc(
                    width / 2,
                    height / 2,
                    6.3,
                    -Math.PI / 2,
                    -Math.PI / 2 + Math.PI * 2 * Math.min(1, control.fraction)
                )
                context.stroke()
            }
        }

        Connections {
            target: control
            function onFractionChanged() { meter.requestPaint() }
        }
        Connections {
            target: frontend
            function onThemeChanged() { meter.requestPaint() }
        }
    }

    background: Rectangle {
        radius: 8
        color: control.down || control.hovered || detailsPopup.opened
            ? Theme.palette.chatControl : "transparent"
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.palette.focus
        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Timer {
        id: hoverClose
        interval: 140
        onTriggered: {
            if (!control.hovered && !popupHover.hovered && !control.detailsPinned)
                detailsPopup.close()
        }
    }

    Popup {
        id: detailsPopup
        objectName: "contextUsagePopup"
        parent: control
        x: control.width - width
        y: -height - 7
        width: 286
        height: 126
        padding: 12
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: control.detailsPinned = false

        HoverHandler {
            id: popupHover
            onHoveredChanged: {
                if (hovered) hoverClose.stop()
                else if (!control.detailsPinned) hoverClose.restart()
            }
        }

        background: Rectangle {
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: 11
        }

        contentItem: ColumnLayout {
            spacing: 7

            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: "Context Window"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                    font.weight: Theme.weightMedium
                }
                Text {
                    text: control.usageLabel
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                }
            }

            VrProgressBar {
                Layout.fillWidth: true
                barHeight: 5
                accentColor: control.fraction > 0.9 ? Theme.palette.danger : (control.fraction > 0.75 ? Theme.palette.warning : Theme.palette.brandOrange)
                from: 0
                to: 1
                value: control.fraction
            }

            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: "Total processado"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                }
                Text {
                    text: control.totalLabel
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                }
            }

            Text {
                Layout.fillWidth: true
                text: control.note
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeMicro
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }
    }
}
