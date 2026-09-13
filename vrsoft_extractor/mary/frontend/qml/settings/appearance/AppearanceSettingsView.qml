import QtQuick
import QtQuick.Layouts

ColumnLayout {
    objectName: "appearanceSettingsView"
    Layout.minimumWidth: 0
    spacing: 36
    ColorSchemeSelector { Layout.fillWidth: true }
    ThemeLibrarySection { Layout.fillWidth: true; Layout.topMargin: -16 }
    AppearanceSlidersSection { Layout.fillWidth: true }
    TypographySection { Layout.fillWidth: true }
}
