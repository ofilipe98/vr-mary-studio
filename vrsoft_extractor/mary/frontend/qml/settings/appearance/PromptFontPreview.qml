import QtQuick
import QtQuick.Layouts
import "../../theme"

Rectangle {
    id: root
    Layout.fillWidth: true
    implicitHeight: Math.max(66, flow.implicitHeight + 20)
    radius: 10
    color: Theme.palette.background
    border.color: Theme.palette.controlBorder || Theme.palette.border
    Flow {
        id: flow
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 12
        Repeater {
            model: [
                {text:"Use"}, {text:"Design de interface",icon:"◇",kind:"skill"},
                {text:"para"}, {text:"corrigir"}, {text:"o"}, {text:"teste"}, {text:"instável"}, {text:"em"},
                {text:"surface.test.ts",icon:"TS",kind:"file"},
                {text:"e"}, {text:"alinhar"}, {text:"o"}, {text:"cabeçalho"}, {text:"com"},
                {text:"SettingsPanels.tsx",icon:"⚛",kind:"file"}, {text:"antes de"}, {text:"publicar."}
            ]
            Item {
                id: token
                required property var modelData
                readonly property bool badge: modelData.kind !== undefined
                width: badge ? chip.width + 4 : word.implicitWidth + 4
                height: Math.max(24, word.implicitHeight + 4)
                Text {
                    id: word
                    objectName: "promptFontPreview"
                    visible: !token.badge
                    anchors.verticalCenter: parent.verticalCenter
                    text: token.modelData.text; color: Theme.palette.text
                    font.family: frontend.promptFontFamily; font.pixelSize: Theme.promptFontSize(14)
                }
                Rectangle {
                    id: chip
                    visible: token.badge
                    anchors.verticalCenter: parent.verticalCenter
                    width: chipLabel.implicitWidth + 12
                    height: chipLabel.implicitHeight + 2
                    radius: 5
                    color: token.modelData.kind === "skill" ? (frontend.resolvedAppearance === "dark" ? "#352341" : "#f3e8fa") : Theme.palette.mutedSurface || Theme.palette.surfaceRaised
                    border.color: token.modelData.kind === "skill" ? "#75408d" : Theme.palette.border
                    Text {
                        id: chipLabel
                        anchors.centerIn: parent
                        text: (token.modelData.icon || "") + " " + token.modelData.text
                        font.family: frontend.promptFontFamily
                        font.pixelSize: Math.max(10, Math.round(Theme.promptFontSize(14) * .8))
                        font.weight: Font.DemiBold
                        color: token.modelData.kind === "skill" ? (frontend.resolvedAppearance === "dark" ? "#e6a0ef" : "#7c318b") : Theme.palette.text
                    }
                }
            }
        }
    }
}
