import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../../theme"

Item {
    id: root
    property string title: ""
    property string description: ""
    property string resetKey: ""
    property bool resetVisible: false
    property bool divider: true
    property bool compact: width < 620 * Theme.textScale
    property int minimumHeight: divider ? 68 : 66
    default property alias controls: controlRow.data
    Layout.fillWidth: true
    implicitHeight: Math.max(minimumHeight, grid.implicitHeight + 24)
    GridLayout {
        id: grid
        anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 16; anchors.rightMargin: 16
        columns: root.compact ? 1 : 2; columnSpacing: 16; rowSpacing: 10
        ColumnLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0
            spacing: 4
            RowLayout {
                spacing: 4; Layout.fillWidth: true
                Text {
                    text: root.title; color: Theme.palette.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap; Layout.fillWidth: true; Layout.minimumWidth: 0
                }
                AppearanceAction {
                    objectName: root.resetKey + "Reset"
                    visible: root.resetVisible; quiet: true; iconKind: "reset"
                    implicitHeight: 18; Accessible.name: "Restaurar " + root.title.toLowerCase()
                    onClicked: frontend.resetAppearanceSetting(root.resetKey)
                }
            }
            Text {
                text: root.description; color: Theme.palette.mutedText
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
                wrapMode: Text.WordWrap; Layout.fillWidth: true
                lineHeight: Theme.bodyLineHeight
            }
        }
        RowLayout {
            id: controlRow
            Layout.alignment: root.compact ? Qt.AlignLeft : Qt.AlignRight
            Layout.fillWidth: false
            Layout.minimumWidth: 0
            Layout.preferredWidth: implicitWidth
            Layout.maximumWidth: Math.min(implicitWidth, grid.width)
            spacing: 8
        }
    }
    Rectangle {
        visible: root.divider; height: 1
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        color: Theme.palette.border
    }
}
