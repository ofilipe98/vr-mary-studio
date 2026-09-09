import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"

ColumnLayout {
    id: root
    spacing: Theme.spaceLg
    Layout.fillWidth: true

    // ========================================================================
    // 1. Contraste
    // ========================================================================
    ColumnLayout {
        spacing: Theme.spaceSm
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true

                RowLayout {
                    spacing: Theme.spaceSm

                    Text {
                        text: "Contraste"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: Font.DemiBold
                        color: Theme.palette.text
                    }

                    // Default badge
                    Rectangle {
                        visible: frontend.appearanceContrast === 100
                        implicitHeight: 18
                        implicitWidth: defaultContrastText.implicitWidth + 10
                        radius: 9
                        color: Qt.alpha(Theme.palette.mutedText, 0.15)

                        Text {
                            id: defaultContrastText
                            anchors.centerIn: parent
                            text: "Padrão"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(10)
                            color: Theme.palette.mutedText
                        }
                    }
                }

                Text {
                    text: "Ajusta a nitidez de bordas, divisores e relevo de superfícies."
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    color: Theme.palette.mutedText
                }
            }

            Text {
                text: frontend.appearanceContrast + "%"
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.palette.accessibleOrange
            }

            VrButton {
                visible: frontend.appearanceContrast !== 100
                text: "Redefinir"
                variant: "ghost"
                implicitHeight: 28
                onClicked: frontend.resetAppearanceSetting("contrast")
            }
        }

        VrSlider {
            Layout.fillWidth: true
            from: 50
            to: 200
            stepSize: 5
            value: frontend.appearanceContrast
            onMoved: frontend.setAppearanceContrast(Math.round(value))
        }
    }

    // Divider
    Rectangle {
        Layout.fillWidth: true
        height: 1
        color: Theme.palette.border
    }

    // ========================================================================
    // 2. Opacidade de vidro (Glass Opacity)
    // ========================================================================
    ColumnLayout {
        spacing: Theme.spaceSm
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true

                RowLayout {
                    spacing: Theme.spaceSm

                    Text {
                        text: "Opacidade de superfícies translúcidas (Vidro)"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: Font.DemiBold
                        color: Theme.palette.text
                    }

                    Rectangle {
                        visible: frontend.glassOpacity === 80
                        implicitHeight: 18
                        implicitWidth: defaultGlassText.implicitWidth + 10
                        radius: 9
                        color: Qt.alpha(Theme.palette.mutedText, 0.15)

                        Text {
                            id: defaultGlassText
                            anchors.centerIn: parent
                            text: "Padrão"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(10)
                            color: Theme.palette.mutedText
                        }
                    }
                }

                Text {
                    text: "Controla a translucidez e densidade de painéis suspensos, popovers e backdrop."
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    color: Theme.palette.mutedText
                }
            }

            Text {
                text: frontend.glassOpacity + "%"
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.palette.accessibleOrange
            }

            VrButton {
                visible: frontend.glassOpacity !== 80
                text: "Redefinir"
                variant: "ghost"
                implicitHeight: 28
                onClicked: frontend.resetAppearanceSetting("glass")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceMd

            VrSlider {
                Layout.fillWidth: true
                from: 40
                to: 100
                stepSize: 5
                value: frontend.glassOpacity
                onMoved: frontend.setGlassOpacity(Math.round(value))
            }

            // Translucent Glass swatch demo
            Rectangle {
                Layout.preferredWidth: 100
                Layout.preferredHeight: 32
                radius: Theme.radiusSmall
                clip: true

                // Background gradient stripes
                Rectangle {
                    anchors.fill: parent
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "#ff7a00" }
                        GradientStop { position: 0.5; color: "#7aa2f7" }
                        GradientStop { position: 1.0; color: "#38bdf8" }
                    }
                }

                // Frosted glass overlay
                Rectangle {
                    anchors.fill: parent
                    color: Qt.alpha(Theme.palette.surface, frontend.glassOpacity / 100.0)
                    border.width: 1
                    border.color: Qt.alpha(Theme.palette.border, 0.8)

                    Text {
                        anchors.centerIn: parent
                        text: "Acrílico"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(10)
                        font.weight: Font.DemiBold
                        color: Theme.palette.text
                    }
                }
            }
        }
    }

    // Divider
    Rectangle {
        Layout.fillWidth: true
        height: 1
        color: Theme.palette.border
    }

    // ========================================================================
    // 3. Animações e Movimento
    // ========================================================================
    ColumnLayout {
        spacing: Theme.spaceSm
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true

                RowLayout {
                    spacing: Theme.spaceSm

                    Text {
                        text: "Animações de painéis e movimento"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: Font.DemiBold
                        color: Theme.palette.text
                    }

                    Rectangle {
                        visible: frontend.rawPanelAnimationDurationMs === 0
                        implicitHeight: 18
                        implicitWidth: defaultMotionText.implicitWidth + 10
                        radius: 9
                        color: Qt.alpha(Theme.palette.mutedText, 0.15)

                        Text {
                            id: defaultMotionText
                            anchors.centerIn: parent
                            text: "Padrão (Instantâneo)"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(10)
                            color: Theme.palette.mutedText
                        }
                    }
                }

                Text {
                    text: frontend.reduceMotion
                        ? "O modo 'Reduzir movimento' está ativo no aplicativo."
                        : "Duração das transições suaves de abertura e expansão de painéis."
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    color: frontend.reduceMotion ? Theme.palette.accessibleOrange : Theme.palette.mutedText
                }
            }

            Text {
                text: frontend.reduceMotion ? "0 ms (Reduzido)" : (frontend.rawPanelAnimationDurationMs === 0 ? "0 ms (Instantâneo)" : frontend.rawPanelAnimationDurationMs + " ms")
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.palette.accessibleOrange
            }

            VrButton {
                visible: frontend.rawPanelAnimationDurationMs !== 0
                text: "Redefinir"
                variant: "ghost"
                implicitHeight: 28
                onClicked: frontend.resetAppearanceSetting("motion")
            }
        }

        VrSlider {
            Layout.fillWidth: true
            from: 0
            to: 400
            stepSize: 25
            enabled: !frontend.reduceMotion
            value: frontend.rawPanelAnimationDurationMs
            onMoved: frontend.setPanelAnimationDurationMs(Math.round(value))
        }

        // Interactive motion preview widget
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            radius: Theme.radiusControl
            color: Theme.palette.surfaceRaised
            border.width: 1
            border.color: Theme.palette.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceMd
                anchors.rightMargin: Theme.spaceMd
                spacing: Theme.spaceMd

                VrButton {
                    text: "Testar animação"
                    variant: "secondary"
                    implicitHeight: 30
                    onClicked: motionBox.movingRight = !motionBox.movingRight
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    Rectangle {
                        id: motionBox
                        property bool movingRight: false
                        width: 80
                        height: 28
                        radius: 6
                        anchors.verticalCenter: parent.verticalCenter
                        x: movingRight ? parent.width - width : 0
                        color: Theme.palette.accessibleOrange

                        Behavior on x {
                            enabled: !frontend.reduceMotion
                            NumberAnimation {
                                duration: frontend.panelAnimationDurationMs > 0 ? frontend.panelAnimationDurationMs : 180
                                easing.type: Easing.OutCubic
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            text: frontend.panelAnimationDurationMs + " ms"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(10)
                            font.weight: Font.DemiBold
                            color: "#FFFFFF"
                        }
                    }
                }
            }
        }

        // Reduce Motion switch
        VrSettingsRow {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 3
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: "Reduzir movimento"
                    color: Theme.palette.headingText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: "Desativa animações e transições decorativas para maior fluidez e acessibilidade."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    wrapMode: Text.WordWrap
                }
            }

            VrSwitch {
                subdued: true
                Layout.alignment: Qt.AlignRight
                checked: frontend.reduceMotion
                onToggled: frontend.setReduceMotion(checked)
            }
        }
    }
}
