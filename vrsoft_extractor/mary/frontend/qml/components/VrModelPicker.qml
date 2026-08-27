import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    function openPicker() {
        pickerPopup.open()
    }

    property var model: []
    property int currentIndex: 0
    property string providerFilter: "all"
    property bool popupAbove: true
    readonly property var currentItem: currentIndex >= 0 && currentIndex < model.length
        ? model[currentIndex] : ({})
    signal activated(int index)
    signal favoriteToggled(int index)

    implicitWidth: 158
    implicitHeight: Theme.compactControlHeight
    leftPadding: 7
    rightPadding: 7
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    onClicked: pickerPopup.opened ? pickerPopup.close() : pickerPopup.open()

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
        y: control.popupAbove ? -height - 8 : control.height + 8
        width: 420
        height: 400
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        onOpened: {
            searchField.clear()
            control.providerFilter = "all"
            modelList.positionViewAtIndex(control.currentIndex, ListView.Center)
            searchField.forceActiveFocus()
        }

        background: Rectangle {
            color: frontend.palette.chatComposer
            border.width: 1
            border.color: frontend.palette.chatBorder
            radius: 12
        }

        contentItem: RowLayout {
            spacing: 0

            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: 48
                color: frontend.palette.chatSidebar
                radius: 14
                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 1
                    color: frontend.palette.chatBorder
                }
                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    spacing: 4
                    Repeater {
                        model: [
                            {key: "favorites", kind: "star", label: "Favoritos"},
                            {key: "all", kind: "models", label: "Todos"},
                            {key: "codex", kind: "", label: "Codex"},
                            {key: "claude", kind: "", label: "Claude"},
                            {key: "opencode", kind: "", label: "OpenCode"}
                        ]
                        delegate: Button {
                            required property var modelData
                            width: 48
                            height: 42
                            padding: 0
                            hoverEnabled: true
                            Accessible.name: modelData.label
                            onClicked: {
                                control.providerFilter = modelData.key
                                modelList.positionViewAtBeginning()
                            }
                            contentItem: Item {
                                VrProviderIcon {
                                    visible: modelData.key === "codex" || modelData.key === "claude" || modelData.key === "opencode"
                                    anchors.centerIn: parent
                                    width: 19
                                    height: 19
                                    provider: modelData.key
                                }
                                VrLineIcon {
                                    visible: modelData.kind.length > 0
                                    anchors.centerIn: parent
                                    width: 18
                                    height: 18
                                    kind: modelData.kind
                                    foreground: modelData.key === "favorites" && control.providerFilter === "favorites"
                                        ? frontend.palette.brandOrange : frontend.palette.text
                                }
                            }
                            background: Rectangle {
                                color: control.providerFilter === modelData.key
                                    ? frontend.palette.selection : parent.hovered
                                        ? frontend.palette.chatControl : "transparent"
                                Rectangle {
                                    visible: control.providerFilter === modelData.key
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 3
                                    height: 26
                                    radius: 2
                                    color: frontend.palette.brandOrange
                                }
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 52
                    color: "transparent"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 10
                        spacing: 7
                        VrLineIcon {
                            Layout.preferredWidth: 18
                            Layout.preferredHeight: 18
                            kind: "search"
                            foreground: frontend.palette.mutedText
                        }
                        TextField {
                            id: searchField
                            objectName: "modelPickerSearch"
                            Layout.fillWidth: true
                            placeholderText: "Pesquisar modelos..."
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
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 12
                        anchors.rightMargin: 10
                        height: 1
                        color: searchField.activeFocus ? frontend.palette.brandOrange : frontend.palette.chatBorder
                    }
                }

                ListView {
                    id: modelList
                    objectName: "modelPickerList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.margins: 8
                    clip: true
                    spacing: 3
                    model: control.model
                    ScrollIndicator.vertical: ScrollIndicator { }

                    delegate: Rectangle {
                        id: modelRow
                        required property int index
                        required property var modelData
                        readonly property bool matches: control.matches(modelData)
                        width: modelList.width
                        height: matches ? 56 : 0
                        visible: matches
                        radius: 10
                        color: control.currentIndex === index
                            ? Qt.rgba(1.0, 0.45, 0.0, 0.14)
                            : modelHover.hovered ? frontend.palette.chatControl : "transparent"
                        Rectangle {
                            visible: control.currentIndex === modelRow.index
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: 34
                            radius: 2
                            color: frontend.palette.brandOrange
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 7
                            spacing: 9
                            VrProviderIcon {
                                Layout.preferredWidth: 22
                                Layout.preferredHeight: 22
                                provider: modelData.provider || "codex"
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
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
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                            }
                            Rectangle {
                                visible: modelRow.index < 4
                                Layout.preferredWidth: 42
                                Layout.preferredHeight: 22
                                radius: 6
                                color: frontend.palette.chatControl
                                Text {
                                    anchors.centerIn: parent
                                    text: "Ctrl+" + (modelRow.index + 1)
                                    color: frontend.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 9
                                }
                            }
                            VrIconButton {
                                implicitWidth: 30
                                implicitHeight: 30
                                symbol: modelData.favorite ? "★" : "☆"
                                foreground: modelData.favorite
                                    ? frontend.palette.brandOrange : frontend.palette.mutedText
                                Accessible.name: modelData.favorite
                                    ? "Remover dos favoritos" : "Adicionar aos favoritos"
                                onClicked: control.favoriteToggled(modelRow.index)
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
                        text: control.providerFilter === "favorites"
                            ? "Nenhum modelo favorito" : "Nenhum modelo encontrado"
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
            }
        }
    }

    function matches(item) {
        if (!item) return false
        if (control.providerFilter === "favorites" && !item.favorite) return false
        if (control.providerFilter !== "all" && control.providerFilter !== "favorites"
                && item.provider !== control.providerFilter) return false
        var query = searchField.text.trim().toLowerCase()
        if (!query.length) return true
        return String(item.label || "").toLowerCase().indexOf(query) >= 0
            || String(item.description || "").toLowerCase().indexOf(query) >= 0
            || String(item.providerLabel || "").toLowerCase().indexOf(query) >= 0
    }

    function hasVisibleItems() {
        for (var i = 0; i < control.model.length; ++i)
            if (control.matches(control.model[i])) return true
        return false
    }
}
