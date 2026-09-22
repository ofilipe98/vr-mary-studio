import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: control

    property var model: []
    property string activeAppId: ""
    property string searchText: ""
    property string placeholderText: "Selecionar aplicativo..."
    property bool hovered: false
    property var selectedAppIds: []

    signal applicationSelected(string appId)
    signal batchDecompileRequested(var appIds)

    function openSelector() {
        selectorPopup.open()
    }

    function closeSelector() {
        selectorPopup.close()
    }

    function toggleSelector() {
        if (selectorPopup.opened) {
            selectorPopup.close()
        } else {
            selectorPopup.open()
        }
    }

    function normalize(str) {
        if (!str) return ""
        var s = String(str).toLowerCase().trim()
        if (s.normalize) {
            s = s.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
        }
        return s
    }

    function isAppSelected(appId) {
        var list = control.selectedAppIds || []
        for (var i = 0; i < list.length; i++) {
            if (list[i] === appId) return true
        }
        return false
    }

    function toggleAppSelected(appId) {
        var list = []
        var found = false
        var current = control.selectedAppIds || []
        for (var i = 0; i < current.length; i++) {
            if (current[i] === appId) {
                found = true
            } else {
                list.push(current[i])
            }
        }
        if (!found) {
            list.push(appId)
        }
        control.selectedAppIds = list
    }

    function selectAllFiltered() {
        var list = []
        var current = control.selectedAppIds || []
        for (var k = 0; k < current.length; k++) {
            list.push(current[k])
        }
        var apps = control.filteredApps || []
        for (var i = 0; i < apps.length; i++) {
            var id = apps[i].appId
            var exists = false
            for (var j = 0; j < list.length; j++) {
                if (list[j] === id) { exists = true; break; }
            }
            if (!exists) list.push(id)
        }
        control.selectedAppIds = list
    }

    function deselectAllFiltered() {
        var apps = control.filteredApps || []
        var map = {}
        for (var i = 0; i < apps.length; i++) {
            map[apps[i].appId] = true
        }
        var current = control.selectedAppIds || []
        var next = []
        for (var j = 0; j < current.length; j++) {
            if (!map[current[j]]) {
                next.push(current[j])
            }
        }
        control.selectedAppIds = next
    }

    function selectPendingOnly() {
        var list = []
        var current = control.selectedAppIds || []
        for (var k = 0; k < current.length; k++) {
            list.push(current[k])
        }
        var apps = control.filteredApps || []
        for (var i = 0; i < apps.length; i++) {
            var item = apps[i]
            if (item.pendingCount > 0) {
                var exists = false
                for (var j = 0; j < list.length; j++) {
                    if (list[j] === item.appId) { exists = true; break; }
                }
                if (!exists) list.push(item.appId)
            }
        }
        control.selectedAppIds = list
    }

    function clearSelection() {
        control.selectedAppIds = []
    }

    readonly property bool allFilteredSelected: {
        var selected = control.selectedAppIds || []
        var apps = control.filteredApps || []
        if (!apps || apps.length === 0) return false
        for (var i = 0; i < apps.length; i++) {
            var found = false
            for (var j = 0; j < selected.length; j++) {
                if (selected[j] === apps[i].appId) {
                    found = true
                    break
                }
            }
            if (!found) return false
        }
        return true
    }

    readonly property var activeApp: {
        var list = control.model || []
        for (var i = 0; i < list.length; i++) {
            if (list[i].appId === control.activeAppId) return list[i]
        }
        return null
    }

    readonly property var filteredApps: {
        var q = normalize(control.searchText)
        var list = control.model || []
        if (!q) return list
        var res = []
        for (var i = 0; i < list.length; i++) {
            var item = list[i]
            var name = normalize(item.name)
            var appId = normalize(item.appId)
            if (name.indexOf(q) !== -1 || appId.indexOf(q) !== -1) {
                res.push(item)
            }
        }
        return res
    }

    implicitHeight: Theme.scaledGeometry(52)

    Rectangle {
        id: selectorBackground
        anchors.fill: parent
        radius: Theme.scaledGeometry(14)
        color: control.hovered || selectorPopup.opened ? Theme.palette.codeSurface : Theme.palette.background
        border.width: 1
        border.color: selectorPopup.opened ? Theme.palette.brandOrange : (control.hovered ? Theme.palette.focus : Theme.palette.border)

        Behavior on color {
            ColorAnimation { duration: Theme.fastDuration }
        }
        Behavior on border.color {
            ColorAnimation { duration: Theme.fastDuration }
        }

        // Full-width clickable background to toggle selector
        MouseArea {
            id: mainClickArea
            objectName: "appSelectorClickArea"
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            hoverEnabled: true
            onEntered: control.hovered = true
            onExited: control.hovered = false
            onClicked: control.toggleSelector()
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.scaledGeometry(12)
            anchors.rightMargin: Theme.scaledGeometry(12)
            spacing: Theme.scaledGeometry(12)

            // Left details area (visual only, clicks propagate to mainClickArea)
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.scaledGeometry(12)

                Item {
                    Layout.preferredWidth: Theme.scaledGeometry(32)
                    Layout.preferredHeight: Theme.scaledGeometry(32)

                    VrAppIcon {
                        visible: !!control.activeApp
                        anchors.fill: parent
                        appName: control.activeApp ? (control.activeApp.name || control.activeApp.appId) : ""
                        fallbackKind: "browser"
                        iconSize: 22
                        containerSize: 32
                    }

                    Rectangle {
                        visible: !control.activeApp
                        anchors.fill: parent
                        radius: Theme.radiusSmall
                        color: Theme.palette.chatBackground
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        VrLineIcon {
                            anchors.centerIn: parent
                            width: Theme.iconSmall
                            height: Theme.iconSmall
                            kind: "search"
                            foreground: Theme.palette.brandOrange
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 2

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: Theme.scaledGeometry(8)

                        Text {
                            text: control.activeApp ? (control.activeApp.name || control.activeApp.appId) : control.placeholderText
                            color: Theme.palette.headingText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(14)
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        Rectangle {
                            visible: !!control.activeApp && !!control.activeApp.hasUnidentified
                            implicitWidth: activeUnidentText.implicitWidth + 8
                            implicitHeight: Theme.scaledGeometry(20)
                            radius: Theme.radiusSmall
                            color: Qt.rgba(0.9, 0.6, 0.0, 0.15)
                            border.width: 1
                            border.color: Theme.palette.warning

                            Text {
                                id: activeUnidentText
                                anchors.centerIn: parent
                                text: "Versão pendente"
                                color: Theme.palette.warning
                                font.pixelSize: Theme.fontSizeMicro
                                font.weight: Font.Medium
                            }
                        }

                        Rectangle {
                            visible: !!control.activeApp && !!control.activeApp.hasVariants
                            implicitWidth: activeVarText.implicitWidth + 8
                            implicitHeight: Theme.scaledGeometry(20)
                            radius: Theme.radiusSmall
                            color: Qt.rgba(0.2, 0.6, 1.0, 0.15)
                            border.width: 1
                            border.color: Theme.palette.accentSoft

                            Text {
                                id: activeVarText
                                anchors.centerIn: parent
                                text: "Variantes"
                                color: Theme.palette.brandOrange
                                font.pixelSize: Theme.fontSizeMicro
                                font.weight: Font.Medium
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: {
                            var prefix = "";
                            if (control.selectedAppIds && control.selectedAppIds.length > 0) {
                                prefix = control.selectedAppIds.length + " selecionado(s) para descompilar · ";
                            }
                            if (control.activeApp) {
                                var app = control.activeApp;
                                var txt = app.versionCount + (app.versionCount === 1 ? " versão catalogada" : " versões catalogadas");
                                if (app.readyCount !== undefined) {
                                    txt += " · Prontas: " + app.readyCount + " · Pendentes: " + app.pendingCount;
                                    if (app.failedCount > 0) txt += " · Falhas: " + app.failedCount;
                                }
                                return prefix + txt;
                            }
                            var count = (control.model || []).length;
                            return prefix + count + (count === 1 ? " aplicativo detectado" : " aplicativos detectados") + " · Clique para pesquisar e selecionar";
                        }
                        color: Theme.palette.subtleText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        elide: Text.ElideRight
                    }
                }
            }

            // Right side buttons
            RowLayout {
                spacing: Theme.scaledGeometry(8)

                VrButton {
                    id: viewVersionsBtn
                    objectName: "appSelectorViewVersions"
                    visible: !!control.activeApp
                    text: "Ver versões"
                    variant: "secondary"
                    implicitHeight: Theme.scaledGeometry(32)
                    onClicked: {
                        selectorPopup.close()
                        if (control.activeApp) {
                            control.applicationSelected(control.activeApp.appId)
                        }
                    }
                }

                Rectangle {
                    implicitWidth: Theme.scaledGeometry(32)
                    implicitHeight: Theme.scaledGeometry(32)
                    radius: Theme.radiusSmall
                    color: control.hovered ? Theme.palette.chatBackground : "transparent"

                    VrLineIcon {
                        anchors.centerIn: parent
                        width: Theme.iconCompact
                        height: Theme.iconCompact
                        kind: selectorPopup.opened ? "chevronUp" : "chevronDown"
                        foreground: Theme.palette.mutedText
                    }
                }
            }
        }
    }

    Popup {
        id: selectorPopup
        objectName: "appSelectorPopup"
        parent: control
        x: 0
        y: control.height + 6
        width: control.width
        height: Math.min(460, Math.max(180, (control.filteredApps.length || 1) * 58 + 104))
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            radius: Theme.scaledGeometry(14)
            color: Theme.palette.background
            border.width: 1
            border.color: Theme.palette.border
        }

        onOpened: {
            control.searchText = ""
            appList.positionViewAtBeginning()
            searchField.forceActiveFocus()
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // Search Bar Header
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.scaledGeometry(48)
                color: "transparent"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.scaledGeometry(12)
                    anchors.rightMargin: Theme.scaledGeometry(12)
                    spacing: Theme.scaledGeometry(8)

                    VrLineIcon {
                        Layout.preferredWidth: Theme.iconSmall
                        Layout.preferredHeight: Theme.iconSmall
                        kind: "search"
                        foreground: Theme.palette.mutedText
                    }

                    TextField {
                        id: searchField
                        objectName: "appSelectorSearchField"
                        Layout.fillWidth: true
                        placeholderText: "Pesquisar aplicativo por nome..."
                        text: control.searchText
                        color: Theme.palette.text
                        placeholderTextColor: Theme.palette.mutedText
                        selectionColor: Theme.palette.selection
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        background: Item { }
                        selectByMouse: true
                        onTextChanged: {
                            if (control.searchText !== text) {
                                control.searchText = text
                            }
                            appList.positionViewAtBeginning()
                        }

                        Keys.onReturnPressed: {
                            if (control.filteredApps.length > 0) {
                                control.applicationSelected(control.filteredApps[0].appId)
                                selectorPopup.close()
                            }
                        }
                        Keys.onEnterPressed: {
                            if (control.filteredApps.length > 0) {
                                control.applicationSelected(control.filteredApps[0].appId)
                                selectorPopup.close()
                            }
                        }
                    }

                    VrLineIcon {
                        visible: control.searchText.length > 0
                        Layout.preferredWidth: Theme.iconCompact
                        Layout.preferredHeight: Theme.iconCompact
                        kind: "close"
                        foreground: searchCloseMouse.containsMouse ? Theme.palette.text : Theme.palette.mutedText

                        MouseArea {
                            id: searchCloseMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                control.searchText = ""
                                searchField.forceActiveFocus()
                            }
                        }
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: searchField.activeFocus ? Theme.palette.brandOrange : Theme.palette.chatBorder
                }
            }

            // Selection & Batch Action Toolbar
            Rectangle {
                id: batchToolbar
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.scaledGeometry(38)
                color: Theme.palette.chatControl

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.scaledGeometry(10)
                    anchors.rightMargin: Theme.scaledGeometry(12)
                    spacing: Theme.scaledGeometry(8)

                    VrCheckBox {
                        id: selectAllBox
                        objectName: "appSelectorSelectAll"
                        text: control.allFilteredSelected ? "Desmarcar todos" : "Selecionar todos"
                        checked: control.allFilteredSelected
                        onToggled: {
                            if (control.allFilteredSelected) {
                                control.deselectAllFiltered()
                            } else {
                                control.selectAllFiltered()
                            }
                        }
                    }

                    VrButton {
                        objectName: "appSelectorPendingOnlyButton"
                        text: "Apenas pendentes"
                        variant: "ghost"
                        implicitHeight: Theme.controlHeightCompact
                        onClicked: control.selectPendingOnly()
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        visible: control.selectedAppIds.length > 0
                        text: control.selectedAppIds.length + " selecionado(s)"
                        color: Theme.palette.brandOrange
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.DemiBold
                    }

                    VrButton {
                        objectName: "appSelectorClearSelectionButton"
                        visible: control.selectedAppIds.length > 0
                        text: "Limpar"
                        variant: "ghost"
                        implicitHeight: Theme.controlHeightCompact
                        onClicked: control.clearSelection()
                    }

                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: Theme.palette.chatBorder
                }
            }

            // Results List
            ListView {
                id: appList
                objectName: "appSelectorList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 6
                clip: true
                spacing: Theme.scaledGeometry(3)
                model: control.filteredApps
                visible: control.filteredApps.length > 0
                ScrollIndicator.vertical: ScrollIndicator { }

                delegate: Rectangle {
                    id: itemDelegate
                    width: appList.width
                    height: Theme.scaledGeometry(56)
                    radius: Theme.radiusSmall
                    color: control.isAppSelected(modelData.appId)
                        ? Qt.rgba(1.0, 0.45, 0.0, 0.12)
                        : (modelData.appId === control.activeAppId
                            ? Qt.rgba(1.0, 0.45, 0.0, 0.06)
                            : (itemMouse.containsMouse ? Theme.palette.chatControl : "transparent"))
                    border.width: control.isAppSelected(modelData.appId) || modelData.appId === control.activeAppId ? 1 : 0
                    border.color: Theme.palette.brandOrange

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.scaledGeometry(8)
                        anchors.rightMargin: Theme.scaledGeometry(12)
                        spacing: Theme.scaledGeometry(8)

                        VrCheckBox {
                            id: itemCheckBox
                            objectName: "appItemCheckBox_" + modelData.appId
                            checked: control.isAppSelected(modelData.appId)
                            onToggled: control.toggleAppSelected(modelData.appId)
                        }

                        // App Info Click Area
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            RowLayout {
                                anchors.fill: parent
                                spacing: Theme.scaledGeometry(10)

                                VrAppIcon {
                                    Layout.preferredWidth: Theme.scaledGeometry(32)
                                    Layout.preferredHeight: Theme.scaledGeometry(32)
                                    appName: modelData.name || modelData.appId
                                    fallbackKind: "browser"
                                    iconSize: 22
                                    containerSize: 32
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 2

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        spacing: Theme.scaledGeometry(6)

                                        Text {
                                            text: modelData.name || modelData.appId
                                            color: Theme.palette.headingText
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(13)
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }

                                        Rectangle {
                                            visible: !!modelData.hasUnidentified
                                            implicitWidth: itemUnidentText.implicitWidth + 8
                                            implicitHeight: Theme.scaledGeometry(20)
                                            radius: Theme.radiusSmall
                                            color: Qt.rgba(0.9, 0.6, 0.0, 0.15)
                                            border.width: 1
                                            border.color: Theme.palette.warning

                                            Text {
                                                id: itemUnidentText
                                                anchors.centerIn: parent
                                                text: "Versão pendente"
                                                color: Theme.palette.warning
                                                font.pixelSize: Theme.fontSizeMicro
                                                font.weight: Font.Medium
                                            }
                                        }

                                        Rectangle {
                                            visible: !!modelData.hasVariants
                                            implicitWidth: itemVarText.implicitWidth + 8
                                            implicitHeight: Theme.scaledGeometry(20)
                                            radius: Theme.radiusSmall
                                            color: Qt.rgba(0.2, 0.6, 1.0, 0.15)
                                            border.width: 1
                                            border.color: Theme.palette.accentSoft

                                            Text {
                                                id: itemVarText
                                                anchors.centerIn: parent
                                                text: "Variantes"
                                                color: Theme.palette.brandOrange
                                                font.pixelSize: Theme.fontSizeMicro
                                                font.weight: Font.Medium
                                            }
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        text: modelData.versionCount + (modelData.versionCount === 1 ? " versão" : " versões") +
                                              " · Prontas: " + modelData.readyCount +
                                              " · Pendentes: " + modelData.pendingCount +
                                              (modelData.failedCount > 0 ? (" · Falhas: " + modelData.failedCount) : "")
                                        color: Theme.palette.subtleText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeCaption
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            MouseArea {
                                id: itemMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: control.toggleAppSelected(modelData.appId)
                            }
                        }

                        // Ver versões button on the right
                        Rectangle {
                            id: verVersoesBtn
                            implicitHeight: Theme.scaledGeometry(28)
                            implicitWidth: verVersoesContent.implicitWidth + 12
                            radius: Theme.radiusSmall
                            color: verVersoesMouse.containsMouse ? Qt.rgba(1.0, 0.45, 0.0, 0.12) : "transparent"
                            border.width: 1
                            border.color: verVersoesMouse.containsMouse ? Theme.palette.brandOrange : Theme.palette.chatBorder

                            RowLayout {
                                id: verVersoesContent
                                anchors.centerIn: parent
                                spacing: Theme.scaledGeometry(4)

                                Text {
                                    text: "Ver versões"
                                    color: verVersoesMouse.containsMouse ? Theme.palette.brandOrange : Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: Font.Medium
                                }

                                VrLineIcon {
                                    Layout.preferredWidth: Theme.iconMicro
                                    Layout.preferredHeight: Theme.iconMicro
                                    kind: "chevronRight"
                                    foreground: verVersoesMouse.containsMouse ? Theme.palette.brandOrange : Theme.palette.mutedText
                                }
                            }

                            MouseArea {
                                id: verVersoesMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    control.applicationSelected(modelData.appId)
                                    selectorPopup.close()
                                }
                            }
                        }
                    }
                }
            }

            // Empty State
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: control.filteredApps.length === 0

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: Theme.scaledGeometry(8)

                    VrLineIcon {
                        Layout.alignment: Qt.AlignHCenter
                        width: Theme.iconSize
                        height: Theme.iconSize
                        kind: "search"
                        foreground: Theme.palette.mutedText
                    }

                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: "Nenhum aplicativo encontrado para \"" + control.searchText + "\""
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                    }
                }
            }
        }
    }
}
