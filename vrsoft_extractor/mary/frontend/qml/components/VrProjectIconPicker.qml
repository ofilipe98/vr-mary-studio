pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Popup {
    id: root

    objectName: "iconPickerPopup"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(520, parent.width - 48)
    height: Math.min(600, parent.height - 70)
    padding: 0
    modal: true
    dim: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    property string projectLabel: ""
    property string pickerTab: "icons"
    property string selKind: "layers"
    property string selColor: "#D946EF"
    property string selEmoji: ""
    property string selText: ""
    property string searchText: ""

    signal saved(string kind, string color, string emoji, string text)

    readonly property var iconCatalog: [
        { kind: "folder", label: "Folder" }, { kind: "folderPlus", label: "Folder Plus" },
        { kind: "files", label: "Files" }, { kind: "file", label: "File" },
        { kind: "browser", label: "Browser" }, { kind: "globe", label: "Globe" },
        { kind: "terminal", label: "Terminal" }, { kind: "code", label: "Code" },
        { kind: "database", label: "Database" }, { kind: "layers", label: "Layers" },
        { kind: "cube", label: "Cube" }, { kind: "models", label: "Models" },
        { kind: "image", label: "Image" }, { kind: "context", label: "Book" },
        { kind: "agents", label: "Bot" }, { kind: "task", label: "Task" },
        { kind: "listTodo", label: "Todo" }, { kind: "branch", label: "Branch" },
        { kind: "star", label: "Star" }, { kind: "eye", label: "Eye" },
        { kind: "lock", label: "Lock" }, { kind: "archive", label: "Archive" },
        { kind: "gauge", label: "Gauge" }, { kind: "trendUp", label: "Trending Up" },
        { kind: "auto", label: "Sparkles" }, { kind: "paintbrush", label: "Paintbrush" },
        { kind: "react", label: "Atom" }, { kind: "attachment", label: "Paperclip" },
        { kind: "search", label: "Search" }, { kind: "settings", label: "Settings" },
        { kind: "pin", label: "Pin" }, { kind: "newChat", label: "Chat" }
    ]

    readonly property var emojiCatalog: [
        "🚀", "✨", "🔥", "💡", "🎯", "📦", "🗂️", "📁",
        "💻", "🖥️", "⌨️", "🖱️", "🌐", "🧠", "🤖", "👾",
        "🎨", "🖌️", "📊", "📈", "🧪", "🔬", "⚙️", "🛠️",
        "🔧", "🔨", "🧰", "📚", "📖", "✏️", "📌", "🗓️",
        "✅", "☑️", "⭐", "🌟", "💜", "🧡", "💙", "💚",
        "❤️", "🎮", "🎧", "🎵", "🛒", "🏦", "🏥", "🚗"
    ]

    function normalized(value) {
        var text = String(value || "").toLowerCase().trim()
        if (text.normalize) text = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
        return text
    }

    readonly property var filteredIcons: {
        var needle = normalized(root.searchText)
        if (!needle.length) return root.iconCatalog
        var result = []
        for (var i = 0; i < root.iconCatalog.length; ++i) {
            var item = root.iconCatalog[i]
            if (normalized(item.label).indexOf(needle) >= 0
                || normalized(item.kind).indexOf(needle) >= 0) result.push(item)
        }
        return result
    }

    function openFor(kind, color, emoji, text) {
        root.selKind = String(kind || "").length ? String(kind) : "layers"
        root.selColor = String(color || "").length ? String(color) : "#D946EF"
        root.selEmoji = String(emoji || "")
        root.selText = String(text || "").trim().toUpperCase()
        root.searchText = ""
        iconSearch.clear()
        monogramField.text = root.selText
        if (String(emoji || "").length) root.pickerTab = "emoji"
        else if (root.selText.length && !String(kind || "").length) root.pickerTab = "monogram"
        else root.pickerTab = "icons"
        root.open()
    }

    function saveCurrent() {
        var kind = "", color = root.selColor, emoji = "", text = ""
        if (root.pickerTab === "icons") {
            kind = root.selKind.length ? root.selKind : "layers"
        } else if (root.pickerTab === "emoji") {
            emoji = root.selEmoji.length ? root.selEmoji : "🚀"
        } else {
            text = root.selText.trim().toUpperCase()
        }
        root.saved(kind, color, emoji, text)
        root.close()
    }

    onOpened: {
        if (root.pickerTab === "icons") Qt.callLater(function() { iconSearch.forceActiveFocus() })
    }

    contentItem: ColumnLayout {
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(18)
            Layout.rightMargin: Theme.scaledGeometry(12)
            Layout.topMargin: Theme.scaledGeometry(14)
            Layout.bottomMargin: 2
            spacing: Theme.scaledGeometry(8)
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 2
                Text {
                    text: "Choose project icon"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeBody
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "Choose an icon, emoji, or monogram."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                }
            }
            VrIconButton {
                Layout.alignment: Qt.AlignTop
                iconKind: "close"
                iconSize: Theme.iconMicro
                implicitWidth: Theme.scaledGeometry(28)
                implicitHeight: Theme.scaledGeometry(28)
                foreground: Theme.palette.mutedText
                Accessible.name: "Fechar"
                onClicked: root.close()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(18)
            Layout.topMargin: Theme.scaledGeometry(12)
            Layout.preferredWidth: tabPills.implicitWidth
            Layout.maximumWidth: Theme.scaledGeometry(320)
            Layout.preferredHeight: Theme.scaledGeometry(32)
            radius: Theme.scaledGeometry(8)
            color: Theme.palette.chatControl
            RowLayout {
                id: tabPills
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(3)
                spacing: 2
                Repeater {
                    model: [
                        { key: "icons", label: "Icons" },
                        { key: "emoji", label: "Emoji" },
                        { key: "monogram", label: "Monogram" }
                    ]
                    delegate: Rectangle {
                        id: tabPill
                        required property var modelData
                        readonly property bool selected: root.pickerTab === modelData.key
                        objectName: "iconPickerTab" + modelData.key.charAt(0).toUpperCase() + modelData.key.slice(1)
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: Theme.scaledGeometry(6)
                        color: tabPill.selected ? Theme.palette.chatComposer
                            : (tabHover.hovered ? Qt.rgba(255, 255, 255, 0.05) : "transparent")
                        border.width: tabPill.selected ? 1 : 0
                        border.color: Theme.palette.chatBorder
                        Text {
                            anchors.centerIn: parent
                            text: tabPill.modelData.label
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeCaption
                            font.weight: tabPill.selected ? Font.DemiBold : Font.Medium
                        }
                        HoverHandler { id: tabHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: root.pickerTab = tabPill.modelData.key }
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(18)
            Layout.rightMargin: Theme.scaledGeometry(18)
            Layout.topMargin: Theme.scaledGeometry(12)
            Layout.bottomMargin: Theme.scaledGeometry(6)
            text: "Color"
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeCaption
            font.weight: Font.Medium
        }

        GridLayout {
            id: colorGrid
            objectName: "iconPickerColors"
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(18)
            Layout.rightMargin: Theme.scaledGeometry(18)
            columns: 9
            columnSpacing: Theme.scaledGeometry(8)
            rowSpacing: Theme.scaledGeometry(8)
            Repeater {
                model: [
                    "#6B7280", "#EF4444", "#F97316", "#F59E0B", "#EAB308",
                    "#84CC16", "#22C55E", "#10B981", "#14B8A6", "#06B6D4",
                    "#0EA5E9", "#3B82F6", "#6366F1", "#8B5CF6", "#A855F7",
                    "#D946EF", "#EC4899", "#F43F5E"
                ]
                delegate: Rectangle {
                    id: colorDot
                    required property var modelData
                    readonly property string dotColor: String(modelData)
                    readonly property bool selected: root.selColor.toLowerCase() === dotColor.toLowerCase()
                    Layout.preferredWidth: Theme.scaledGeometry(24)
                    Layout.preferredHeight: Theme.scaledGeometry(24)
                    radius: Theme.scaledGeometry(12)
                    color: dotColor
                    border.width: colorDot.selected ? 2 : 0
                    border.color: "#FFFFFF"
                    HoverHandler { id: dotHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: root.selColor = colorDot.dotColor }
                    Accessible.name: dotColor
                    Rectangle {
                        visible: colorDot.selected
                        anchors.fill: parent
                        anchors.margins: -4
                        radius: Theme.scaledGeometry(16)
                        color: "transparent"
                        border.width: 1
                        border.color: Qt.alpha("#FFFFFF", 0.45)
                    }
                }
            }
        }

        VrTextField {
            id: iconSearch
            objectName: "iconPickerSearch"
            visible: root.pickerTab === "icons"
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(18)
            Layout.rightMargin: Theme.scaledGeometry(18)
            Layout.topMargin: visible ? 12 : 0
            Layout.preferredHeight: visible ? 36 : 0
            leftPadding: Theme.scaledGeometry(30)
            placeholderText: "Search all Lucide icons"
            text: root.searchText
            font.pixelSize: Theme.fontSizeCaption
            onTextChanged: if (root.searchText !== text) root.searchText = text
            Keys.onReturnPressed: {
                if (root.filteredIcons.length) {
                    root.selKind = root.filteredIcons[0].kind
                    iconGrid.positionViewAtBeginning()
                }
            }
            VrLineIcon {
                anchors.left: parent.left
                anchors.leftMargin: Theme.iconMicro
                anchors.verticalCenter: parent.verticalCenter
                width: Theme.iconCompact
                height: Theme.iconCompact
                kind: "search"
                foreground: Theme.palette.mutedText
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: Theme.scaledGeometry(12)
            Layout.rightMargin: Theme.scaledGeometry(12)
            Layout.topMargin: Theme.scaledGeometry(10)
            Layout.bottomMargin: Theme.scaledGeometry(6)
            currentIndex: root.pickerTab === "emoji" ? 1 : (root.pickerTab === "monogram" ? 2 : 0)

            GridView {
                id: iconGrid
                objectName: "iconPickerGrid"
                clip: true
                cellWidth: 56
                cellHeight: 56
                model: root.pickerTab === "icons" ? root.filteredIcons : []
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    id: iconCell
                    required property var modelData
                    readonly property bool selected: root.selKind === modelData.kind
                    width: Theme.scaledGeometry(48)
                    height: Theme.scaledGeometry(48)
                    radius: Theme.scaledGeometry(9)
                    color: iconCell.selected ? Qt.alpha(root.selColor, 0.20)
                        : (cellHover.hovered ? Theme.palette.chatControl : "transparent")
                    border.width: iconCell.selected ? 1 : 0
                    border.color: root.selColor
                    VrLineIcon {
                        anchors.centerIn: parent
                        width: Theme.scaledGeometry(24)
                        height: Theme.scaledGeometry(24)
                        kind: iconCell.modelData.kind
                        foreground: iconCell.selected ? root.selColor : Theme.palette.mutedText
                    }
                    Accessible.name: iconCell.modelData.label
                    HoverHandler { id: cellHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: root.selKind = iconCell.modelData.kind }
                }
                Text {
                    anchors.centerIn: parent
                    visible: root.pickerTab === "icons" && iconGrid.count === 0
                    text: "No icons found"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                }
            }

            GridView {
                id: emojiGrid
                objectName: "iconPickerEmojiGrid"
                clip: true
                cellWidth: 48
                cellHeight: 48
                model: root.pickerTab === "emoji" ? root.emojiCatalog : []
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    id: emojiCell
                    required property var modelData
                    readonly property string glyph: String(modelData)
                    readonly property bool selected: root.selEmoji === glyph
                    width: Theme.scaledGeometry(42)
                    height: Theme.scaledGeometry(42)
                    radius: Theme.scaledGeometry(9)
                    color: emojiCell.selected ? Theme.palette.chatControl : "transparent"
                    border.width: emojiCell.selected ? 1 : 0
                    border.color: Theme.palette.focus
                    Text {
                        anchors.centerIn: parent
                        text: emojiCell.glyph
                        font.pixelSize: 23
                    }
                    HoverHandler { id: emojiHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: root.selEmoji = emojiCell.glyph }
                }
            }

            ColumnLayout {
                spacing: Theme.scaledGeometry(12)
                Item { Layout.fillWidth: true; Layout.preferredHeight: Theme.scaledGeometry(6) }
                VrProjectIcon {
                    Layout.alignment: Qt.AlignHCenter
                    boxSize: 64
                    iconSize: 34
                    projectLabel: root.projectLabel
                    iconKind: ""
                    iconEmoji: ""
                    iconColor: root.selColor
                    iconText: root.selText
                }
                VrTextField {
                    id: monogramField
                    objectName: "iconPickerMonogramField"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: Theme.scaledGeometry(120)
                    Layout.preferredHeight: Theme.scaledGeometry(40)
                    text: root.selText
                    placeholderText: "AB"
                    horizontalAlignment: Text.AlignHCenter
                    maximumLength: 2
                    font.pixelSize: Theme.fontSizeBody
                    font.weight: Font.DemiBold
                    onTextChanged: {
                        var upper = text.toUpperCase()
                        if (text !== upper) {
                            var pos = cursorPosition
                            text = upper
                            cursorPosition = pos
                        }
                        if (root.selText !== upper) root.selText = upper
                    }
                    Keys.onReturnPressed: root.saveCurrent()
                }
                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.scaledGeometry(24)
                    Layout.rightMargin: Theme.scaledGeometry(24)
                    text: "One or two characters. Leave empty to use the project initials."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }
                Item { Layout.fillWidth: true; Layout.fillHeight: true }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.palette.chatDivider
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.scaledGeometry(18)
            Layout.rightMargin: Theme.scaledGeometry(18)
            Layout.topMargin: Theme.scaledGeometry(10)
            Layout.bottomMargin: Theme.scaledGeometry(12)
            spacing: Theme.scaledGeometry(10)
            Item { Layout.fillWidth: true }
            VrButton {
                objectName: "iconPickerCancel"
                text: "Cancel"
                variant: "secondary"
                implicitHeight: Theme.scaledGeometry(32)
                onClicked: root.close()
            }
            VrButton {
                objectName: "iconPickerSave"
                text: "Save icon"
                variant: "primary"
                implicitHeight: Theme.scaledGeometry(32)
                onClicked: root.saveCurrent()
            }
        }
    }

    background: Rectangle {
        radius: Theme.scaledGeometry(14)
        color: Theme.palette.chatSidebar
        border.width: 1
        border.color: Theme.palette.chatBorder
    }
}
