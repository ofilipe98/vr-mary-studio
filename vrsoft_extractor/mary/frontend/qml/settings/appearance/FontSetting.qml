import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
Item {
    id: root
    property string title: ""
    property string description: ""
    property string settingKey: ""
    property string family: ""
    property int size: 14
    property int minSize: 10
    property int maxSize: 22
    property bool monospaceOnly: false
    property bool changed: false
    default property alias previews: previewColumn.data
    signal typographySelected(string family, int size)
    Layout.fillWidth: true
    implicitHeight: header.implicitHeight + previewColumn.implicitHeight + (previewColumn.implicitHeight > 0 ? 12 : 0)
    AppearanceRow {
        id: header
        anchors.left: parent.left; anchors.right: parent.right
        height: implicitHeight
        minimumHeight: 58
        title: root.title; description: root.description
        resetKey: root.settingKey; resetVisible: root.changed; divider: false
        AppearanceCombo {
            id: familyButton
            objectName: root.settingKey + "Family"
            Layout.preferredWidth: Math.min(176, (root.width - 42) * .55); Layout.minimumWidth: 80
            model: [root.family]; currentIndex: 0
            Accessible.name: root.title
            onPressedChanged: if(pressed) { popup.close(); picker.openAt(familyButton) }
            onDownChanged: if(down) popup.close()
            Keys.onSpacePressed: picker.openAt(familyButton)
            Keys.onReturnPressed: picker.openAt(familyButton)
        }
        AppearanceCombo {
            objectName: root.settingKey + "Size"
            Layout.preferredWidth: Math.min(144, (root.width - 42) * .45); Layout.minimumWidth: 70
            model: {
                var values=[]
                for(var i=root.minSize;i<=root.maxSize;i++) values.push(i+" px")
                return values
            }
            currentIndex: root.size-root.minSize
            Accessible.name: root.title + " — tamanho"
            onActivated: index => root.typographySelected(root.family,index+root.minSize)
        }
    }
    ColumnLayout {
        id: previewColumn
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: header.bottom
        anchors.leftMargin: 16; anchors.rightMargin: 16
        spacing: 8
    }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.palette.border }
    FontFamilyPicker {
        id: picker
        selectedFamily: root.family; monospaceOnly: root.monospaceOnly
        onFamilySelected: family => root.typographySelected(family,root.size)
    }
}
