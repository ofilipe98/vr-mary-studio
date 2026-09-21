import QtQuick
import "../../theme"
import QtQuick.Layouts
import "../../theme"
import "../../components"

ColumnLayout {
    objectName: "appearanceSettingsView"
    Layout.minimumWidth: 0
    spacing: Theme.scaledGeometry(36)
    ColorSchemeSelector { Layout.fillWidth: true }
    ThemeLibrarySection { Layout.fillWidth: true; Layout.topMargin: -16 }
    AppearanceSlidersSection { Layout.fillWidth: true }
    AppearanceGroup {
        Layout.fillWidth: true
        AppearanceRow {
            title: "Escala da interface"
            description: "Amplia textos, controles e espaçamento. Ctrl + / Ctrl − ajustam; Ctrl 0 restaura. A escala do Windows continua independente."
            divider: false
            VrComboBox {
                objectName: "appearanceScaleCombo"
                implicitWidth: Theme.scaledGeometry(120)
                model: ["90%", "100%", "110%", "125%", "150%"]
                property var values: ["90", "100", "110", "125", "150"]
                currentIndex: values.indexOf(frontend.uiScale === "auto" ? "100" : frontend.uiScale)
                displayText: Math.round(frontend.uiScaleFactor * 100) + "%"
                onActivated: index => frontend.setUiScale(values[index])
            }
        }
    }
    TypographySection { Layout.fillWidth: true }
}
