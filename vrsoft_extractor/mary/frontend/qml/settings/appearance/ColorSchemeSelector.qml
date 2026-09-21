import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
ColumnLayout {
    spacing: Theme.scaledGeometry(14)
    Text { text: "Esquema de cores"; Layout.leftMargin: Theme.scaledGeometry(16); font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); color: Theme.palette.text; opacity: .7 }
    RowLayout {
        Layout.fillWidth: true; spacing: Theme.scaledGeometry(12)
        Repeater {
            model: ["system", "light", "dark"]
            Button {
                id: card
                required property string modelData
                objectName: "colorScheme_" + modelData
                readonly property bool selected: frontend.appearanceMode === modelData
                Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 1
                implicitHeight: Math.max(116, Math.min(180, width * .655))
                padding: Theme.scaledGeometry(8); hoverEnabled: true
                Accessible.name: ({system: "Sistema", light: "Claro", dark: "Escuro"})[modelData]
                onClicked: frontend.setAppearanceMode(modelData)
                background: Rectangle {
                    radius: Theme.scaledGeometry(14)
                    color: card.selected || card.hovered ? Qt.tint(Theme.palette.background, Qt.alpha(Theme.palette.accentSoft, .35)) : Theme.palette.background
                    border.color: card.selected || card.visualFocus ? Theme.palette.focus : Theme.palette.border
                }
                contentItem: ColumnLayout {
                    spacing: Theme.scaledGeometry(6)
                    Item {
                        id: preview
                        Layout.fillWidth: true; Layout.fillHeight: true
                        ThemeWireframePane { anchors.fill: parent; isDark: card.modelData === "dark" }
                        Item {
                            visible: card.modelData === "system"
                            anchors.right: parent.right; height: parent.height; width: parent.width / 2
                            clip: true
                            ThemeWireframePane { x: -parent.width; width: preview.width; height: preview.height; isDark: true }
                        }
                    }
                    Text {
                        text: card.Accessible.name
                        Layout.alignment: Qt.AlignHCenter
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
                        font.weight: card.selected ? Font.DemiBold : Font.Normal
                        color: card.selected ? Theme.palette.text : Theme.palette.mutedText
                    }
                }
            }
        }
    }
}
