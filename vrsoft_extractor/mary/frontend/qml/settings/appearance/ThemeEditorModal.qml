import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../components"

Popup {
    id: modal

    property bool isEditing: false
    property string targetThemeId: ""
    property string themeName: "Novo Tema"
    property string themeAppearance: "dark"
    property string colorBackground: "#141416"
    property string colorSurface: "#1e1e21"
    property string colorBorder: "#2c2c30"
    property string colorAccent: "#ff7a00"
    property string colorText: "#f3f3f3"
    property string colorMuted: "#9da1a8"

    signal saved()

    modal: true
    focus: true
    dim: true
    Overlay.modal: Rectangle { color: Qt.alpha(Theme.palette.background, .85) }
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(680, parent ? parent.width - 40 : 680)
    height: Math.min(620, parent ? parent.height - 40 : 620)
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: Theme.radiusCard
        color: Qt.alpha(Theme.palette.surface, Theme.glassOpacity)
        border.width: 1
        border.color: Theme.palette.border
    }

    contentItem: ColumnLayout {
        spacing: 0

        // Header
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 52
            color: Theme.palette.surfaceRaised
            radius: Theme.radiusCard

            // Square bottom corners
            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: 10
                color: Theme.palette.surfaceRaised
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceLg
                anchors.rightMargin: Theme.spaceLg

                Text {
                    text: modal.isEditing ? "Editar Tema Personalizado" : "Criar Novo Tema"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.subtitleSize
                    font.weight: Font.DemiBold
                    color: Theme.palette.text
                    Layout.fillWidth: true
                }

                VrIconButton {
                    iconKind: "close"
                    ToolTip.text: "Fechar"
                    onClicked: modal.close()
                }
            }
        }

        // Body with ScrollView
        ScrollView {
            id: editorScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            leftPadding: 16
            rightPadding: 16
            topPadding: 16
            bottomPadding: 16

            ColumnLayout {
                width: editorScroll.availableWidth
                spacing: Theme.spaceLg

                // Basic details: Name and Appearance
                GridLayout {
                    columns: modal.width < 560 ? 1 : 2
                    Layout.fillWidth: true
                    columnSpacing: Theme.spaceMd
                    rowSpacing: Theme.spaceMd

                    ColumnLayout {
                        spacing: Theme.spaceXs
                        Layout.fillWidth: true

                        Text {
                            text: "Nome do tema"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            font.weight: Font.DemiBold
                            color: Theme.palette.text
                        }

                        VrTextField {
                            id: nameInput
                            objectName: "themeNameInput"
                            Layout.fillWidth: true
                            text: modal.themeName
                            placeholderText: "Ex: Neon Cyberpunk"
                            onTextChanged: modal.themeName = text
                        }
                    }

                    ColumnLayout {
                        spacing: Theme.spaceXs
                        Layout.preferredWidth: 160

                        Text {
                            text: "Aparência base"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            font.weight: Font.DemiBold
                            color: Theme.palette.text
                        }

                        RowLayout {
                            spacing: Theme.spaceSm

                            VrButton {
                                text: "Escuro"
                                variant: modal.themeAppearance === "dark" ? "primary" : "secondary"
                                implicitHeight: 36
                                onClicked: modal.themeAppearance = "dark"
                            }

                            VrButton {
                                text: "Claro"
                                variant: modal.themeAppearance === "light" ? "primary" : "secondary"
                                implicitHeight: 36
                                onClicked: modal.themeAppearance = "light"
                            }
                        }
                    }
                }

                // Live Preview Card
                ColumnLayout {
                    spacing: Theme.spaceXs
                    Layout.fillWidth: true

                    Text {
                        text: "Prévia em tempo real"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.captionSize
                        font.weight: Font.DemiBold
                        color: Theme.palette.mutedText
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 110
                        radius: Theme.radiusControl
                        color: modal.colorBackground
                        border.width: 1
                        border.color: modal.colorBorder
                        clip: true

                        RowLayout {
                            anchors.fill: parent
                            spacing: 0

                            // Mini sidebar
                            Rectangle {
                                Layout.fillHeight: true
                                Layout.preferredWidth: modal.width < 560 ? 72 : 120
                                color: modal.colorSurface
                                border.width: 1
                                border.color: modal.colorBorder

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: Theme.spaceSm
                                    spacing: 6

                                    Rectangle {
                                        width: 16; height: 16; radius: 4
                                        color: modal.colorAccent
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true; height: 6; radius: 3
                                        color: modal.colorMuted
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true; height: 6; radius: 3
                                        color: modal.colorBorder
                                    }
                                }
                            }

                            // Main area
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                anchors.margins: Theme.spaceMd
                                spacing: 8

                                Text {
                                    text: modal.themeName || "VRStudio"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.bodySize
                                    font.weight: Font.DemiBold
                                    color: modal.colorText
                                }

                                Text {
                                    text: "Prévia das cores selecionadas."
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.captionSize
                                    color: modal.colorMuted
                                }

                                RowLayout {
                                    spacing: Theme.spaceSm

                                    Rectangle {
                                        implicitHeight: 24
                                        implicitWidth: 70
                                        radius: 6
                                        color: modal.colorAccent

                                        Text {
                                            anchors.centerIn: parent
                                            text: "Ação"
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(11)
                                            font.weight: Font.DemiBold
                                            color: "#FFFFFF"
                                        }
                                    }

                                    Rectangle {
                                        implicitHeight: 24
                                        implicitWidth: 80
                                        radius: 6
                                        color: modal.colorSurface
                                        border.width: 1
                                        border.color: modal.colorBorder

                                        Text {
                                            anchors.centerIn: parent
                                            text: "Secundário"
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(11)
                                            color: modal.colorText
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Color Inputs Grid
                GridLayout {
                    columns: modal.width < 560 ? 1 : 2
                    rowSpacing: Theme.spaceMd
                    columnSpacing: Theme.spaceMd
                    Layout.fillWidth: true

                    // 1. Background
                    ColumnLayout {
                        spacing: Theme.spaceXs
                        Layout.fillWidth: true

                        Text { text: "Fundo principal"; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; color: Theme.palette.text }
                        RowLayout {
                            spacing: Theme.spaceSm
                            Rectangle { width: 32; height: 32; radius: 6; color: modal.colorBackground; border.width: 1; border.color: Theme.palette.border }
                            VrTextField {
                                id: colorBackgroundInput
                                objectName: "colorBackgroundInput"
                                Layout.fillWidth: true
                                text: modal.colorBackground
                                validator: RegularExpressionValidator { regularExpression: /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/ }
                                onTextChanged: if(acceptableInput) modal.colorBackground = text
                            }
                        }
                    }

                    // 2. Surface
                    ColumnLayout {
                        spacing: Theme.spaceXs
                        Layout.fillWidth: true

                        Text { text: "Superfície (cartões e barra lateral)"; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; color: Theme.palette.text }
                        RowLayout {
                            spacing: Theme.spaceSm
                            Rectangle { width: 32; height: 32; radius: 6; color: modal.colorSurface; border.width: 1; border.color: Theme.palette.border }
                            VrTextField {
                                id: colorSurfaceInput
                                objectName: "colorSurfaceInput"
                                Layout.fillWidth: true
                                text: modal.colorSurface
                                validator: RegularExpressionValidator { regularExpression: /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/ }
                                onTextChanged: if(acceptableInput) modal.colorSurface = text
                            }
                        }
                    }

                    // 3. Border
                    ColumnLayout {
                        spacing: Theme.spaceXs
                        Layout.fillWidth: true

                        Text { text: "Bordas e divisores"; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; color: Theme.palette.text }
                        RowLayout {
                            spacing: Theme.spaceSm
                            Rectangle { width: 32; height: 32; radius: 6; color: modal.colorBorder; border.width: 1; border.color: Theme.palette.border }
                            VrTextField {
                                id: colorBorderInput
                                objectName: "colorBorderInput"
                                Layout.fillWidth: true
                                text: modal.colorBorder
                                validator: RegularExpressionValidator { regularExpression: /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/ }
                                onTextChanged: if(acceptableInput) modal.colorBorder = text
                            }
                        }
                    }

                    // 4. Accent
                    ColumnLayout {
                        spacing: Theme.spaceXs
                        Layout.fillWidth: true

                        Text { text: "Cor primária / Destaque"; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; color: Theme.palette.text }
                        RowLayout {
                            spacing: Theme.spaceSm
                            Rectangle { width: 32; height: 32; radius: 6; color: modal.colorAccent; border.width: 1; border.color: Theme.palette.border }
                            VrTextField {
                                id: colorAccentInput
                                objectName: "colorAccentInput"
                                Layout.fillWidth: true
                                text: modal.colorAccent
                                validator: RegularExpressionValidator { regularExpression: /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/ }
                                onTextChanged: if(acceptableInput) modal.colorAccent = text
                            }
                        }
                    }

                    // 5. Text
                    ColumnLayout {
                        spacing: Theme.spaceXs
                        Layout.fillWidth: true

                        Text { text: "Texto principal"; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; color: Theme.palette.text }
                        RowLayout {
                            spacing: Theme.spaceSm
                            Rectangle { width: 32; height: 32; radius: 6; color: modal.colorText; border.width: 1; border.color: Theme.palette.border }
                            VrTextField {
                                id: colorTextInput
                                objectName: "colorTextInput"
                                Layout.fillWidth: true
                                text: modal.colorText
                                validator: RegularExpressionValidator { regularExpression: /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/ }
                                onTextChanged: if(acceptableInput) modal.colorText = text
                            }
                        }
                    }

                    // 6. Muted
                    ColumnLayout {
                        spacing: Theme.spaceXs
                        Layout.fillWidth: true

                        Text { text: "Texto secundário / suave"; font.family: Theme.fontFamily; font.pixelSize: Theme.captionSize; color: Theme.palette.text }
                        RowLayout {
                            spacing: Theme.spaceSm
                            Rectangle { width: 32; height: 32; radius: 6; color: modal.colorMuted; border.width: 1; border.color: Theme.palette.border }
                            VrTextField {
                                id: colorMutedInput
                                objectName: "colorMutedInput"
                                Layout.fillWidth: true
                                text: modal.colorMuted
                                validator: RegularExpressionValidator { regularExpression: /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/ }
                                onTextChanged: if(acceptableInput) modal.colorMuted = text
                            }
                        }
                    }
                }
            }
        }

        // Footer Actions
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 56
            color: Theme.palette.surfaceRaised
            radius: Theme.radiusCard

            // Square top corners
            Rectangle {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 10
                color: Theme.palette.surfaceRaised
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceLg
                anchors.rightMargin: Theme.spaceLg
                spacing: Theme.spaceMd

                Item { Layout.fillWidth: true }

                VrButton {
                    text: "Cancelar"
                    variant: "secondary"
                    onClicked: modal.close()
                }

                VrButton {
                    objectName: "themeSaveButton"
                    text: modal.isEditing ? "Salvar alterações" : "Criar tema"
                    enabled: modal.themeName.trim().length > 0 && colorBackgroundInput.acceptableInput && colorSurfaceInput.acceptableInput && colorBorderInput.acceptableInput && colorAccentInput.acceptableInput && colorTextInput.acceptableInput && colorMutedInput.acceptableInput
                    variant: "primary"
                    onClicked: {
                        var paletteMap = {
                            "background": modal.colorBackground,
                            "surface": modal.colorSurface,
                            "border": modal.colorBorder,
                            "brandOrange": modal.colorAccent,
                            "accessibleOrange": modal.colorAccent,
                            "text": modal.colorText,
                            "mutedText": modal.colorMuted,
                            "chatBackground": modal.colorBackground,
                            "chatSidebar": modal.colorSurface,
                            "codeSurface": modal.colorBackground,
                            "messageSurface": modal.colorSurface
                        }

                        if (modal.isEditing && modal.targetThemeId) {
                            frontend.updateCustomTheme(modal.targetThemeId, modal.themeName, modal.themeAppearance, paletteMap)
                        } else {
                            var newId = frontend.createCustomTheme(modal.themeName, modal.themeAppearance, frontend.themeId)
                            if (newId) {
                                frontend.updateCustomTheme(newId, modal.themeName, modal.themeAppearance, paletteMap)
                                if (modal.themeAppearance === "light") {
                                    frontend.setThemeForAppearance("light", newId)
                                } else {
                                    frontend.setThemeForAppearance("dark", newId)
                                }
                            }
                        }
                        modal.saved()
                        modal.close()
                    }
                }
            }
        }
    }
}
