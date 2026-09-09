import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"

ColumnLayout {
    id: root
    spacing: Theme.spaceMd
    Layout.fillWidth: true

    ColumnLayout {
        spacing: Theme.spaceXs
        Layout.fillWidth: true

        Text {
            text: "Esquema de cores"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.subtitleSize
            font.weight: Font.DemiBold
            color: Theme.palette.text
        }

        Text {
            text: "Escolha o modo de exibição preferido ou deixe o sistema operacional sincronizar automaticamente."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.captionSize
            color: Theme.palette.mutedText
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    RowLayout {
        spacing: Theme.spaceMd
        Layout.fillWidth: true

        // 1. Sistema
        Rectangle {
            id: systemCard
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            radius: Theme.radiusCard
            color: Theme.palette.surface
            border.width: frontend.appearanceMode === "system" ? 2 : 1
            border.color: frontend.appearanceMode === "system" ? Theme.palette.accessibleOrange : Theme.palette.border

            scale: !frontend.reduceMotion && systemArea.pressed ? 0.98 : 1.0
            Behavior on scale {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.pressDuration }
            }

            MouseArea {
                id: systemArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: frontend.setAppearanceMode("system")
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                // Mini Window illustration (Split light & dark)
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: Theme.radiusSmall
                    clip: true
                    color: "#18181b"
                    border.width: 1
                    border.color: Theme.palette.border

                    // Light half (left)
                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: parent.width * 0.5
                        color: "#f4f4f5"

                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: 18
                            color: "#e4e4e7"
                        }

                        Rectangle {
                            x: 24; y: 12
                            width: 32; height: 5
                            radius: 2
                            color: "#d4d4d8"
                        }
                        Rectangle {
                            x: 24; y: 22
                            width: 20; height: 5
                            radius: 2
                            color: "#ff7a00"
                        }
                    }

                    // Dark half (right)
                    Rectangle {
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: parent.width * 0.5
                        color: "#18181b"

                        Rectangle {
                            x: 8; y: 12
                            width: 32; height: 5
                            radius: 2
                            color: "#3f3f46"
                        }
                        Rectangle {
                            x: 8; y: 22
                            width: 24; height: 5
                            radius: 2
                            color: "#ff7a00"
                        }
                    }

                    // Split separator line
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 1
                        color: Theme.palette.border
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm

                    Rectangle {
                        width: 14; height: 14; radius: 7
                        border.width: frontend.appearanceMode === "system" ? 4 : 1
                        border.color: frontend.appearanceMode === "system" ? Theme.palette.accessibleOrange : Theme.palette.mutedText
                        color: "transparent"
                    }

                    Text {
                        text: "Sistema"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: frontend.appearanceMode === "system" ? Font.DemiBold : Font.Normal
                        color: Theme.palette.text
                        Layout.fillWidth: true
                    }
                }
            }
        }

        // 2. Claro
        Rectangle {
            id: lightCard
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            radius: Theme.radiusCard
            color: Theme.palette.surface
            border.width: frontend.appearanceMode === "light" ? 2 : 1
            border.color: frontend.appearanceMode === "light" ? Theme.palette.accessibleOrange : Theme.palette.border

            scale: !frontend.reduceMotion && lightArea.pressed ? 0.98 : 1.0
            Behavior on scale {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.pressDuration }
            }

            MouseArea {
                id: lightArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: frontend.setAppearanceMode("light")
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                // Mini Window illustration (Light)
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: Theme.radiusSmall
                    clip: true
                    color: "#f4f4f5"
                    border.width: 1
                    border.color: "#e4e4e7"

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 24
                        color: "#e4e4e7"

                        Rectangle { x: 6; y: 8; width: 12; height: 4; radius: 2; color: "#d4d4d8" }
                        Rectangle { x: 6; y: 16; width: 12; height: 4; radius: 2; color: "#d4d4d8" }
                    }

                    Rectangle { x: 32; y: 10; width: 44; height: 6; radius: 2; color: "#d4d4d8" }
                    Rectangle { x: 32; y: 20; width: 30; height: 6; radius: 2; color: "#ff7a00" }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm

                    Rectangle {
                        width: 14; height: 14; radius: 7
                        border.width: frontend.appearanceMode === "light" ? 4 : 1
                        border.color: frontend.appearanceMode === "light" ? Theme.palette.accessibleOrange : Theme.palette.mutedText
                        color: "transparent"
                    }

                    Text {
                        text: "Claro"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: frontend.appearanceMode === "light" ? Font.DemiBold : Font.Normal
                        color: Theme.palette.text
                        Layout.fillWidth: true
                    }
                }
            }
        }

        // 3. Escuro
        Rectangle {
            id: darkCard
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            radius: Theme.radiusCard
            color: Theme.palette.surface
            border.width: frontend.appearanceMode === "dark" ? 2 : 1
            border.color: frontend.appearanceMode === "dark" ? Theme.palette.accessibleOrange : Theme.palette.border

            scale: !frontend.reduceMotion && darkArea.pressed ? 0.98 : 1.0
            Behavior on scale {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.pressDuration }
            }

            MouseArea {
                id: darkArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: frontend.setAppearanceMode("dark")
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                // Mini Window illustration (Dark)
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: Theme.radiusSmall
                    clip: true
                    color: "#18181b"
                    border.width: 1
                    border.color: "#27272a"

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 24
                        color: "#27272a"

                        Rectangle { x: 6; y: 8; width: 12; height: 4; radius: 2; color: "#3f3f46" }
                        Rectangle { x: 6; y: 16; width: 12; height: 4; radius: 2; color: "#3f3f46" }
                    }

                    Rectangle { x: 32; y: 10; width: 44; height: 6; radius: 2; color: "#3f3f46" }
                    Rectangle { x: 32; y: 20; width: 30; height: 6; radius: 2; color: "#ff7a00" }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm

                    Rectangle {
                        width: 14; height: 14; radius: 7
                        border.width: frontend.appearanceMode === "dark" ? 4 : 1
                        border.color: frontend.appearanceMode === "dark" ? Theme.palette.accessibleOrange : Theme.palette.mutedText
                        color: "transparent"
                    }

                    Text {
                        text: "Escuro"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: frontend.appearanceMode === "dark" ? Font.DemiBold : Font.Normal
                        color: Theme.palette.text
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }
}
