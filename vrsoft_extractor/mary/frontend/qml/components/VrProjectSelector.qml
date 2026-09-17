pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Button {
    id: control

    property var model: []
    property int currentIndex: 0
    property string popupObjectName: ""
    property bool compact: false
    property bool showSearch: true
    property bool showNewProject: true
    property string searchText: ""
    readonly property var currentItem: currentIndex >= 0 && currentIndex < model.length
        ? model[currentIndex] : ({})
    signal activated(int index)
    signal settingsRequested(int index)
    signal newProjectRequested()

    function normalized(value) {
        var text = String(value || "").toLowerCase().trim()
        if (text.normalize) text = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
        return text
    }

    readonly property var filteredModel: {
        var source = control.model || []
        var needle = normalized(control.searchText)
        var result = []
        for (var index = 0; index < source.length; ++index) {
            var item = source[index] || ({})
            if (needle.length) {
                var hay = normalized(item.label) + " " + normalized(item.path)
                if (hay.indexOf(needle) < 0) continue
            }
            result.push({
                label: String(item.label || ""),
                path: String(item.path || ""),
                icon: String(item.icon || ""),
                iconKind: String(item.iconKind || item.icon_kind || ""),
                iconEmoji: String(item.iconEmoji || item.icon_emoji || ""),
                iconColor: String(item.iconColor || item.icon_color || ""),
                iconText: String(item.iconText || item.icon_text || ""),
                sourceIndex: index
            })
        }
        return result
    }

    function openSelectorMenu() {
        updatePopupX()
        selectorPopup.open()
    }

    // Mantém o popup dentro da janela: alinhado à direita do botão,
    // mas deslocado para a direita quando sairia pela borda esquerda
    // (sidebar estreita) ou pela borda direita.
    function updatePopupX() {
        var popupW = selectorPopup.width
        var fallbackX = control.width - popupW
        var overlay = Overlay.overlay
        if (!overlay || !overlay.width) {
            selectorPopup.x = Math.min(0, fallbackX)
            return
        }
        var pos = control.mapToItem(overlay, 0, 0)
        if (!pos) {
            selectorPopup.x = Math.min(0, fallbackX)
            return
        }
        var x = fallbackX
        var left = pos.x + x
        if (left < 4) x += (4 - left)
        var right = pos.x + x + popupW
        if (right > overlay.width - 4) x -= (right - (overlay.width - 4))
        selectorPopup.x = x
    }

    function clickSettingsButton(sourceIndex) {
        for (var row = 0; row < projectList.count; ++row) {
            var item = projectList.itemAtIndex(row)
            if (item && item.sourceIndex === sourceIndex && item.configurable) {
                item.clickSettings()
                return true
            }
        }
        return false
    }

    function clickProjectButton(sourceIndex) {
        for (var row = 0; row < projectList.count; ++row) {
            var item = projectList.itemAtIndex(row)
            if (item && item.sourceIndex === sourceIndex) {
                item.activateSelection()
                return true
            }
        }
        return false
    }

    implicitWidth: compact ? 32 : -1
    implicitHeight: compact ? 32 : Theme.compactControlHeight
    leftPadding: compact ? 0 : 8
    rightPadding: compact ? 0 : 8
    topPadding: 0
    bottomPadding: 0
    hoverEnabled: true
    focusPolicy: compact ? Qt.NoFocus : Qt.StrongFocus
    onClicked: {
        if (selectorPopup.opened) selectorPopup.close()
        else {
            updatePopupX()
            selectorPopup.open()
        }
    }

    ToolTip.visible: compact && hovered
    ToolTip.text: currentIndex > 0 && currentItem.label
        ? ("Projeto: " + currentItem.label) : "Filtrar chats por projeto"
    Accessible.name: compact ? ToolTip.text : (currentItem.label || "Todos os projetos")

    contentItem: Item {
        implicitWidth: control.compact ? 32 : -1
        implicitHeight: control.compact ? 32 : -1

        VrProjectIcon {
            visible: control.compact
            anchors.centerIn: parent
            width: 22
            height: 22
            boxSize: 22
            iconSize: 16
            flat: true
            projectLabel: String(control.currentItem.label || "")
            iconPath: String(control.currentItem.icon || "")
            iconKind: String(control.currentItem.iconKind || control.currentItem.icon_kind || "")
            iconEmoji: String(control.currentItem.iconEmoji || control.currentItem.icon_emoji || "")
            iconColor: String(control.currentItem.iconColor || control.currentItem.icon_color || "")
            iconText: String(control.currentItem.iconText || control.currentItem.icon_text || "")
            isAll: !String(control.currentItem.path || "").length
        }

        Rectangle {
            visible: control.compact && control.currentIndex > 0
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 4
            width: 5
            height: 5
            radius: 2.5
            color: Theme.palette.brandOrange
        }

        RowLayout {
            visible: !control.compact
            anchors.fill: parent
            spacing: 7
            VrProjectIcon {
                Layout.preferredWidth: 22
                Layout.preferredHeight: 22
                boxSize: 22
                iconSize: 13
                projectLabel: String(control.currentItem.label || "")
                iconPath: String(control.currentItem.icon || "")
                iconKind: String(control.currentItem.iconKind || control.currentItem.icon_kind || "")
                iconEmoji: String(control.currentItem.iconEmoji || control.currentItem.icon_emoji || "")
                iconColor: String(control.currentItem.iconColor || control.currentItem.icon_color || "")
                iconText: String(control.currentItem.iconText || control.currentItem.icon_text || "")
                isAll: !String(control.currentItem.path || "").length
            }
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: control.currentItem.label || "Todos os projetos"
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
                maximumLineCount: 1
            }
            VrLineIcon {
                Layout.preferredWidth: 13
                Layout.preferredHeight: 13
                kind: selectorPopup.opened ? "chevronUp" : "chevronDown"
                foreground: Theme.palette.mutedText
            }
        }
    }

    background: Rectangle {
        radius: control.compact ? 4 : Theme.radiusSmall
        color: control.down || control.hovered || selectorPopup.opened
            ? (control.compact ? Qt.rgba(255, 255, 255, 0.1) : Theme.palette.chatControl) : (control.compact ? "transparent" : Theme.palette.surfaceRaised)
        border.width: control.compact ? (control.activeFocus ? 1 : 0) : 1
        border.color: control.activeFocus
            ? Theme.palette.focus : Theme.palette.border
    }

    Popup {
        id: selectorPopup
        objectName: control.popupObjectName
        parent: control
        x: control.compact ? Math.min(0, control.width - 264) : 0
        y: control.height + 4
        width: control.compact ? 264 : Math.max(240, control.width)
        height: Math.min(384, (searchHeader.visible ? 44 : 0)
            + Math.min(6, Math.max(1, control.filteredModel.length)) * 38 + 8
            + (control.showNewProject ? 47 : 0) + 8)
        padding: 4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: {
            control.searchText = ""
            updatePopupX()
            projectList.positionViewAtIndex(0, ListView.Contain)
            if (searchHeader.visible) Qt.callLater(function() { selectorSearch.forceActiveFocus() })
        }
        onClosed: control.searchText = ""

        contentItem: ColumnLayout {
            spacing: 0

            Item {
                id: searchHeader
                visible: control.showSearch
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? 40 : 0
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    anchors.rightMargin: 6
                    spacing: 6
                    VrLineIcon {
                        Layout.preferredWidth: 14
                        Layout.preferredHeight: 14
                        kind: "search"
                        foreground: Theme.palette.mutedText
                    }
                    TextField {
                        id: selectorSearch
                        objectName: "projectSelectorSearch"
                        Layout.fillWidth: true
                        placeholderText: "Buscar projetos..."
                        text: control.searchText
                        color: Theme.palette.text
                        placeholderTextColor: Theme.palette.mutedText
                        selectionColor: Theme.palette.selection
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        background: Item { }
                        selectByMouse: true
                        onTextChanged: {
                            if (control.searchText !== text) control.searchText = text
                            projectList.positionViewAtBeginning()
                        }
                        Keys.onDownPressed: {
                            if (projectList.count > 0)
                                projectList.currentIndex = Math.min(projectList.count - 1, projectList.currentIndex + 1)
                        }
                        Keys.onUpPressed: {
                            if (projectList.count > 0)
                                projectList.currentIndex = Math.max(0, projectList.currentIndex - 1)
                        }
                        Keys.onReturnPressed: {
                            if (projectList.count > 0) {
                                var current = control.filteredModel[projectList.currentIndex]
                                if (current) {
                                    control.activated(Number(current.sourceIndex))
                                    selectorPopup.close()
                                }
                            }
                        }
                        Keys.onEnterPressed: {
                            if (projectList.count > 0) {
                                var selected = control.filteredModel[projectList.currentIndex]
                                if (selected) {
                                    control.activated(Number(selected.sourceIndex))
                                    selectorPopup.close()
                                }
                            }
                        }
                    }
                    VrLineIcon {
                        visible: control.searchText.length > 0
                        Layout.preferredWidth: 12
                        Layout.preferredHeight: 12
                        kind: "close"
                        foreground: Theme.palette.mutedText
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: control.searchText = ""
                        }
                    }
                }
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: selectorSearch.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                    opacity: selectorSearch.activeFocus ? 1.0 : 0.6
                }
            }

            ListView {
                id: projectList
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.topMargin: 4
                Layout.bottomMargin: 2
                clip: true
                spacing: 1
                model: selectorPopup.opened ? control.filteredModel : []
                currentIndex: 0
                ScrollIndicator.vertical: ScrollIndicator { }

                delegate: Rectangle {
                    id: projectRow
                    required property int index
                    required property var modelData
                    readonly property int sourceIndex: Number(modelData.sourceIndex)
                    readonly property bool selected: control.currentIndex === sourceIndex
                    readonly property bool configurable: String(modelData.path || "").length > 0
                    readonly property string fullTitle: String(modelData.label || "") + (String(modelData.path || "").length ? "\n" + modelData.path : "")
                    function activateSettings() {
                        control.settingsRequested(projectRow.sourceIndex)
                        selectorPopup.close()
                    }
                    function activateSelection() {
                        control.activated(projectRow.sourceIndex)
                        selectorPopup.close()
                    }
                    function clickSettings() {
                        activateSettings()
                    }
                    width: projectList.width
                    height: 38
                    radius: 8
                    color: projectRow.selected ? Qt.alpha(Theme.palette.focus, 0.32)
                        : rowHover.hovered ? Theme.palette.chatControl : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 4
                        spacing: 9
                        VrProjectIcon {
                            Layout.preferredWidth: 22
                            Layout.preferredHeight: 22
                            boxSize: 22
                            iconSize: 13
                            flat: true
                            projectLabel: String(projectRow.modelData.label || "")
                            iconPath: String(projectRow.modelData.icon || "")
                            iconKind: String(projectRow.modelData.iconKind || "")
                            iconEmoji: String(projectRow.modelData.iconEmoji || "")
                            iconColor: String(projectRow.modelData.iconColor || "")
                            iconText: String(projectRow.modelData.iconText || "")
                            isAll: !String(projectRow.modelData.path || "").length
                        }
                        Text {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: projectRow.modelData.label
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(14)
                            font.weight: projectRow.selected ? Font.DemiBold : Font.Medium
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                            maximumLineCount: 1
                        }
                        VrIconButton {
                            id: settingsButton
                            objectName: "projectSettingsButton"
                            property int projectIndex: projectRow.sourceIndex
                            visible: projectRow.configurable
                            Layout.preferredWidth: visible ? 26 : 0
                            Layout.preferredHeight: 26
                            iconKind: "settings"
                            iconSize: 14
                            foreground: projectRow.selected || hovered
                                ? Theme.palette.text : Theme.palette.mutedText
                            ToolTip.visible: hovered
                            ToolTip.text: "Configurar projeto"
                            Accessible.name: "Configurar " + projectRow.modelData.label
                            onClicked: projectRow.activateSettings()
                            z: 2
                        }
                        VrLineIcon {
                            visible: projectRow.selected && !projectRow.configurable
                            Layout.preferredWidth: visible ? 14 : 0
                            Layout.preferredHeight: 14
                            kind: "check"
                            foreground: Theme.palette.brandOrange
                        }
                    }

                    ToolTip.visible: rowHover.hovered
                    ToolTip.delay: 500
                    ToolTip.text: projectRow.fullTitle

                    HoverHandler { id: rowHover }
                    MouseArea {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.right: parent.right
                        anchors.rightMargin: projectRow.configurable ? 30
                            : projectRow.selected ? 22 : 0
                        onClicked: projectRow.activateSelection()
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: selectorPopup.opened && projectList.count === 0
                    text: "Nenhum projeto encontrado"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                }
            }

            Rectangle {
                visible: control.showNewProject
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                Layout.preferredHeight: 1
                color: Theme.palette.chatBorder
                opacity: 0.7
            }

            Rectangle {
                id: newProjectRow
                visible: control.showNewProject
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? 38 : 0
                Layout.topMargin: visible ? 3 : 0
                Layout.bottomMargin: visible ? 1 : 0
                radius: 8
                color: newProjectHover.hovered ? Theme.palette.chatControl : "transparent"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 9
                    VrLineIcon {
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 16
                        kind: "plus"
                        foreground: Theme.palette.mutedText
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "New project"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                        font.weight: Font.Medium
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                HoverHandler { id: newProjectHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    onTapped: {
                        selectorPopup.close()
                        control.newProjectRequested()
                    }
                }
                Accessible.role: Accessible.Button
                Accessible.name: "New project"
            }
        }

        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.border
            radius: 12
        }
    }
}
