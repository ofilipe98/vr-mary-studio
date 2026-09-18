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
    property string providerFilter: "favorites"
    property bool showingLegacy: false
    property bool loading: false
    readonly property var frontierItems: filteredItems(false)
    readonly property var legacyItems: filteredItems(true)
    readonly property var visibleItems: showingLegacy ? legacyItems : frontierItems
    property bool popupAbove: true
    property bool outlined: false
    readonly property var currentItem: currentIndex >= 0 && currentIndex < model.length
        ? model[currentIndex] : ({})
    signal activated(int index)
    signal favoriteToggled(int index)

    property bool compact: false
    implicitWidth: compact
        ? (pickerContentRow.implicitWidth + leftPadding + rightPadding)
        : Math.max(158, pickerContentRow.implicitWidth + leftPadding + rightPadding)
    implicitHeight: compact ? 26 : Theme.compactControlHeight
    leftPadding: compact ? 6 : 7
    rightPadding: compact ? 6 : 7
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && control.down ? 0.97 : 1
    onClicked: pickerPopup.opened ? pickerPopup.close() : pickerPopup.open()

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    contentItem: RowLayout {
        id: pickerContentRow
        spacing: control.compact ? 5 : 7
        VrProviderIcon {
            Layout.preferredWidth: control.compact ? 14 : 17
            Layout.preferredHeight: control.compact ? 14 : 17
            provider: control.currentItem.provider || "codex"
        }
        Text {
            Layout.fillWidth: !control.compact
            text: control.currentItem.displayName || control.currentItem.label || "Modelo"
            color: control.compact
                ? (control.hovered || pickerPopup.opened ? Theme.palette.text : Theme.palette.mutedText)
                : (control.hovered || pickerPopup.opened ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8"))
            font.family: Theme.fontFamily
            font.pixelSize: control.compact ? Theme.fontSize(11.5) : Theme.fontSize(12.5)
            renderType: Theme.textRenderType
            elide: control.compact ? Text.ElideNone : Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        VrLineIcon {
            Layout.preferredWidth: control.compact ? 10 : 11
            Layout.preferredHeight: control.compact ? 10 : 11
            kind: "chevronDown"
            foreground: control.hovered || pickerPopup.opened ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8")
        }
    }

    background: Rectangle {
        radius: control.compact ? 6 : 6
        color: control.down || control.hovered || pickerPopup.opened
            ? Qt.rgba(255, 255, 255, 0.07) : (control.outlined ? Theme.palette.chatControl : "transparent")
        border.width: control.outlined || control.activeFocus || pickerPopup.opened ? 1 : 0
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Popup {
        id: pickerPopup
        objectName: "modelPickerPopup"
        parent: control
        x: 0
        y: control.popupAbove ? -height - 8 : control.height + 8
        width: Math.min(420, Theme.viewportWidth - 24)
        height: 400
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        onOpened: {
            searchField.clear()
            control.providerFilter = "favorites"
            control.showingLegacy = false
            modelList.positionViewAtBeginning()
            searchField.forceActiveFocus()
        }

        background: Rectangle {
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: 12
        }

        contentItem: RowLayout {
            spacing: 0

            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: 48
                color: Theme.palette.chatSidebar
                radius: 14
                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 1
                    color: Theme.palette.chatBorder
                }
                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    spacing: 4
                    Repeater {
                        model: control.providerTabs()
                        delegate: Button {
                            id: providerTabButton
                            required property var modelData
                            width: 48
                            height: 42
                            padding: 0
                            hoverEnabled: true
                            Accessible.name: modelData.label
                            onClicked: {
                                control.providerFilter = modelData.key
                                control.showingLegacy = false
                                modelList.positionViewAtBeginning()
                            }
                            contentItem: Item {
                                VrProviderIcon {
                                    visible: modelData.key === "codex" || modelData.key === "claude" || modelData.key === "opencode" || modelData.key === "antigravity"
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
                                        ? Theme.palette.brandOrange : Theme.palette.text
                                }
                            }
                            background: Rectangle {
                                color: control.providerFilter === modelData.key
                                    ? Theme.palette.selection : providerTabButton.hovered
                                        ? Theme.palette.chatControl : "transparent"
                                Rectangle {
                                    visible: control.providerFilter === modelData.key
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 3
                                    height: 26
                                    radius: 2
                                    color: Theme.palette.brandOrange
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
                            foreground: Theme.palette.mutedText
                        }
                        TextField {
                            id: searchField
                            objectName: "modelPickerSearch"
                            Layout.fillWidth: true
                            placeholderText: "Pesquisar modelos..."
                            color: Theme.palette.text
                            placeholderTextColor: Theme.palette.mutedText
                            selectionColor: Theme.palette.selection
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
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
                        color: searchField.activeFocus ? Theme.palette.brandOrange : Theme.palette.chatBorder
                    }
                }

                Button {
                    objectName: "modelPickerBack"
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    Layout.rightMargin: 8
                    Layout.preferredHeight: 36
                    visible: control.showingLegacy
                    text: "‹  Modelos legado"
                    Accessible.name: "Voltar aos modelos de fronteira"
                    onClicked: {
                        control.showingLegacy = false
                        modelList.positionViewAtBeginning()
                    }
                    contentItem: Text {
                        text: parent.text
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        radius: 8
                        color: parent.hovered ? Theme.palette.chatControl : "transparent"
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
                    model: control.visibleItems
                    ScrollIndicator.vertical: ScrollIndicator { }

                    footer: Button {
                        objectName: "modelPickerLegacy"
                        width: modelList.width
                        height: visible ? 58 : 0
                        visible: !control.showingLegacy && control.legacyItems.length > 0
                        padding: 10
                        Accessible.name: "Modelos legado, " + control.legacyItems.length + " modelos"
                        onClicked: {
                            control.showingLegacy = true
                            modelList.positionViewAtBeginning()
                        }
                        contentItem: RowLayout {
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text {
                                    text: "Modelos legado"
                                    color: Theme.palette.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(13)
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: control.legacyItems.length + (control.legacyItems.length === 1 ? " modelo" : " modelos")
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeCaption
                                }
                            }
                            VrLineIcon {
                                Layout.preferredWidth: 16
                                Layout.preferredHeight: 16
                                kind: "chevronRight"
                            }
                        }
                        background: Rectangle {
                            radius: 10
                            color: parent.hovered ? Theme.palette.chatControl : "transparent"
                        }
                    }

                    delegate: Rectangle {
                        id: modelRow
                        objectName: "modelPickerRow"
                        required property int index
                        required property var modelData
                        readonly property int sourceIndex: modelData.sourceIndex
                        width: modelList.width
                        height: 56
                        radius: 10
                        color: control.currentIndex === sourceIndex
                            ? Qt.rgba(1.0, 0.45, 0.0, 0.14)
                            : modelHover.hovered ? Theme.palette.chatControl : "transparent"
                        Rectangle {
                            visible: control.currentIndex === modelRow.sourceIndex
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: 34
                            radius: 2
                            color: Theme.palette.brandOrange
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
                                    color: Theme.palette.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(13)
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.providerLabel || modelData.provider || ""
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeCaption
                                    elide: Text.ElideRight
                                }
                            }
                            Rectangle {
                                visible: modelRow.sourceIndex < 4
                                Layout.preferredWidth: 42
                                Layout.preferredHeight: 22
                                radius: 6
                                color: Theme.palette.chatControl
                                Text {
                                    anchors.centerIn: parent
                                    text: "Ctrl+" + (modelRow.sourceIndex + 1)
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                }
                            }
                            VrIconButton {
                                implicitWidth: 30
                                implicitHeight: 30
                                symbol: modelData.favorite ? "★" : "☆"
                                foreground: modelData.favorite
                                    ? Theme.palette.brandOrange : Theme.palette.mutedText
                                Accessible.name: modelData.favorite
                                    ? "Remover dos favoritos" : "Adicionar aos favoritos"
                                onClicked: control.favoriteToggled(modelRow.sourceIndex)
                            }
                        }
                        HoverHandler { id: modelHover }
                        TapHandler {
                            onTapped: {
                                control.activated(modelRow.sourceIndex)
                                pickerPopup.close()
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: !control.visibleItems.length
                            && (control.showingLegacy || !control.legacyItems.length)
                        text: control.loading && control.providerFilter !== "favorites"
                            ? "Carregando modelos..."
                            : control.providerFilter === "favorites"
                                ? "Nenhum modelo favorito" : "Nenhum modelo encontrado"
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                    }
                }
            }
        }
    }

    function matches(item) {
        if (!item) return false
        if (item.inactive === true) return false
        if (control.providerFilter === "favorites" && !item.favorite) return false
        if (control.providerFilter !== "favorites"
                && item.provider !== control.providerFilter) return false
        var query = searchField.text.trim().toLowerCase()
        if (!query.length) return true
        return String(item.label || "").toLowerCase().indexOf(query) >= 0
            || String(item.displayName || "").toLowerCase().indexOf(query) >= 0
            || String(item.description || "").toLowerCase().indexOf(query) >= 0
            || String(item.providerLabel || "").toLowerCase().indexOf(query) >= 0
    }

    function isLegacy(item) {
        // Reference models shown in the product's model picker. Keep the full
        // catalog available in the legacy view, including saved favorites.
        var name = String(item.value || item.displayName || item.label || "")
            .toLowerCase().replace(/[^a-z0-9]/g, "")
        if (item.provider === "codex")
            return ["gpt6astra", "gpt56sol", "gpt56terra", "gpt56luna"].indexOf(name) < 0
        if (item.provider === "antigravity") {
            var display = String(item.displayName || "").toLowerCase().replace(/[^a-z0-9]/g, "")
            return !/^gemini38flash(high|medium|low)?$/.test(name)
                && !/^gemini38flash(high|medium|low)?$/.test(display)
        }
        return item.isLegacy === true || item.isFrontier === false
    }

    function filteredItems(legacy) {
        var result = []
        for (var i = 0; i < control.model.length; ++i) {
            var item = control.model[i]
            if (!control.matches(item) || control.isLegacy(item) !== legacy) continue
            var row = Object.assign({}, item)
            row.sourceIndex = i
            result.push(row)
        }
        return result
    }

    function providerTabs() {
        var result = [{key: "favorites", kind: "star", label: "Favoritos"}]
        var seen = ({})
        for (var index = 0; index < control.model.length; ++index) {
            var item = control.model[index] || ({})
            var provider = String(item.provider || "")
            if (!provider.length || item.inactive === true || seen[provider]) continue
            seen[provider] = true
            result.push({
                key: provider,
                kind: "",
                label: item.providerLabel || provider
            })
        }
        return result
    }
}
