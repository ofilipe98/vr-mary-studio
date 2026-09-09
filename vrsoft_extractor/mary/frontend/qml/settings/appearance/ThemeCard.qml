import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"

Rectangle {
    id: root

    property var themeData: ({})
    property bool isCurrentLight: frontend.themeLight === (themeData.id || "")
    property bool isCurrentDark: frontend.themeDark === (themeData.id || "")
    property bool isCurrentActive: frontend.themeId === (themeData.id || "")
    property bool isCustom: !(themeData.builtIn === true)

    signal editRequested()
    signal duplicateRequested()
    signal exportRequested()
    signal deleteRequested()

    Layout.fillWidth: true
    Layout.preferredHeight: 130
    radius: Theme.radiusCard
    color: Theme.palette.surface
    border.width: isCurrentActive ? 2 : 1
    border.color: isCurrentActive ? Theme.palette.accessibleOrange : (mouseArea.hovered ? Theme.palette.border : Qt.alpha(Theme.palette.border, 0.6))

    scale: !frontend.reduceMotion && mouseArea.pressed ? 0.99 : 1.0
    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            if (root.themeData.appearance === "light") {
                frontend.setThemeForAppearance("light", root.themeData.id)
            } else {
                frontend.setThemeForAppearance("dark", root.themeData.id)
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceMd
        spacing: Theme.spaceSm

        // Header: Name, Mode Badge, Active Badge
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            Text {
                text: root.themeData.name || "Tema"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.palette.text
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            // Appearance badge (Claro / Escuro)
            Rectangle {
                implicitHeight: 20
                implicitWidth: badgeText.implicitWidth + 12
                radius: 10
                color: root.themeData.appearance === "light" ? "#fef3c7" : "#27272a"
                border.width: 1
                border.color: root.themeData.appearance === "light" ? "#fde68a" : "#3f3f46"

                Text {
                    id: badgeText
                    anchors.centerIn: parent
                    text: root.themeData.appearance === "light" ? "Claro" : "Escuro"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(10)
                    font.weight: Font.DemiBold
                    color: root.themeData.appearance === "light" ? "#92400e" : "#e4e4e7"
                }
            }

            // Active indicator badge
            Rectangle {
                visible: root.isCurrentActive
                implicitHeight: 20
                implicitWidth: activeLabel.implicitWidth + 12
                radius: 10
                color: Qt.alpha(Theme.palette.accessibleOrange, 0.15)
                border.width: 1
                border.color: Theme.palette.accessibleOrange

                Text {
                    id: activeLabel
                    anchors.centerIn: parent
                    text: "Ativo"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(10)
                    font.weight: Font.DemiBold
                    color: Theme.palette.accessibleOrange
                }
            }
        }

        // Palette Color Swatches Preview
        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Repeater {
                model: [
                    root.themeData.palette ? root.themeData.palette.background : "#18181b",
                    root.themeData.palette ? root.themeData.palette.surface : "#27272a",
                    root.themeData.palette ? root.themeData.palette.border : "#3f3f46",
                    root.themeData.palette ? (root.themeData.palette.brandOrange || root.themeData.palette.accessibleOrange) : "#ff7a00",
                    root.themeData.palette ? root.themeData.palette.text : "#f4f4f5"
                ]

                Rectangle {
                    width: 22
                    height: 22
                    radius: 11
                    color: modelData || "#333333"
                    border.width: 1
                    border.color: Qt.alpha(Theme.palette.border, 0.8)
                }
            }

            Item { Layout.fillWidth: true }
        }

        // Action Toolbar
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            Text {
                text: root.isCustom ? "Personalizado" : "Padrão"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.captionSize
                color: Theme.palette.mutedText
                Layout.fillWidth: true
            }

            VrButton {
                text: "Duplicar"
                variant: "ghost"
                implicitHeight: 28
                onClicked: root.duplicateRequested()
            }

            VrButton {
                text: "Exportar"
                variant: "ghost"
                implicitHeight: 28
                onClicked: root.exportRequested()
            }

            VrButton {
                visible: root.isCustom
                text: "Editar"
                variant: "ghost"
                implicitHeight: 28
                onClicked: root.editRequested()
            }

            VrButton {
                visible: root.isCustom
                text: "Excluir"
                variant: "danger"
                implicitHeight: 28
                onClicked: root.deleteRequested()
            }
        }
    }
}
