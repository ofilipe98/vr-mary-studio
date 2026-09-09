import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../components"

Popup {
    id: picker

    property string selectedFamily: ""
    property bool monospaceOnly: false
    property var fullFontList: monospaceOnly ? frontend.monospaceFontFamilies : frontend.systemFontFamilies
    property var filteredFonts: []

    signal familySelected(string familyName)

    function updateFilter() {
        var term = searchField.text.trim().toLowerCase()
        var src = picker.fullFontList
        if (!term) {
            filteredFonts = src.slice(0, 100)
            return
        }
        var res = []
        for (var i = 0; i < src.length; i++) {
            if (src[i].toLowerCase().indexOf(term) !== -1) {
                res.push(src[i])
                if (res.length >= 100) break
            }
        }
        filteredFonts = res
    }

    onOpened: {
        searchField.text = ""
        searchField.forceActiveFocus()
        updateFilter()
    }

    width: 320
    height: 380
    padding: 0
    modal: true
    focus: true
    dim: false
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: Theme.radiusControl
        color: Theme.palette.surface
        border.width: 1
        border.color: Theme.palette.border
    }

    contentItem: ColumnLayout {
        spacing: 0

        // Search header
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 48
            color: Theme.palette.surfaceRaised
            radius: Theme.radiusControl

            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: 6
                color: Theme.palette.surfaceRaised
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceSm
                anchors.rightMargin: Theme.spaceSm
                spacing: Theme.spaceSm

                VrTextField {
                    id: searchField
                    Layout.fillWidth: true
                    placeholderText: "Buscar família de fonte..."
                    onTextChanged: picker.updateFilter()
                }
            }
        }

        // List of fonts
        ListView {
            id: fontList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: picker.filteredFonts

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Rectangle {
                width: fontList.width
                height: 36
                color: itemArea.containsMouse ? Theme.palette.hover : (picker.selectedFamily === modelData ? Qt.alpha(Theme.palette.accessibleOrange, 0.15) : "transparent")

                MouseArea {
                    id: itemArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        picker.familySelected(modelData)
                        picker.close()
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceMd
                    spacing: Theme.spaceSm

                    Text {
                        text: modelData
                        font.family: modelData
                        font.pixelSize: Theme.fontSize(13)
                        color: picker.selectedFamily === modelData ? Theme.palette.accessibleOrange : Theme.palette.text
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    // Monospace indicator badge
                    Rectangle {
                        visible: frontend.isMonospaceFont(modelData)
                        implicitHeight: 18
                        implicitWidth: 36
                        radius: 4
                        color: Qt.alpha(Theme.palette.mutedText, 0.15)

                        Text {
                            anchors.centerIn: parent
                            text: "mono"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(9)
                            color: Theme.palette.mutedText
                        }
                    }
                }
            }
        }
    }
}
