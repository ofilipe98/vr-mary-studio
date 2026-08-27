import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    function openPicker() { pickerPopup.open() }
    function matches(item) {
        if (!item) return false
        var query = searchField.text.trim().toLowerCase()
        if (!query.length) return true
        return String(item.displayName || item.label || "").toLowerCase().indexOf(query) >= 0
            || String(item.providerLabel || item.provider || "").toLowerCase().indexOf(query) >= 0
            || String(item.description || "").toLowerCase().indexOf(query) >= 0
    }
    function hasVisibleItems() {
        for (var index = 0; index < control.model.length; ++index)
            if (control.matches(control.model[index])) return true
        return false
    }

    property var model: []
    property int currentIndex: 0
    readonly property var currentItem: currentIndex >= 0 && currentIndex < model.length
        ? model[currentIndex] : ({})
    signal activated(int index)
    // Compatibility for the persisted backend preference. The streamlined
    // picker intentionally keeps one searchable model list.
    signal favoriteToggled(int index)

    implicitWidth: 158
    implicitHeight: Theme.compactControlHeight
    leftPadding: 7
    rightPadding: 7
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    onClicked: pickerPopup.open()

    contentItem: RowLayout {
        spacing: 7
        VrProviderIcon {
            Layout.preferredWidth: 17
            Layout.preferredHeight: 17
            provider: control.currentItem.provider || "codex"
        }
        Text {
            Layout.fillWidth: true
            text: control.currentItem.displayName || control.currentItem.label || "Modelo"
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: 13
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        VrLineIcon {
            Layout.preferredWidth: 13
            Layout.preferredHeight: 13
            kind: "chevronDown"
            foreground: frontend.palette.mutedText
        }
    }

    background: Rectangle {
        radius: 8
        color: control.down || control.hovered || pickerPopup.opened
            ? frontend.palette.chatControl : "transparent"
        border.width: control.activeFocus || pickerPopup.opened ? 1 : 0
        border.color: control.activeFocus ? frontend.palette.focus : frontend.palette.chatBorder
    }

    Popup {
        id: pickerPopup
        objectName: "modelPickerPopup"
        parent: control
        x: 0
        y: -height - 8
        width: 380
        height: 390
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: {
            searchField.clear()
            modelList.positionViewAtIndex(control.currentIndex, ListView.Center)
            searchField.forceActiveFocus()
        }

        background: Rectangle {
            color: frontend.palette.chatComposer
            border.width: 1
            border.color: frontend.palette.chatBorder
            radius: 14
        }

        contentItem: ColumnLayout {
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 50
                Layout.leftMargin: 12
                Layout.rightMargin: 10
                spacing: 8
                VrLineIcon {
                    Layout.preferredWidth: 17
                    Layout.preferredHeight: 17
                    kind: "search"
                    foreground: frontend.palette.mutedText
                }
                TextField {
                    id: searchField
                    objectName: "modelPickerSearch"
                    Layout.fillWidth: true
                    placeholderText: "Buscar modelo ou provedor..."
                    color: frontend.palette.text
                    placeholderTextColor: frontend.palette.mutedText
                    selectionColor: frontend.palette.selection
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    background: Item { }
                    onTextChanged: modelList.positionViewAtBeginning()
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: searchField.activeFocus
                    ? frontend.palette.brandOrange : frontend.palette.chatBorder
            }

            ListView {
                id: modelList
                objectName: "modelPickerList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 8
                clip: true
                spacing: 2
                model: control.model
                ScrollIndicator.vertical: ScrollIndicator { }

                delegate: Rectangle {
                    id: modelRow
                    required property int index
                    required property var modelData
                    readonly property bool matchesFilter: control.matches(modelData)
                    width: modelList.width
                    height: matchesFilter ? 56 : 0
                    visible: matchesFilter
                    radius: 9
                    color: control.currentIndex === index
                        ? frontend.palette.selection
                        : modelHover.hovered ? frontend.palette.chatControl : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        spacing: 9
                        VrProviderIcon {
                            Layout.preferredWidth: 23
                            Layout.preferredHeight: 23
                            provider: modelData.provider || "codex"
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                Layout.fillWidth: true
                                text: modelData.displayName || modelData.label
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.providerLabel || modelData.provider || ""
                                color: frontend.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }
                        }
                        Text {
                            visible: control.currentIndex === modelRow.index
                            text: "✓"
                            color: frontend.palette.brandOrange
                            font.family: Theme.fontFamily
                            font.pixelSize: 14
                            font.weight: Font.Bold
                        }
                    }
                    HoverHandler { id: modelHover }
                    TapHandler {
                        onTapped: {
                            control.activated(modelRow.index)
                            pickerPopup.close()
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: !control.hasVisibleItems()
                    text: "Nenhum modelo encontrado"
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
            }
        }
    }
}
