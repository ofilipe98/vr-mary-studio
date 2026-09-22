import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../components"
Popup {
    id: picker
    property string selectedFamily: ""
    property bool monospaceOnly: false
    readonly property var fullFontList: monospaceOnly ? frontend.monospaceFontFamilies : frontend.systemFontFamilies
    readonly property var filteredFonts: {
        var term=searchField.text.trim().toLowerCase()
        return fullFontList.filter(f => !term || f.toLowerCase().indexOf(term) !== -1)
    }
    signal familySelected(string familyName)
    function choose(index) {
        if(index>=0 && index<filteredFonts.length) {
            familySelected(filteredFonts[index]); close()
        }
    }
    function openAt(item) {
        var pos=item.mapToItem(parent,0,item.height)
        x=Math.max(8,Math.min(pos.x,parent.width-width-8))
        y=Math.max(8,Math.min(pos.y+4,parent.height-height-8))
        open()
    }
    parent: Overlay.overlay
    width: Math.min(320,parent ? parent.width-16 : 320)
    height: Math.min(380,parent ? parent.height-32 : 380)
    padding: Theme.scaledGeometry(8); modal: false; focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    onOpened: { searchField.text=""; fontList.currentIndex=Math.max(0,filteredFonts.indexOf(selectedFamily)); searchField.forceActiveFocus() }
    background: Rectangle { radius: Theme.scaledGeometry(10); color: Qt.alpha(Theme.palette.surface, Theme.glassOpacity); border.color: Theme.palette.border }
    contentItem: ColumnLayout {
        spacing: Theme.scaledGeometry(8)
        VrTextField {
            id: searchField; objectName: "fontSearchField"
            Layout.fillWidth: true; placeholderText: "Buscar fontes..."
            onTextChanged: fontList.currentIndex=0
            Keys.onDownPressed: fontList.currentIndex=Math.min(fontList.count-1,fontList.currentIndex+1)
            Keys.onUpPressed: fontList.currentIndex=Math.max(0,fontList.currentIndex-1)
            Keys.onReturnPressed: picker.choose(fontList.currentIndex)
        }
        ListView {
            id: fontList
            objectName: "fontPickerList"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; model: picker.filteredFonts
            ScrollBar.vertical: ScrollBar { }
            delegate: ItemDelegate {
                required property string modelData
                required property int index
                width: fontList.width; height: Theme.scaledGeometry(34)
                text: modelData
                highlighted: fontList.currentIndex===index
                background: Rectangle { radius: Theme.scaledGeometry(6); color: parent.highlighted || parent.hovered ? Theme.palette.hover : "transparent" }
                contentItem: Text {
                    text: parent.text; font.family: parent.text; font.pixelSize: Theme.fontSizeControl
                    color: picker.selectedFamily===parent.text ? Theme.palette.accessibleOrange : Theme.palette.text
                    elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                }
                onClicked: picker.choose(index)
            }
        }
        Text { visible: fontList.count===0; text: "Nenhuma fonte encontrada"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; Layout.alignment: Qt.AlignHCenter }
    }
}
