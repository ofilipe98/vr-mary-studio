import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"

ColumnLayout {
    id: root
    spacing: Theme.spaceMd
    Layout.fillWidth: true

    // Section Header
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spaceMd

        ColumnLayout {
            spacing: Theme.spaceXs
            Layout.fillWidth: true

            Text {
                text: "Biblioteca de temas"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.subtitleSize
                font.weight: Font.DemiBold
                color: Theme.palette.text
            }

            Text {
                text: "Explore temas integrados ou crie paletas customizadas com exportação e importação flexível."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.captionSize
                color: Theme.palette.mutedText
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        RowLayout {
            spacing: Theme.spaceSm

            VrButton {
                text: "Importar tema"
                variant: "secondary"
                onClicked: importModal.open()
            }

            VrButton {
                text: "Criar novo tema"
                variant: "primary"
                onClicked: {
                    editorModal.isEditing = false
                    editorModal.targetThemeId = ""
                    editorModal.themeName = "Meu Tema Customizado"
                    editorModal.themeAppearance = frontend.resolvedAppearance
                    editorModal.colorBackground = frontend.palette.background || "#141416"
                    editorModal.colorSurface = frontend.palette.surface || "#1e1e21"
                    editorModal.colorBorder = frontend.palette.border || "#2c2c30"
                    editorModal.colorAccent = frontend.palette.brandOrange || "#ff7a00"
                    editorModal.colorText = frontend.palette.text || "#f3f3f3"
                    editorModal.colorMuted = frontend.palette.mutedText || "#9da1a8"
                    editorModal.open()
                }
            }
        }
    }

    // Grid of Theme Cards
    GridLayout {
        id: themesGrid
        columns: root.width > 700 ? 2 : 1
        rowSpacing: Theme.spaceMd
        columnSpacing: Theme.spaceMd
        Layout.fillWidth: true

        Repeater {
            model: frontend.availableThemes

            ThemeCard {
                themeData: modelData

                onEditRequested: {
                    editorModal.isEditing = true
                    editorModal.targetThemeId = modelData.id
                    editorModal.themeName = modelData.name
                    editorModal.themeAppearance = modelData.appearance
                    editorModal.colorBackground = modelData.palette ? modelData.palette.background : "#141416"
                    editorModal.colorSurface = modelData.palette ? modelData.palette.surface : "#1e1e21"
                    editorModal.colorBorder = modelData.palette ? modelData.palette.border : "#2c2c30"
                    editorModal.colorAccent = modelData.palette ? (modelData.palette.brandOrange || modelData.palette.accessibleOrange) : "#ff7a00"
                    editorModal.colorText = modelData.palette ? modelData.palette.text : "#f3f3f3"
                    editorModal.colorMuted = modelData.palette ? modelData.palette.mutedText : "#9da1a8"
                    editorModal.open()
                }

                onDuplicateRequested: {
                    frontend.duplicateTheme(modelData.id, (modelData.name || "Tema") + " (Cópia)")
                }

                onExportRequested: {
                    var jsonStr = frontend.exportThemeJson(modelData.id)
                    exportModal.jsonContent = jsonStr
                    exportModal.themeName = modelData.name
                    exportModal.open()
                }

                onDeleteRequested: {
                    frontend.deleteCustomTheme(modelData.id)
                }
            }
        }
    }

    // Modals
    ThemeEditorModal {
        id: editorModal
    }

    ThemeImportModal {
        id: importModal
    }

    // Export Modal (Viewer / Copy)
    ThemeExportModal {
        id: exportModal
    }
}
