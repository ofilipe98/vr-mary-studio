import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
Rectangle {
    id: root
    property string themeId: ""
    property string themeName: ""
    property var lightTheme: null
    property var darkTheme: null
    property bool isBuiltIn: true
    readonly property var activeTheme: frontend.resolvedAppearance === "light" ? (lightTheme || darkTheme) : (darkTheme || lightTheme)
    signal editRequested()
    signal duplicateRequested()
    signal exportRequested()
    signal deleteRequested()
    objectName: "themeCard_" + themeId
    Layout.fillWidth: true; Layout.minimumWidth: 0
    implicitHeight: 112 + Theme.fontSize(14); radius: Theme.scaledGeometry(14)
    color: cardArea.containsMouse ? Theme.palette.hover : Theme.palette.background
    border.color: Theme.palette.border
    MouseArea {
        id: cardArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
        onClicked: {
            if (root.lightTheme) frontend.setThemeForAppearance("light", root.lightTheme.id)
            if (root.darkTheme) frontend.setThemeForAppearance("dark", root.darkTheme.id)
        }
    }
    Row {
        anchors.horizontalCenter: parent.horizontalCenter; y: 12; spacing: Theme.scaledGeometry(10)
        Repeater {
            model: [root.lightTheme, root.darkTheme].filter(t => t !== null)
            ThemePreviewCircle {
                required property var modelData
                objectName: "themeVariant_" + modelData.id
                mode: modelData.appearance
                canvasColor: modelData.palette.previewCanvas || modelData.palette.background
                accentColor: modelData.palette.previewAccent || modelData.palette.accessibleOrange
                actionColor: modelData.palette.previewAction || modelData.palette.accessibleOrange
                isActive: (mode === "light" ? frontend.themeLight : frontend.themeDark) === modelData.id
                onClicked: frontend.setThemeForAppearance(mode, modelData.id)
            }
        }
    }
    RowLayout {
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.margins: Theme.scaledGeometry(12); spacing: 2
        Text {
            text: root.themeName; color: Theme.palette.text
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); font.weight: Font.DemiBold
            Layout.fillWidth: true; elide: Text.ElideRight
        }
        AppearanceAction { visible: !root.isBuiltIn; quiet: true; iconKind: "edit"; Accessible.name: "Editar tema"; onClicked: root.editRequested() }
        AppearanceAction { visible: !root.isBuiltIn; quiet: true; iconKind: "download"; Accessible.name: "Exportar tema"; onClicked: root.exportRequested() }
        AppearanceAction { visible: !root.isBuiltIn; quiet: true; iconKind: "trash"; Accessible.name: "Excluir tema"; onClicked: root.deleteRequested() }
        AppearanceAction { objectName: "duplicateTheme_" + root.themeId; quiet: true; iconKind: "copy"; Accessible.name: "Duplicar tema"; onClicked: root.duplicateRequested() }
    }
}
