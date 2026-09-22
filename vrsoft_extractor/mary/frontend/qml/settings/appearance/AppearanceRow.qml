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
        anchors.leftMargin: Theme.scaledGeometry(16); anchors.rightMargin: Theme.scaledGeometry(16)
        columns: root.compact ? 1 : 2; columnSpacing: Theme.scaledGeometry(16); rowSpacing: Theme.scaledGeometry(10)
        ColumnLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0
            spacing: Theme.scaledGeometry(4)
            RowLayout {
                spacing: Theme.scaledGeometry(4); Layout.fillWidth: true
                Text {
                    text: root.title; color: Theme.palette.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl; font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap; Layout.fillWidth: true; Layout.minimumWidth: 0
                }
                AppearanceAction {
                    objectName: root.resetKey + "Reset"
                    visible: root.resetVisible; quiet: true; iconKind: "reset"
                    implicitHeight: Theme.scaledGeometry(18); Accessible.name: "Restaurar " + root.title.toLowerCase()
                    onClicked: frontend.resetAppearanceSetting(root.resetKey)
                }
            }
            Text {
                text: root.description; color: Theme.palette.mutedText
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl
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
            spacing: Theme.scaledGeometry(8)
        }
    }
    Rectangle {
        visible: root.divider; height: 1
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        color: Theme.palette.border
    }
}
