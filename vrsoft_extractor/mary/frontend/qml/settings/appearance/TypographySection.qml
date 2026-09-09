import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"

ColumnLayout {
    id: root
    spacing: Theme.spaceLg
    Layout.fillWidth: true

    // Header & Advanced Toggle
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spaceMd

        ColumnLayout {
            spacing: Theme.spaceXs
            Layout.fillWidth: true

            Text {
                text: "Tipografia"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.subtitleSize
                font.weight: Font.DemiBold
                color: Theme.palette.text
            }

            Text {
                text: "Personalize famílias e tamanhos tipográficos para interface, prompt, código e terminal."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.captionSize
                color: Theme.palette.mutedText
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        RowLayout {
            spacing: Theme.spaceSm

            Text {
                text: "Modo avançado"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.captionSize
                font.weight: Font.DemiBold
                color: frontend.typographyAdvanced ? Theme.palette.accessibleOrange : Theme.palette.mutedText
            }

            VrSwitch {
                checked: frontend.typographyAdvanced
                onToggled: frontend.setTypographyAdvanced(checked)
            }
        }
    }

    // ========================================================================
    // 1. Interface Typography
    // ========================================================================
    ColumnLayout {
        spacing: Theme.spaceSm
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            Text {
                text: "Interface"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.palette.text
                Layout.fillWidth: true
            }

            Text {
                text: frontend.interfaceFontFamily + " · " + frontend.interfaceFontSize + "px"
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.captionSize
                color: Theme.palette.accessibleOrange
            }

            VrButton {
                visible: frontend.interfaceFontFamily !== "Segoe UI" || frontend.interfaceFontSize !== 14
                text: "Redefinir"
                variant: "ghost"
                implicitHeight: 28
                onClicked: frontend.resetAppearanceSetting("typography_interface")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceMd

            VrButton {
                text: frontend.interfaceFontFamily
                variant: "secondary"
                Layout.fillWidth: true
                implicitHeight: Theme.controlHeight
                onClicked: {
                    interfacePicker.selectedFamily = frontend.interfaceFontFamily
                    interfacePicker.monospaceOnly = false
                    interfacePicker.open()
                }
            }

            VrSlider {
                Layout.preferredWidth: 160
                from: 12
                to: 20
                stepSize: 1
                value: frontend.interfaceFontSize
                onMoved: frontend.setInterfaceTypography(frontend.interfaceFontFamily, Math.round(value))
            }
        }

        // Live Interface Preview
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 54
            radius: Theme.radiusControl
            color: Theme.palette.surfaceRaised
            border.width: 1
            border.color: Theme.palette.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceMd
                anchors.rightMargin: Theme.spaceMd
                spacing: Theme.spaceMd

                Rectangle { width: 10; height: 10; radius: 5; color: Theme.palette.accessibleOrange }

                Text {
                    text: "Painel de controle, menus, barras de navegação e cartões de projeto."
                    font.family: frontend.interfaceFontFamily
                    font.pixelSize: Theme.fontSize(frontend.interfaceFontSize)
                    color: Theme.palette.text
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }
    }

    // ========================================================================
    // 2. Prompt Typography (Advanced mode)
    // ========================================================================
    ColumnLayout {
        visible: frontend.typographyAdvanced
        spacing: Theme.spaceSm
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            Text {
                text: "Composer de Prompt"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.palette.text
                Layout.fillWidth: true
            }

            Text {
                text: (frontend.promptFontFamily || frontend.interfaceFontFamily) + " · " + frontend.promptFontSize + "px"
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.captionSize
                color: Theme.palette.accessibleOrange
            }

            VrButton {
                visible: frontend.promptFontFamily.length > 0 || frontend.promptFontSize !== 14
                text: "Redefinir"
                variant: "ghost"
                implicitHeight: 28
                onClicked: frontend.resetAppearanceSetting("typography_prompt")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceMd

            VrButton {
                text: frontend.promptFontFamily || "Mesma da Interface (" + frontend.interfaceFontFamily + ")"
                variant: "secondary"
                Layout.fillWidth: true
                implicitHeight: Theme.controlHeight
                onClicked: {
                    promptPicker.selectedFamily = frontend.promptFontFamily || frontend.interfaceFontFamily
                    promptPicker.monospaceOnly = false
                    promptPicker.open()
                }
            }

            VrSlider {
                Layout.preferredWidth: 160
                from: 12
                to: 20
                stepSize: 1
                value: frontend.promptFontSize
                onMoved: frontend.setPromptTypography(frontend.promptFontFamily, Math.round(value))
            }
        }

        // Live Prompt Preview
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 54
            radius: Theme.radiusControl
            color: Theme.palette.surfaceRaised
            border.width: 1
            border.color: Theme.palette.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceMd
                anchors.rightMargin: Theme.spaceMd
                spacing: Theme.spaceMd

                Text {
                    text: "Como posso ajudar você a refatorar o extrator de dados hoje?"
                    font.family: frontend.promptFontFamily || frontend.interfaceFontFamily
                    font.pixelSize: Theme.fontSize(frontend.promptFontSize)
                    font.italic: true
                    color: Theme.palette.text
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }
    }

    // ========================================================================
    // 3. Code Typography
    // ========================================================================
    ColumnLayout {
        spacing: Theme.spaceSm
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            Text {
                text: "Código"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.palette.text
                Layout.fillWidth: true
            }

            Text {
                text: frontend.codeFontFamily + " · " + frontend.codeFontSize + "px"
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.captionSize
                color: Theme.palette.accessibleOrange
            }

            VrButton {
                visible: frontend.codeFontFamily !== "Consolas" || frontend.codeFontSize !== 13
                text: "Redefinir"
                variant: "ghost"
                implicitHeight: 28
                onClicked: frontend.resetAppearanceSetting("typography_code")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceMd

            VrButton {
                text: frontend.codeFontFamily
                variant: "secondary"
                Layout.fillWidth: true
                implicitHeight: Theme.controlHeight
                onClicked: {
                    codePicker.selectedFamily = frontend.codeFontFamily
                    codePicker.monospaceOnly = true
                    codePicker.open()
                }
            }

            VrSlider {
                Layout.preferredWidth: 160
                from: 10
                to: 18
                stepSize: 1
                value: frontend.codeFontSize
                onMoved: frontend.setCodeTypography(frontend.codeFontFamily, Math.round(value))
            }
        }

        // Live Code Syntax Preview
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 64
            radius: Theme.radiusControl
            color: Theme.palette.background
            border.width: 1
            border.color: Theme.palette.border

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceSm
                spacing: Theme.spaceMd

                // Line numbers
                ColumnLayout {
                    spacing: 4
                    Text { text: "1"; font.family: frontend.codeFontFamily; font.pixelSize: Theme.monospaceFontSize(frontend.codeFontSize); color: Theme.palette.mutedText }
                    Text { text: "2"; font.family: frontend.codeFontFamily; font.pixelSize: Theme.monospaceFontSize(frontend.codeFontSize); color: Theme.palette.mutedText }
                }

                // Code snippet
                ColumnLayout {
                    spacing: 4
                    Layout.fillWidth: true
                    Text {
                        text: "const appearance = await themeManager.resolveMode();"
                        font.family: frontend.codeFontFamily
                        font.pixelSize: Theme.monospaceFontSize(frontend.codeFontSize)
                        color: "#38bdf8"
                    }
                    Text {
                        text: "console.log(`Current palette: ${appearance.theme}`);"
                        font.family: frontend.codeFontFamily
                        font.pixelSize: Theme.monospaceFontSize(frontend.codeFontSize)
                        color: Theme.palette.accessibleOrange
                    }
                }
            }
        }
    }

    // ========================================================================
    // 4. Terminal Typography (Advanced mode)
    // ========================================================================
    ColumnLayout {
        visible: frontend.typographyAdvanced
        spacing: Theme.spaceSm
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            Text {
                text: "Terminal e Logs"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.palette.text
                Layout.fillWidth: true
            }

            Text {
                text: (frontend.terminalFontFamily || frontend.codeFontFamily) + " · " + frontend.terminalFontSize + "px"
                font.family: Theme.monospaceFontFamily
                font.pixelSize: Theme.captionSize
                color: Theme.palette.accessibleOrange
            }

            VrButton {
                visible: frontend.terminalFontFamily.length > 0 || frontend.terminalFontSize !== 12
                text: "Redefinir"
                variant: "ghost"
                implicitHeight: 28
                onClicked: frontend.resetAppearanceSetting("typography_terminal")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceMd

            VrButton {
                text: frontend.terminalFontFamily || "Mesma do Código (" + frontend.codeFontFamily + ")"
                variant: "secondary"
                Layout.fillWidth: true
                implicitHeight: Theme.controlHeight
                onClicked: {
                    terminalPicker.selectedFamily = frontend.terminalFontFamily || frontend.codeFontFamily
                    terminalPicker.monospaceOnly = true
                    terminalPicker.open()
                }
            }

            VrSlider {
                Layout.preferredWidth: 160
                from: 8
                to: 20
                stepSize: 1
                value: frontend.terminalFontSize
                onMoved: frontend.setTerminalTypography(frontend.terminalFontFamily, Math.round(value))
            }
        }

        // Live Terminal Preview
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 56
            radius: Theme.radiusControl
            color: "#0d1117"
            border.width: 1
            border.color: Theme.palette.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceMd
                anchors.rightMargin: Theme.spaceMd
                spacing: Theme.spaceSm

                Text {
                    text: "$ pytest tests/test_theme_manager.py\n[OK] 11 tests passed in 0.39s"
                    font.family: frontend.terminalFontFamily || frontend.codeFontFamily
                    font.pixelSize: Theme.terminalFontSize(frontend.terminalFontSize)
                    color: "#3fb950"
                    Layout.fillWidth: true
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
    // 5. Suavização de fontes e Quebra automática
    // ========================================================================
    ColumnLayout {
        spacing: Theme.spaceMd
        Layout.fillWidth: true

        VrSettingsRow {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 3
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: "Suavização subpixel de fontes"
                    color: Theme.palette.headingText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: frontend.isMacOS
                        ? "Ativa o renderizador antialiasing subpixel nativo no macOS."
                        : "Controle otimizado de renderização ClearType/antialiasing para Windows e Linux."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    wrapMode: Text.WordWrap
                }
            }

            VrSwitch {
                subdued: true
                Layout.alignment: Qt.AlignRight
                checked: frontend.fontSmoothing
                onToggled: frontend.setFontSmoothing(checked)
            }
        }

        VrSettingsRow {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 3
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: "Quebra automática de linha (Word wrap)"
                    color: Theme.palette.headingText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: "Quebra linhas longas nos blocos de código e transcrições para evitar rolagem horizontal excessiva."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    wrapMode: Text.WordWrap
                }
            }

            VrSwitch {
                subdued: true
                Layout.alignment: Qt.AlignRight
                checked: frontend.wordWrap
                onToggled: frontend.setWordWrap(checked)
            }
        }
    }

    // Pickers Popups
    FontFamilyPicker {
        id: interfacePicker
        onFamilySelected: function(fam) {
            frontend.setInterfaceTypography(fam, frontend.interfaceFontSize)
        }
    }

    FontFamilyPicker {
        id: promptPicker
        onFamilySelected: function(fam) {
            frontend.setPromptTypography(fam, frontend.promptFontSize)
        }
    }

    FontFamilyPicker {
        id: codePicker
        onFamilySelected: function(fam) {
            frontend.setCodeTypography(fam, frontend.codeFontSize)
        }
    }

    FontFamilyPicker {
        id: terminalPicker
        onFamilySelected: function(fam) {
            frontend.setTerminalTypography(fam, frontend.terminalFontSize)
        }
    }
}
