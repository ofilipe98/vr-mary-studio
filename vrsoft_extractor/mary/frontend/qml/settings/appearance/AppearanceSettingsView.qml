import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"

ColumnLayout {
    id: root
    spacing: 24

    // Header
    RowLayout {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 12

        Rectangle {
            Layout.preferredWidth: 36
            Layout.preferredHeight: 36
            radius: Theme.radiusSmall
            color: Theme.palette.codeSurface
            border.width: 1
            border.color: Theme.palette.chatBorder

            VrLineIcon {
                anchors.centerIn: parent
                width: 18
                height: 18
                kind: "settings"
                foreground: Theme.palette.brandOrange
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 2

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "Aparência e Personalização"
                color: Theme.palette.headingText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(16)
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "Esquema de cores, biblioteca de temas, contraste, opacidade de vidro, movimento e tipografia."
                color: Theme.palette.subtleText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                wrapMode: Text.WordWrap
            }
        }
    }

    // 1. Esquema de Cores (Sistema / Claro / Escuro com preview em mini-janela)
    ColorSchemeSelector {
        Layout.fillWidth: true
    }

    Rectangle {
        Layout.fillWidth: true
        height: 1
        color: Theme.palette.border
    }

    // 2. Biblioteca de Temas (Integrados + Customizados com Exportação/Importação e Editor)
    ThemeLibrarySection {
        Layout.fillWidth: true
    }

    Rectangle {
        Layout.fillWidth: true
        height: 1
        color: Theme.palette.border
    }

    // 3. Sliders de Ajuste Visual (Contraste, Vidro, Movimento e Animações)
    AppearanceSlidersSection {
        Layout.fillWidth: true
    }

    Rectangle {
        Layout.fillWidth: true
        height: 1
        color: Theme.palette.border
    }

    // 4. Tipografia (Simples / Avançada com seletores reais de fonte e previews ao vivo)
    TypographySection {
        Layout.fillWidth: true
    }
}
