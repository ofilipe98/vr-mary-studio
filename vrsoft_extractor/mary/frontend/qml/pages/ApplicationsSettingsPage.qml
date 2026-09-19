import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"
import "../settings/appearance"

Item {
    id: root
    property bool ultraContextAdded: false
    readonly property var selectedDistribution: {
        var details = chat.selectedVersionDetails
        var origins = details.origin_packages || []
        for (var i = 0; i < origins.length; i++) {
            if (origins[i].package_id === chat.selectedAppOriginId)
                return (details.distribution_contexts || {})[origins[i].distribution_id] || {}
        }
        return {}
    }
    objectName: "appsSettingsPage"

    // View navigation state: 0 = Apps catalog, 1 = App versions, 2 = Version view
    property int navigationLevel: 0
    property string activeAppId: chat.selectedAppId
    property string activeVersion: chat.selectedAppVersion
    property int versionSubTab: 0 // 0: Detalhes, 1: Descompilacao, 2: Comparacao, 3: Origens

    property string manualVersionInput: ""
    property string compareTargetVersion: ""
    property string pendingUnlinkPackageId: ""
    property string pendingUnlinkPackageName: ""
    property string pendingReleaseRemoval: ""
    property string pendingRenamePackageId: ""
    property string pendingRenamePackageName: ""
    property string pendingDeleteJarsPackageId: ""
    property string pendingDeleteJarsPackageName: ""
    property var decompiledDetectionResult: null

    Connections {
        target: chat
        function onDecompiledDirectoryDetected(result) {
            if (result.is_valid) {
                root.decompiledDetectionResult = result;
                decompiledImportDialog.open();
            }
        }
    }
    Component.onCompleted: chat.refreshCodeAnalysisReleases()

    onActiveAppIdChanged: {
        if (!activeAppId && navigationLevel > 0) {
            navigationLevel = 0;
        }
    }

    ScrollView {
        id: appsScroll
        objectName: "appsSettingsScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        topPadding: 4
        rightPadding: 12
        bottomPadding: 24
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        Item {
            width: appsScroll.availableWidth
            implicitHeight: appsColumn.implicitHeight

            ColumnLayout {
                id: appsColumn
                anchors.horizontalCenter: parent.horizontalCenter
                width: root.navigationLevel >= 2 ? parent.width : Math.min(848, parent.width)
                spacing: 24

                Text {
                    Layout.fillWidth: true
                    text: chat.applicationsCatalogError
                    visible: text.length > 0
                    color: Theme.palette.danger
                    wrapMode: Text.Wrap
                }
            // Refined Application Import Preview Card
            Rectangle {
                id: importPreviewCard
                objectName: "applicationImportPreview"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                visible: !!chat.applicationImportPreview.state
                radius: Theme.radiusCard
                color: Theme.palette.codeSurface
                border.width: 1
                border.color: chat.applicationImportPreview.error
                    ? Theme.palette.danger
                    : (chat.applicationImportPreview.state === "ready" ? Theme.palette.brandOrange : Theme.palette.chatBorder)

                property string searchFilter: ""
                property string filterRole: "all" // "all", "app", "dependency"
                readonly property var previewRows: chat.applicationImportPreview.rows || []
                readonly property int totalCount: previewRows.length
                readonly property int newAppsCount: {
                    var count = 0;
                    for (var i = 0; i < previewRows.length; i++) {
                        if (previewRows[i].status === "Novo aplicativo") count++;
                    }
                    return count;
                }
                readonly property int depsCount: {
                    var count = 0;
                    for (var i = 0; i < previewRows.length; i++) {
                        if (previewRows[i].role === "dependency") count++;
                    }
                    return count;
                }
                readonly property int updateCount: {
                    var count = 0;
                    for (var i = 0; i < previewRows.length; i++) {
                        var st = previewRows[i].status;
                        if (st === "Nova versão" || st === "Nova variante") count++;
                    }
                    return count;
                }
                readonly property int existingCount: {
                    var count = 0;
                    for (var i = 0; i < previewRows.length; i++) {
                        if (previewRows[i].status === "Já existente — reutilizar") count++;
                    }
                    return count;
                }

                function getFilteredRows() {
                    var list = previewRows;
                    var term = searchFilter.trim().toLowerCase();
                    var role = filterRole;
                    if (!term && role === "all") return list;
                    var res = [];
                    for (var i = 0; i < list.length; i++) {
                        var item = list[i];
                        if (role === "app" && item.role !== "application") continue;
                        if (role === "dependency" && item.role !== "dependency") continue;
                        if (term) {
                            var appMatch = (item.application || "").toLowerCase().indexOf(term) !== -1;
                            var pathMatch = (item.relative_path || "").toLowerCase().indexOf(term) !== -1;
                            var statusMatch = (item.status || "").toLowerCase().indexOf(term) !== -1;
                            var verMatch = (item.version || "").toLowerCase().indexOf(term) !== -1;
                            if (!appMatch && !pathMatch && !statusMatch && !verMatch) continue;
                        }
                        res.push(item);
                    }
                    return res;
                }

                implicitHeight: previewContentLayout.implicitHeight + 24

                ColumnLayout {
                    id: previewContentLayout
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    // Header Row
                    GridLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        columns: root.width < 640 ? 1 : 2
                        rowSpacing: 10
                        columnSpacing: 12

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 10

                            Rectangle {
                                Layout.preferredWidth: 36
                                Layout.preferredHeight: 36
                                radius: Theme.radiusSmall
                                color: chat.applicationImportPreview.error
                                    ? Qt.rgba(0.9, 0.2, 0.2, 0.15)
                                    : Qt.rgba(0.95, 0.45, 0.15, 0.15)
                                border.width: 1
                                border.color: chat.applicationImportPreview.error
                                    ? Theme.palette.danger
                                    : Theme.palette.brandOrange

                                VrLineIcon {
                                    anchors.centerIn: parent
                                    width: 18
                                    height: 18
                                    kind: chat.applicationImportPreview.error ? "warning" : "files"
                                    foreground: chat.applicationImportPreview.error
                                        ? Theme.palette.danger
                                        : Theme.palette.brandOrange
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 2

                                Text {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: chat.applicationImportPreview.state === "running"
                                        ? "Preparando prévia…"
                                        : (chat.applicationImportPreview.error || "Prévia da importação — confira aplicativos, versões e variantes")
                                    color: chat.applicationImportPreview.error
                                        ? Theme.palette.danger
                                        : Theme.palette.headingText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(14)
                                    font.weight: Font.DemiBold
                                    wrapMode: Text.WordWrap
                                }

                                Text {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: chat.applicationImportPreview.state === "running"
                                        ? (chat.releaseSnapshotStatus || "Detectando aplicativos…")
                                        : (chat.applicationImportPreview.error
                                            ? chat.applicationImportPreview.error
                                            : "Revise os componentes identificados no pacote antes de confirmar a inclusão no catálogo.")
                                    color: Theme.palette.subtleText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }

                        RowLayout {
                            Layout.alignment: root.width < 640 ? Qt.AlignLeft : Qt.AlignRight
                            spacing: 8

                            VrButton {
                                text: "Cancelar"
                                variant: "secondary"
                                implicitHeight: 32
                                onClicked: chat.cancelApplicationImport()
                            }

                            VrButton {
                                objectName: "confirmApplicationImport"
                                text: "Confirmar importação"
                                variant: "primary"
                                implicitHeight: 32
                                enabled: chat.applicationImportPreview.state === "ready"
                                onClicked: chat.confirmApplicationImport()
                            }
                        }
                    }

                    // Running state progress indicator
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: chat.applicationImportPreview.state === "running"
                        spacing: 6

                        VrProgressBar {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            indeterminate: true
                            barHeight: 6
                            accentColor: Theme.palette.brandOrange
                        }
                    }

                    // Ready state content
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: chat.applicationImportPreview.state === "ready"
                        spacing: 10

                        // Summary metrics badges
                        Flow {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 6

                            Rectangle {
                                implicitHeight: 24
                                implicitWidth: totalLabel.implicitWidth + 14
                                radius: 12
                                color: Theme.palette.chatBackground
                                border.width: 1
                                border.color: Theme.palette.chatBorder
                                Text {
                                    id: totalLabel
                                    anchors.centerIn: parent
                                    text: importPreviewCard.totalCount + " componentes"
                                    color: Theme.palette.headingText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                    font.weight: Font.DemiBold
                                }
                            }

                            Rectangle {
                                visible: importPreviewCard.newAppsCount > 0
                                implicitHeight: 24
                                implicitWidth: newLabel.implicitWidth + 14
                                radius: 12
                                color: Qt.rgba(0.06, 0.72, 0.50, 0.15)
                                border.width: 1
                                border.color: Theme.palette.success
                                Text {
                                    id: newLabel
                                    anchors.centerIn: parent
                                    text: importPreviewCard.newAppsCount + " novos aplicativos"
                                    color: Theme.palette.success
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                    font.weight: Font.DemiBold
                                }
                            }

                            Rectangle {
                                visible: importPreviewCard.depsCount > 0
                                implicitHeight: 24
                                implicitWidth: depLabel.implicitWidth + 14
                                radius: 12
                                color: Qt.rgba(0.23, 0.51, 0.96, 0.15)
                                border.width: 1
                                border.color: "#3B82F6"
                                Text {
                                    id: depLabel
                                    anchors.centerIn: parent
                                    text: importPreviewCard.depsCount + " dependências"
                                    color: "#3B82F6"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                    font.weight: Font.DemiBold
                                }
                            }

                            Rectangle {
                                visible: importPreviewCard.updateCount > 0
                                implicitHeight: 24
                                implicitWidth: updateLabel.implicitWidth + 14
                                radius: 12
                                color: Qt.rgba(0.96, 0.62, 0.04, 0.15)
                                border.width: 1
                                border.color: Theme.palette.warning
                                Text {
                                    id: updateLabel
                                    anchors.centerIn: parent
                                    text: importPreviewCard.updateCount + " atualizações / variantes"
                                    color: Theme.palette.warning
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                    font.weight: Font.DemiBold
                                }
                            }

                            Rectangle {
                                visible: importPreviewCard.existingCount > 0
                                implicitHeight: 24
                                implicitWidth: existLabel.implicitWidth + 14
                                radius: 12
                                color: Qt.rgba(0.5, 0.5, 0.5, 0.12)
                                border.width: 1
                                border.color: Theme.palette.chatBorder
                                Text {
                                    id: existLabel
                                    anchors.centerIn: parent
                                    text: importPreviewCard.existingCount + " já existentes"
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                }
                            }
                        }

                        // Search and filter toolbar
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 8

                            VrTextField {
                                id: previewSearchInput
                                Layout.fillWidth: true
                                Layout.minimumWidth: 80
                                implicitHeight: 32
                                placeholderText: "Filtrar por aplicativo, versão ou caminho…"
                                text: importPreviewCard.searchFilter
                                onTextChanged: importPreviewCard.searchFilter = text
                            }

                            VrButton {
                                text: "Todos"
                                variant: importPreviewCard.filterRole === "all" ? "primary" : "secondary"
                                implicitHeight: 32
                                onClicked: importPreviewCard.filterRole = "all"
                            }

                            VrButton {
                                text: "Apps"
                                variant: importPreviewCard.filterRole === "app" ? "primary" : "secondary"
                                implicitHeight: 32
                                onClicked: importPreviewCard.filterRole = "app"
                            }

                            VrButton {
                                text: "Dependências"
                                variant: importPreviewCard.filterRole === "dependency" ? "primary" : "secondary"
                                implicitHeight: 32
                                onClicked: importPreviewCard.filterRole = "dependency"
                            }
                        }

                        // Scrollable components list
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.preferredHeight: Math.min(380, Math.max(90, previewItemsColumn.implicitHeight + 16))
                            clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical.policy: ScrollBar.AsNeeded

                            ColumnLayout {
                                id: previewItemsColumn
                                width: parent.width
                                spacing: 6

                                Repeater {
                                    model: importPreviewCard.getFilteredRows()
                                    delegate: Rectangle {
                                        id: previewItemDelegate
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitHeight: Math.max(54, itemRowLayout.implicitHeight + 12)
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: 1
                                        border.color: Theme.palette.chatBorder

                                        property bool isNew: modelData.status === "Novo aplicativo"
                                        property bool isDep: modelData.role === "dependency"
                                        property bool isUpdate: modelData.status === "Nova versão" || modelData.status === "Nova variante"
                                        property bool hashCopied: false

                                        Timer {
                                            id: hashResetTimer
                                            interval: 1800
                                            onTriggered: previewItemDelegate.hashCopied = false
                                        }

                                        RowLayout {
                                            id: itemRowLayout
                                            anchors.fill: parent
                                            anchors.leftMargin: 8
                                            anchors.rightMargin: 8
                                            spacing: 10

                                            // Official Application Icon
                                            VrAppIcon {
                                                Layout.preferredWidth: 32
                                                Layout.preferredHeight: 32
                                                appName: modelData.application
                                                fallbackKind: modelData.role === "dependency" ? "files" : "browser"
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
                                                    spacing: 6

                                                    Text {
                                                        text: modelData.application
                                                        color: Theme.palette.headingText
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: Theme.fontSize(13)
                                                        font.weight: Font.DemiBold
                                                        elide: Text.ElideRight
                                                    }

                                                    Rectangle {
                                                        implicitWidth: verText.implicitWidth + 8
                                                        implicitHeight: 18
                                                        radius: 4
                                                        color: Theme.palette.codeSurface
                                                        border.width: 1
                                                        border.color: Theme.palette.chatBorder
                                                        Text {
                                                            id: verText
                                                            anchors.centerIn: parent
                                                            text: modelData.version
                                                            color: Theme.palette.brandOrange
                                                            font.family: Theme.monospaceFontFamily
                                                            font.pixelSize: Theme.fontSizeMicro
                                                            font.weight: Font.Medium
                                                        }
                                                    }

                                                    Item { Layout.fillWidth: true }
                                                }

                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    Layout.minimumWidth: 0
                                                    spacing: 6

                                                    Text {
                                                        text: modelData.relative_path
                                                        color: Theme.palette.mutedText
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: Theme.fontSizeMicro
                                                        elide: Text.ElideMiddle
                                                        Layout.maximumWidth: 220
                                                    }

                                                    Text {
                                                        text: "•"
                                                        color: Theme.palette.chatBorder
                                                        font.pixelSize: Theme.fontSizeMicro
                                                    }

                                                    Text {
                                                        text: "SHA-256 " + (modelData.sha256 ? (modelData.sha256.substring(0, 8) + "…" + modelData.sha256.substring(modelData.sha256.length - 8)) : "")
                                                        color: Theme.palette.subtleText
                                                        font.family: Theme.monospaceFontFamily
                                                        font.pixelSize: Theme.fontSizeCaption
                                                    }

                                                    Rectangle {
                                                        implicitWidth: copyLabel.implicitWidth + 8
                                                        implicitHeight: 16
                                                        radius: 3
                                                        color: copyMouse.containsMouse ? Theme.palette.selection : "transparent"

                                                        Text {
                                                            id: copyLabel
                                                            anchors.centerIn: parent
                                                            text: previewItemDelegate.hashCopied ? "Copiado!" : "Copiar"
                                                            color: previewItemDelegate.hashCopied ? Theme.palette.success : Theme.palette.mutedText
                                                            font.family: Theme.fontFamily
                                                            font.pixelSize: Theme.fontSizeMicro
                                                        }

                                                        MouseArea {
                                                            id: copyMouse
                                                            anchors.fill: parent
                                                            hoverEnabled: true
                                                            cursorShape: Qt.PointingHandCursor
                                                            onClicked: {
                                                                studio.copyText(modelData.sha256);
                                                                previewItemDelegate.hashCopied = true;
                                                                hashResetTimer.restart();
                                                            }
                                                        }
                                                    }

                                                    Item { Layout.fillWidth: true }
                                                }
                                            }

                                            // Status badge
                                            Rectangle {
                                                Layout.alignment: Qt.AlignVCenter
                                                implicitHeight: 22
                                                implicitWidth: statusText.implicitWidth + 12
                                                radius: 11
                                                color: previewItemDelegate.isNew ? Qt.rgba(0.06, 0.72, 0.50, 0.15)
                                                     : (previewItemDelegate.isDep ? Qt.rgba(0.23, 0.51, 0.96, 0.15)
                                                     : (previewItemDelegate.isUpdate ? Qt.rgba(0.96, 0.62, 0.04, 0.15)
                                                     : Qt.rgba(0.5, 0.5, 0.5, 0.12)))
                                                border.width: 1
                                                border.color: previewItemDelegate.isNew ? Theme.palette.success
                                                     : (previewItemDelegate.isDep ? "#3B82F6"
                                                     : (previewItemDelegate.isUpdate ? Theme.palette.warning
                                                     : Theme.palette.chatBorder))

                                                Text {
                                                    id: statusText
                                                    anchors.centerIn: parent
                                                    text: modelData.status
                                                    color: previewItemDelegate.isNew ? Theme.palette.success
                                                         : (previewItemDelegate.isDep ? "#3B82F6"
                                                         : (previewItemDelegate.isUpdate ? Theme.palette.warning
                                                         : Theme.palette.mutedText))
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: Theme.fontSizeMicro
                                                    font.weight: Font.DemiBold
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // Bottom action buttons row
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 8

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: importPreviewCard.getFilteredRows().length + " de " + importPreviewCard.totalCount + " componentes exibidos"
                                color: Theme.palette.subtleText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeMicro
                            }

                            VrButton {
                                text: "Cancelar"
                                variant: "secondary"
                                implicitHeight: 30
                                onClicked: chat.cancelApplicationImport()
                            }

                            VrButton {
                                text: "Confirmar importação"
                                variant: "primary"
                                implicitHeight: 30
                                enabled: chat.applicationImportPreview.state === "ready"
                                onClicked: chat.confirmApplicationImport()
                            }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: root.navigationLevel === 0
                spacing: 8

                Text {
                    text: "Importação de pacotes e JARs"
                    Layout.leftMargin: 16
                    Layout.fillWidth: true
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }

                VrButton {
                    objectName: "globalDecompileConfigHeaderButton"
                    text: "Configurações de descompilação"
                    variant: "ghost"
                    implicitHeight: 28
                    enabled: !chat.codeProcessingRunning
                    onClicked: globalDecompileConfigDialog.open()
                }

                VrButton {
                    text: chat.applicationsCatalogLoading ? "Atualizando…" : "Atualizar"
                    variant: "ghost"
                    implicitHeight: 28
                    enabled: !chat.applicationsCatalogLoading
                    onClicked: chat.refreshApplicationsCatalog()
                }
            }

            Rectangle {
                id: appsImportCard
                objectName: "appsImportCard"
                visible: root.navigationLevel === 0
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: importActionsLayout.implicitHeight + 2
                radius: 14
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border

                ColumnLayout {
                    id: importActionsLayout
                    objectName: "vrUltraJarDirectoryCard"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 1
                    spacing: 0

                    AppearanceRow {
                        title: "Importação direta"
                        description: "Importe pacotes compactados, JARs avulsos ou pastas já descompiladas para o catálogo."
                        divider: true

                        Flow {
                            spacing: 8
                            Layout.alignment: Qt.AlignRight

                            VrButton {
                                text: "Importar pacote VR"
                                enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                                variant: "primary"
                                implicitHeight: 32
                                onClicked: {
                                    var res = chat.selectAndImportPackage();
                                    if (res) {
                                        chat.refreshApplicationsCatalog();
                                    }
                                }
                            }

                            VrButton {
                                text: "Importar JAR avulso"
                                enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                                variant: "secondary"
                                implicitHeight: 32
                                onClicked: {
                                    var res = chat.selectAndImportSingleJar();
                                    if (res) {
                                        chat.refreshApplicationsCatalog();
                                    }
                                }
                            }

                            VrButton {
                                text: "Importar código descompilado"
                                enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                                variant: "secondary"
                                implicitHeight: 32
                                onClicked: {
                                    var det = chat.detectDecompiledDirectory("");
                                    if (det && det.is_valid) {
                                        root.decompiledDetectionResult = det;
                                        decompiledImportDialog.open();
                                    }
                                }
                            }
                        }
                    }

                    AppearanceRow {
                        title: "Diretório padrão dos JARs"
                        description: "Pasta raiz onde as compilações e bibliotecas JAR estão armazenadas."
                        divider: true

                        RowLayout {
                            spacing: 8

                            VrComboBox {
                                id: jarSourcePicker
                                objectName: "vrUltraJarDirectoryPicker"
                                Layout.preferredWidth: 240
                                implicitHeight: 34
                                enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                                model: chat.codeAnalysisJarSourceItems
                                textRole: "label"
                                currentIndex: {
                                    for (var index = 0; index < chat.codeAnalysisJarSourceItems.length; ++index) {
                                        if (chat.codeAnalysisJarSourceItems[index].value === chat.codeAnalysisJarSource)
                                            return index
                                    }
                                    return 0
                                }
                                onActivated: index => {
                                    if (index < chat.codeAnalysisJarSourceItems.length)
                                        chat.setCodeAnalysisJarSource(chat.codeAnalysisJarSourceItems[index].value)
                                }
                                background: Rectangle {
                                    radius: 8
                                    color: Theme.palette.codeSurface
                                    border.width: jarSourcePicker.activeFocus ? 2 : 1
                                    border.color: jarSourcePicker.activeFocus ? Theme.palette.focus : Theme.palette.border
                                }
                            }

                            VrButton {
                                text: "Escolher pasta…"
                                variant: "secondary"
                                implicitHeight: 34
                                enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                                onClicked: chat.selectCustomJarDirectory()
                            }
                        }
                    }

                    AppearanceRow {
                        title: "Escopo da análise"
                        description: "Indexar todos os componentes da release ou isolar um único JAR."
                        divider: true

                        VrComboBox {
                            id: jarScopePicker
                            objectName: "vrUltraJarScopePicker"
                            Layout.preferredWidth: 260
                            implicitHeight: 34
                            enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                            model: [
                                { "label": "Pacote completo ou parcial", "value": "full_release" },
                                { "label": "Somente um JAR", "value": "single_jar" }
                            ]
                            textRole: "label"
                            currentIndex: chat.codeAnalysisSnapshotScope === "single_jar" ? 1 : 0
                            onActivated: index => chat.setCodeAnalysisSnapshotScope(
                                index === 1 ? "single_jar" : "full_release"
                            )
                            background: Rectangle {
                                radius: 8
                                color: Theme.palette.codeSurface
                                border.width: jarScopePicker.activeFocus ? 2 : 1
                                border.color: jarScopePicker.activeFocus ? Theme.palette.focus : Theme.palette.border
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.topMargin: 4
                        Layout.bottomMargin: 8
                        text: {
                            var index = jarSourcePicker.currentIndex
                            if (index < 0 || index >= chat.codeAnalysisJarSourceItems.length)
                                return ""
                            var item = chat.codeAnalysisJarSourceItems[index]
                            if (chat.codeAnalysisSnapshotScope === "single_jar")
                                return item.path + " · " + item.status + " · escolha um JAR abaixo"
                            var composition = item.jarCount > 0
                                ? " · " + chat.codeAnalysisExpectedJarCount + " JARs formam a release completa; quantidades menores serão indexadas como release parcial"
                                : ""
                            return item.path + " · " + item.status + composition
                        }
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    AppearanceRow {
                        visible: chat.codeAnalysisSnapshotScope === "single_jar"
                        title: "JAR selecionado"
                        description: "Arquivo JAR específico a ser analisado."
                        divider: true

                        RowLayout {
                            objectName: "vrUltraSingleJarRow"
                            spacing: 8
                            Layout.preferredWidth: Math.min(340, importActionsLayout.width - 32)

                            VrTextField {
                                objectName: "vrUltraSingleJarPath"
                                Layout.fillWidth: true
                                implicitHeight: 34
                                readOnly: true
                                text: chat.codeAnalysisSingleJarPath
                                placeholderText: "Nenhum JAR selecionado"
                                background: Rectangle {
                                    radius: 8
                                    color: Theme.palette.codeSurface
                                    border.width: 1
                                    border.color: Theme.palette.border
                                }
                            }

                            VrButton {
                                objectName: "vrUltraSelectSingleJarButton"
                                text: "Escolher JAR…"
                                implicitHeight: 34
                                enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                                onClicked: chat.selectCodeAnalysisSingleJar()
                            }
                        }
                    }

                    AppearanceRow {
                        title: "Preparação de release"
                        description: "Identificador da release e geração da prévia de componentes."
                        divider: false

                        RowLayout {
                            spacing: 8
                            Layout.preferredWidth: Math.min(340, importActionsLayout.width - 32)

                            VrTextField {
                                id: releaseIdField
                                objectName: "vrUltraReleaseIdField"
                                Layout.fillWidth: true
                                implicitHeight: 34
                                placeholderText: chat.codeAnalysisSnapshotScope === "single_jar"
                                    ? "Automático: aplicação e versão do vr*.properties"
                                    : "ID automático; informe somente se quiser personalizar"
                                enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                                onAccepted: chat.previewConfiguredImport(text.trim())
                                background: Rectangle {
                                    radius: 8
                                    color: Theme.palette.codeSurface
                                    border.width: releaseIdField.activeFocus ? 2 : 1
                                    border.color: releaseIdField.activeFocus ? Theme.palette.focus : Theme.palette.border
                                }
                            }

                            VrButton {
                                objectName: "vrUltraAddReleaseButton"
                                text: chat.releaseSnapshotRunning ? "Detectando…" : "Preparar prévia"
                                variant: "primary"
                                implicitHeight: 34
                                enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                                    && (chat.codeAnalysisSnapshotScope !== "single_jar" || chat.codeAnalysisSingleJarPath.length > 0)
                                onClicked: chat.previewConfiguredImport(releaseIdField.text.trim())
                            }
                        }
                    }

                    Text {
                        objectName: "vrUltraReleaseSnapshotStatus"
                        Layout.fillWidth: true
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        Layout.topMargin: 4
                        Layout.bottomMargin: 8
                        visible: text.length > 0
                        text: chat.releaseSnapshotStatus
                        color: (text.indexOf("Não foi possível") === 0 || text.indexOf("não encontrada") !== -1 || text.indexOf("não encontrado") !== -1 || text.indexOf("não é um JAR") !== -1 || text.indexOf("mudaram após a prévia") !== -1 || text.indexOf("Erro") === 0) ? Theme.palette.warning : Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Breadcrumb navigation
            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: 42
                radius: 14
                color: Theme.palette.background
                border.width: 1
                border.color: Theme.palette.border
                visible: root.navigationLevel > 0

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 8

                    VrButton {
                        text: root.width < 600 ? "Aplicativos" : "Catálogo de Aplicativos"
                        variant: "ghost"
                        implicitHeight: 28
                        onClicked: root.navigationLevel = 0
                    }

                    Text {
                        text: "›"
                        color: Theme.palette.mutedText
                        font.pixelSize: Theme.fontSize(14)
                    }

                    Text {
                        text: root.activeAppId ? (root.activeAppId.toUpperCase()) : ""
                        color: root.navigationLevel === 1 ? Theme.palette.brandOrange : Theme.palette.headingText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        font.weight: Font.DemiBold
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            enabled: root.navigationLevel > 1
                            onClicked: root.navigationLevel = 1
                        }
                    }

                    Text {
                        visible: root.navigationLevel >= 2
                        text: "›"
                        color: Theme.palette.mutedText
                        font.pixelSize: Theme.fontSize(14)
                    }

                    Text {
                        visible: root.navigationLevel >= 2
                        text: "Versão: " + root.activeVersion
                        color: Theme.palette.brandOrange
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        font.weight: Font.DemiBold
                    }

                    Item {
                        Layout.fillWidth: true
                    }
                }
            }

            // LEVEL 0: Applications Overview
            ColumnLayout {
                objectName: "appsCatalogView"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 16
                visible: root.navigationLevel === 0

                Text {
                    text: "Aplicativos detectados"
                    Layout.leftMargin: 16
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: chat.applicationsCatalogLoading && chat.applicationsCatalog.length > 0
                    spacing: 8
                    VrProgressBar {
                        Layout.fillWidth: true
                        barHeight: 3
                        indeterminate: true
                        accentColor: Theme.palette.brandOrange
                    }
                    Text {
                        text: "Atualizando catálogo…"
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                    }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    // Empty and error are mutually exclusive: the empty hint
                    // only shows when there is no catalog error. While the
                    // first load is still running it reads as loading state.
                    visible: (chat.applicationsCatalogLoading || chat.applicationsCatalogLoaded) && chat.applicationsCatalog.length === 0 && chat.applicationsCatalogError.length === 0
                    text: chat.applicationsCatalogLoading
                        ? "Carregando catálogo de aplicativos…"
                        : "Nenhum aplicativo catalogado ainda. Importe um pacote VR ou JAR avulso acima."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                }

                VrAppSelector {
                    id: appSelector
                    objectName: "appSelector"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    visible: chat.applicationsCatalog.length > 0
                    model: chat.applicationsCatalog
                    activeAppId: root.activeAppId
                    onApplicationSelected: function(appId) {
                        chat.selectApplication(appId);
                        root.activeAppId = appId;
                        root.navigationLevel = 1;
                    }
                    onBatchDecompileRequested: function(appIds) {
                        chat.startBatchAppsProcessing(appIds);
                    }
                }

                // Batch Decompilation Action Card (Visible when apps are selected)
                Rectangle {
                    objectName: "appsBatchActionCard"
                    Layout.fillWidth: true
                    implicitHeight: 52
                    radius: 14
                    color: Qt.rgba(1.0, 0.45, 0.0, 0.08)
                    border.width: 1
                    border.color: Theme.palette.brandOrange
                    visible: appSelector.selectedAppIds && appSelector.selectedAppIds.length > 0 && !chat.codeProcessingRunning

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 12

                        VrLineIcon {
                            Layout.preferredWidth: 18
                            Layout.preferredHeight: 18
                            kind: "play"
                            foreground: Theme.palette.brandOrange
                        }

                        Text {
                            text: (appSelector.selectedAppIds ? appSelector.selectedAppIds.length : 0) + " aplicativo(s) / JAR(s) selecionado(s) para descompilar em lote"
                            color: Theme.palette.headingText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.Medium
                            Layout.fillWidth: true
                        }

                        VrButton {
                            objectName: "batchDecompileSettingsButton"
                            text: "Configurações Globais"
                            variant: "secondary"
                            implicitHeight: 30
                            onClicked: globalDecompileConfigDialog.open()
                        }

                        VrButton {
                            text: "Limpar seleção"
                            variant: "ghost"
                            implicitHeight: 30
                            onClicked: appSelector.clearSelection()
                        }

                        VrButton {
                            objectName: "startBatchAppsProcessingButton"
                            text: "Iniciar Descompilação em Lote (" + (appSelector.selectedAppIds ? appSelector.selectedAppIds.length : 0) + ")"
                            variant: "primary"
                            implicitHeight: 30
                            onClicked: {
                                chat.startBatchAppsProcessing(appSelector.selectedAppIds);
                            }
                        }
                    }
                }

                // Live Batch Processing Status Card (Visible when code processing is running)
                Rectangle {
                    objectName: "appsBatchProcessingStatusCard"
                    Layout.fillWidth: true
                    implicitHeight: liveBatchLayout.implicitHeight + 24
                    radius: 14
                    color: Theme.palette.codeSurface
                    border.width: 1
                    border.color: Theme.palette.brandOrange
                    visible: chat.codeProcessingRunning

                    ColumnLayout {
                        id: liveBatchLayout
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Text {
                                text: "Descompilação e Indexação em Andamento..."
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                            }

                            Text {
                                text: Number(chat.codeProcessingProgress).toFixed(0) + "% · " +
                                      chat.codeProcessingCoveredJars + "/" + chat.codeProcessingTotalJars + " JARs"
                                color: Theme.palette.brandOrange
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                            }

                            VrButton {
                                text: "Pausar"
                                variant: "secondary"
                                implicitHeight: 26
                                onClicked: chat.pauseCodeProcessing()
                            }

                            VrButton {
                                text: chat.codeProcessingCancelRequested ? "Cancelando..." : "Cancelar"
                                variant: "secondary"
                                implicitHeight: 26
                                enabled: !chat.codeProcessingCancelRequested
                                onClicked: chat.cancelCodeProcessing()
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: chat.codeProcessingStatus
                            color: Theme.palette.subtleText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeMicro
                            elide: Text.ElideRight
                        }

                        VrProgressBar {
                            Layout.fillWidth: true
                            barHeight: 6
                            accentColor: Theme.palette.brandOrange
                            from: 0
                            to: 100
                            value: Number(chat.codeProcessingProgress) || 0
                            indeterminate: chat.codeProcessingRunning && (!chat.codeProcessingProgress || chat.codeProcessingProgress === 0)
                        }
                    }
                }


                // Packages List Section
                Text {
                    text: "Pacotes de origem importados"
                    Layout.leftMargin: 16
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    visible: chat.packagesCatalog.length === 0
                    text: "Nenhum pacote importado."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                }

                Repeater {
                    model: chat.packagesCatalog
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: pkgCardLayout.implicitHeight + 20
                        radius: 14
                        color: Theme.palette.background
                        border.width: 1
                        border.color: Theme.palette.border

                        RowLayout {
                            id: pkgCardLayout
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 10

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 2

                                Text {
                                    text: modelData.name || modelData.package_id
                                    color: Theme.palette.headingText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(13)
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: "Importado em: " + (modelData.imported_at || "—") +
                                          " · Composição: " + (modelData.composition ? modelData.composition.length : 0) + " aplicativos"
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                }
                            }

                            RowLayout {
                                spacing: 6

                                VrButton {
                                    text: "Renomear"
                                    variant: "secondary"
                                    implicitHeight: 28
                                    onClicked: {
                                        root.pendingRenamePackageId = modelData.package_id;
                                        root.pendingRenamePackageName = modelData.name || modelData.package_id;
                                        renamePackageInput.text = root.pendingRenamePackageName;
                                        renamePackageDialog.open();
                                    }
                                }

                                VrButton {
                                    text: "Excluir JARs Originais"
                                    variant: "ghost"
                                    implicitHeight: 28
                                    onClicked: {
                                        root.pendingDeleteJarsPackageId = modelData.package_id;
                                        root.pendingDeleteJarsPackageName = modelData.name || modelData.package_id;
                                        deleteJarsConfirmDialog.open();
                                    }
                                }

                                VrButton {
                                    objectName: "vrUltraRemoveReleaseButton"
                                    text: "Remover / Desvincular"
                                    variant: "danger"
                                    implicitHeight: 28
                                    onClicked: {
                                        root.pendingUnlinkPackageId = modelData.package_id;
                                        root.pendingUnlinkPackageName = modelData.name || modelData.package_id;
                                        unlinkDeleteDataCheckBox.checked = false;
                                        unlinkConfirmDialog.open();
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // LEVEL 1: Versions of Selected App
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 16
                visible: root.navigationLevel === 1

                Text {
                    text: "Histórico de versões: " + (root.activeAppId ? root.activeAppId.toUpperCase() : "")
                    Layout.leftMargin: 16
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }

                // Versions Repeater
                Repeater {
                    model: chat.appVersions
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: verCardLayout.implicitHeight + 20
                        radius: 14
                        color: Theme.palette.background
                        border.width: 1
                        border.color: Theme.palette.border

                        RowLayout {
                            id: verCardLayout
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 12

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 4

                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 8

                                    Text {
                                        text: "Versão " + modelData.version
                                        color: Theme.palette.headingText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(14)
                                        font.weight: Font.DemiBold
                                    }

                                    Rectangle {
                                        visible: modelData.manualOverride
                                        implicitWidth: manualTag.implicitWidth + 8
                                        implicitHeight: 18
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: 1
                                        border.color: Theme.palette.chatBorder

                                        Text {
                                            id: manualTag
                                            anchors.centerIn: parent
                                            text: "Identificação manual"
                                            color: Theme.palette.subtleText
                                            font.pixelSize: Theme.fontSizeMicro
                                        }
                                    }

                                    Rectangle {
                                        implicitWidth: statusText.implicitWidth + 10
                                        implicitHeight: 20
                                        radius: Theme.radiusSmall
                                        color: modelData.indexState === "ready" ? Qt.rgba(0.2, 0.8, 0.2, 0.15) :
                                               (modelData.indexState === "failed" ? Qt.rgba(0.9, 0.2, 0.2, 0.15) : Qt.rgba(1.0, 0.6, 0.0, 0.15))
                                        border.width: 1
                                        border.color: modelData.indexState === "ready" ? Qt.rgba(0.2, 0.8, 0.2, 0.4) :
                                                      (modelData.indexState === "failed" ? Qt.rgba(0.9, 0.2, 0.2, 0.4) : Theme.palette.warning)

                                        Text {
                                            id: statusText
                                            anchors.centerIn: parent
                                            text: modelData.indexState === "ready" ? "Indexado" :
                                                  (modelData.indexState === "failed" ? "Falha" : "Pendente")
                                            color: modelData.indexState === "ready" ? Qt.rgba(0.1, 0.7, 0.1, 1.0) :
                                                   (modelData.indexState === "failed" ? Qt.rgba(0.9, 0.2, 0.2, 1.0) : Theme.palette.warning)
                                            font.pixelSize: Theme.fontSizeMicro
                                            font.weight: Theme.weightMedium
                                        }
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: "Classes: " + modelData.indexedClasses + " / " + modelData.classCount +
                                          " · Variantes: " + modelData.variantCount +
                                          " · Origens registradas: " + modelData.originCount
                                    color: Theme.palette.subtleText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                }
                            }

                            VrButton {
                                text: "Detalhes e Código"
                                variant: "primary"
                                implicitHeight: 32
                                onClicked: {
                                    chat.selectAppVersion(modelData.version);
                                    root.activeVersion = modelData.version;
                                    root.versionSubTab = 0;
                                    root.navigationLevel = 2;
                                }
                            }
                        }
                    }
                }
            }

            // LEVEL 2: Version Details & Actions
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 14
                visible: root.navigationLevel === 2

                VrComboBox {
                    objectName: "appVariantPicker"
                    Layout.fillWidth: true
                    model: [{"variant_id": "", "label": "Selecione a variante (SHA-256)"}].concat(
                        chat.appVariants.map(function(v) { return {variant_id: v.variant_id, label: v.sha256}; }))
                    textRole: "label"
                    currentIndex: {
                        for (var i = 0; i < model.length; i++)
                            if (model[i].variant_id === chat.selectedAppVariantId) return i;
                        return 0;
                    }
                    onActivated: index => chat.selectAppVariant(model[index].variant_id)
                }

                VrComboBox {
                    objectName: "appOriginPicker"
                    Layout.fillWidth: true
                    model: [{package_id: "", package_name: "Selecione a origem e suas dependências"}].concat(chat.selectedVersionDetails.origin_packages || [])
                    textRole: "package_name"
                    currentIndex: {
                        for (var i = 0; i < model.length; i++)
                            if (model[i].package_id === chat.selectedAppOriginId) return i;
                        return 0;
                    }
                    onActivated: index => chat.selectAppOrigin(model[index].package_id)
                }

                VrButton {
                    objectName: "useApplicationInUltra"
                    text: "Usar no Ultra"
                    variant: "primary"
                    enabled: !!chat.selectedAppVariantId && !!chat.selectedAppOriginId
                    onClicked: {
                        if (chat.addSelectedApplicationContext()) root.ultraContextAdded = true
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: root.ultraContextAdded
                    text: "Contexto atualizado. Ative a análise de código na aba VR Ultra. Outros aplicativos selecionados são mantidos."
                    color: Theme.palette.mutedText
                    wrapMode: Text.WordWrap
                }

                // Sub-tab Navigation
                GridLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    columns: root.width < 800 ? 1 : 4
                    rowSpacing: 8
                    columnSpacing: 8

                    VrButton {
                        text: "Detalhes e Variantes"
                        variant: root.versionSubTab === 0 ? "primary" : "secondary"
                        implicitHeight: 32
                        onClicked: root.versionSubTab = 0
                    }

                    VrButton {
                        text: "Descompilação e Índice"
                        variant: root.versionSubTab === 1 ? "primary" : "secondary"
                        implicitHeight: 32
                        onClicked: root.versionSubTab = 1
                    }

                    VrButton {
                        text: "Comparação de Versões"
                        variant: root.versionSubTab === 2 ? "primary" : "secondary"
                        implicitHeight: 32
                        onClicked: root.versionSubTab = 2
                    }

                    VrButton {
                        text: "Pacotes de Origem"
                        variant: root.versionSubTab === 3 ? "primary" : "secondary"
                        implicitHeight: 32
                        onClicked: root.versionSubTab = 3
                    }
                    VrButton {
                        text: "Código"
                        variant: root.versionSubTab === 4 ? "primary" : "secondary"
                        onClicked: {
                            root.versionSubTab = 4
                            chat.loadApplicationSources("", 0, "")
                        }
                    }
                }

                // Sub-Tab 0: Details & Variants
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 12
                    visible: root.versionSubTab === 0

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.width < 800 ? 1 : 2
                        VrTextField {
                            id: correctedVersion
                            Layout.fillWidth: true
                            placeholderText: "Informar ou corrigir versão desta variante"
                        }
                        VrButton {
                            text: "Salvar versão da variante"
                            enabled: !!chat.selectedAppVariantId && correctedVersion.text.trim().length > 0
                            onClicked: {
                                if (chat.overrideVariantVersion(chat.selectedAppId, chat.selectedAppVersion, chat.selectedAppVariantId, correctedVersion.text.trim())) {
                                    root.activeVersion = correctedVersion.text.trim()
                                    correctedVersion.text = ""
                                }
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: detailsCardLayout.implicitHeight + 24
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        ColumnLayout {
                            id: detailsCardLayout
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8

                            Text {
                                text: "Metadados da Versão"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(14)
                                font.weight: Font.DemiBold
                            }

                            Text {
                                text: "Aplicativo: " + (root.activeAppId ? root.activeAppId.toUpperCase() : "")
                                color: Theme.palette.text
                                font.pixelSize: Theme.fontSize(12)
                            }

                            Text {
                                text: "Versão: " + root.activeVersion
                                color: Theme.palette.text
                                font.pixelSize: Theme.fontSize(12)
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                wrapMode: Text.WrapAnywhere
                                text: "Variante selecionada (SHA-256): " + (chat.selectedAppVariantId || "—")
                                color: Theme.palette.text
                                font.pixelSize: Theme.fontSize(12)
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                wrapMode: Text.WrapAnywhere
                                text: "Caminho relativo: " + (chat.selectedVersionDetails.relative_path || "—")
                                color: Theme.palette.subtleText
                                font.pixelSize: Theme.fontSize(12)
                            }

                            Text {
                                text: "Classe principal do manifesto: " + (chat.selectedVersionDetails.manifest_main_class || "Não declarada")
                                color: Theme.palette.subtleText
                                font.pixelSize: Theme.fontSize(12)
                            }
                        }
                    }
                }

                // Sub-Tab 1: Decompilation & Indexing (Contains all Processing & Hardware options)
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 12
                    visible: root.versionSubTab === 1

                    Rectangle {
                        objectName: "vrUltraCodeProcessingCard"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: decompCardLayout.implicitHeight + 24
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        ColumnLayout {
                            id: decompCardLayout
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 10

                            Text {
                                text: "Status de Processamento Local"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(14)
                                font.weight: Font.DemiBold
                            }

                            Text {
                                objectName: "vrUltraCodeProcessingHardwareSummary"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: chat.codeProcessingHardwareSummary || "Modo paralelo automático"
                                color: Theme.palette.mutedText
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.Wrap
                            }

                            Text {
                                objectName: "appProcessingStatus"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Origem da tarefa: " + (chat.codeAnalysisRelease || "—") + "\n" + chat.codeProcessingStatus
                                color: Theme.palette.text
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.Wrap
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                columns: root.width < 800 ? 1 : 5
                                rowSpacing: 10
                                columnSpacing: 10

                                Text {
                                    objectName: "vrUltraCodeProcessingProgressLabel"
                                    text: Number(chat.codeProcessingProgress).toFixed(
                                        chat.codeProcessingProgress >= 100 ? 0 : 1
                                    ) + "% · "
                                        + chat.codeProcessingCoveredJars + "/"
                                        + chat.codeProcessingTotalJars + " JARs"
                                    color: Theme.palette.text
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: Font.Medium
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                }

                                VrButton {
                                    objectName: "vrUltraStartCodeProcessing"
                                    text: chat.codeProcessingRunning ? "Processando…" : "Iniciar processamento"
                                    variant: "primary"
                                    implicitHeight: 30
                                    enabled: !chat.codeProcessingRunning && chat.selectedAppVariantId.length > 0 && chat.selectedAppOriginId.length > 0
                                    onClicked: chat.startVariantProcessing(root.activeAppId, root.activeVersion, chat.selectedAppVariantId)
                                }

                                VrButton {
                                    objectName: "vrUltraPauseCodeProcessing"
                                    text: "Pausar"
                                    variant: "secondary"
                                    implicitHeight: 30
                                    enabled: chat.codeProcessingRunning
                                    onClicked: chat.pauseCodeProcessing()
                                }

                                VrButton {
                                    objectName: "vrUltraCancelCodeProcessing"
                                    text: chat.codeProcessingCancelRequested ? "Cancelando…" : "Cancelar"
                                    variant: "secondary"
                                    implicitHeight: 30
                                    enabled: (chat.codeProcessingRunning || chat.codeProcessingCanCancel) && !chat.codeProcessingCancelRequested
                                    onClicked: chat.cancelCodeProcessing()
                                }

                                VrButton {
                                    objectName: "vrUltraRetryCodeProcessing"
                                    text: "Repetir"
                                    variant: "secondary"
                                    implicitHeight: 30
                                    enabled: chat.codeProcessingCanRetry && !chat.codeProcessingRunning
                                        && !!chat.selectedAppVariantId && chat.selectedAppOriginId === chat.codeAnalysisRelease
                                    onClicked: chat.retryCodeProcessing()
                                }
                            }

                            VrProgressBar {
                                objectName: "vrUltraCodeProcessingProgress"
                                Layout.fillWidth: true
                                barHeight: 6
                                accentColor: Theme.palette.brandOrange
                                from: 0
                                to: 100
                                value: chat.codeProcessingProgress
                                indeterminate: chat.codeProcessingRunning && chat.codeProcessingProgress === 0
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                columns: root.width < 800 ? 1 : 3
                                rowSpacing: 12
                                columnSpacing: 12

                                Text {
                                    objectName: "vrUltraCodeProcessingCurrentBatch"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    wrapMode: Text.WrapAnywhere
                                    text: chat.codeProcessingCurrentJar ? ("JAR atual: " + chat.codeProcessingCurrentJar) : ""
                                    color: Theme.palette.mutedText
                                    font.pixelSize: Theme.fontSizeMicro
                                }

                                Text {
                                    objectName: "vrUltraCodeProcessingTelemetry"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    wrapMode: Text.Wrap
                                    text: chat.codeProcessingTelemetrySummary
                                    color: Theme.palette.subtleText
                                    font.pixelSize: Theme.fontSizeMicro
                                }

                                Text {
                                    objectName: "vrUltraCodeProcessingEta"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    wrapMode: Text.Wrap
                                    text: chat.codeProcessingEtaSummary
                                    color: Theme.palette.subtleText
                                    font.pixelSize: Theme.fontSizeMicro
                                }
                            }

                            // Sliders and hardware limits
                            GridLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                columns: root.width < 600 ? 1 : 2
                                rowSpacing: 8
                                columnSpacing: 12

                                Text {
                                    text: "Memória Máxima da JVM"
                                    color: Theme.palette.text
                                    font.pixelSize: Theme.fontSize(12)
                                }
                                VrComboBox {
                                    id: heapPicker
                                    objectName: "vrUltraCodeProcessingHeapPicker"
                                    Layout.fillWidth: true
                                    model: chat.codeProcessingHeapOptions
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < chat.codeProcessingHeapOptions.length; ++i) {
                                            if (chat.codeProcessingHeapOptions[i].value === chat.codeProcessingMaxHeapMb) return i;
                                        }
                                        return 0;
                                    }
                                    onActivated: index => chat.setCodeProcessingMaxHeapMb(chat.codeProcessingHeapOptions[index].value)
                                }

                                Text {
                                    text: "Timeout do Lote"
                                    color: Theme.palette.text
                                    font.pixelSize: Theme.fontSize(12)
                                }
                                VrComboBox {
                                    id: timeoutPicker
                                    objectName: "vrUltraCodeProcessingTimeoutPicker"
                                    Layout.fillWidth: true
                                    model: chat.codeProcessingTimeoutOptions
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < chat.codeProcessingTimeoutOptions.length; ++i) {
                                            if (chat.codeProcessingTimeoutOptions[i].value === chat.codeProcessingTimeoutSeconds) return i;
                                        }
                                        return 0;
                                    }
                                    onActivated: index => chat.setCodeProcessingTimeoutSeconds(chat.codeProcessingTimeoutOptions[index].value)
                                }

                                Text {
                                    text: "Núcleos de CPU"
                                    color: Theme.palette.text
                                    font.pixelSize: Theme.fontSize(12)
                                }
                                VrComboBox {
                                    id: cpuPicker
                                    objectName: "vrUltraCodeProcessingCpuPicker"
                                    Layout.fillWidth: true
                                    model: chat.codeProcessingCpuCoreOptions
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < chat.codeProcessingCpuCoreOptions.length; ++i) {
                                            if (chat.codeProcessingCpuCoreOptions[i].value === chat.codeProcessingMaxCpuCores) return i;
                                        }
                                        return 0;
                                    }
                                    onActivated: index => chat.setCodeProcessingMaxCpuCores(chat.codeProcessingCpuCoreOptions[index].value)
                                }

                                Text {
                                    text: "Multiplicador de Disco"
                                    color: Theme.palette.text
                                    font.pixelSize: Theme.fontSize(12)
                                }
                                VrComboBox {
                                    id: diskPicker
                                    objectName: "vrUltraCodeProcessingDiskPicker"
                                    Layout.fillWidth: true
                                    model: chat.codeProcessingDiskMultiplierOptions
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < chat.codeProcessingDiskMultiplierOptions.length; ++i) {
                                            if (chat.codeProcessingDiskMultiplierOptions[i].value === chat.codeProcessingDiskMultiplier) return i;
                                        }
                                        return 0;
                                    }
                                    onActivated: index => chat.setCodeProcessingDiskMultiplier(chat.codeProcessingDiskMultiplierOptions[index].value)
                                }

                                Text {
                                    text: "Janela de Processamento"
                                    color: Theme.palette.text
                                    font.pixelSize: Theme.fontSize(12)
                                }
                                VrComboBox {
                                    id: windowPicker
                                    objectName: "vrUltraCodeProcessingWindowPicker"
                                    Layout.fillWidth: true
                                    model: chat.codeProcessingWindowOptions
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < chat.codeProcessingWindowOptions.length; ++i) {
                                            if (chat.codeProcessingWindowOptions[i].value === chat.codeProcessingWindow) return i;
                                        }
                                        return 0;
                                    }
                                    onActivated: index => chat.setCodeProcessingWindow(chat.codeProcessingWindowOptions[index].value)
                                }

                                Text {
                                    text: "Lote para repetir"
                                    color: Theme.palette.text
                                    font.pixelSize: Theme.fontSize(12)
                                }
                                VrComboBox {
                                    id: retryPicker
                                    objectName: "vrUltraCodeProcessingRetryPicker"
                                    Layout.fillWidth: true
                                    enabled: chat.codeProcessingCanRetry && !chat.codeProcessingRunning
                                    model: chat.codeProcessingAttentionBatches.length ? chat.codeProcessingAttentionBatches : [{label: "Nenhum lote com falha", batchId: ""}]
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < chat.codeProcessingAttentionBatches.length; i++)
                                            if (chat.codeProcessingAttentionBatches[i].batchId === chat.codeProcessingRetryBatch) return i;
                                        return 0;
                                    }
                                    onActivated: index => chat.setCodeProcessingRetryBatch(model[index].batchId)
                                }
                            }

                            // Orphan Cleanup & Storage Capacity
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 10

                                Text {
                                    objectName: "vrUltraCodeProcessingCapacity"
                                    wrapMode: Text.Wrap
                                    text: "Bancos compartilhados: " + (chat.codeProcessingCapacitySummary || "Integridade OK")
                                    color: Theme.palette.subtleText
                                    font.pixelSize: Theme.fontSizeMicro
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                }

                                VrButton {
                                    objectName: "vrUltraCleanCodeProcessingOrphans"
                                    text: "Limpar órfãos"
                                    variant: "ghost"
                                    implicitHeight: 28
                                    enabled: !chat.codeProcessingRunning
                                    onClicked: cleanOrphansDialog.open()
                                }
                            }
                        }
                    }
                }

                // Sub-Tab 2: Version Comparison
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 12
                    visible: root.versionSubTab === 2

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: compareCardLayout.implicitHeight + 24
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        ColumnLayout {
                            id: compareCardLayout
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 10

                            Text {
                                text: "Comparar Versão " + root.activeVersion + " com outra versão"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(14)
                                font.weight: Font.DemiBold
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                columns: root.width < 800 ? 1 : 3
                                rowSpacing: 10
                                columnSpacing: 10

                                Text {
                                    text: "Versão de destino:"
                                    color: Theme.palette.text
                                    font.pixelSize: Theme.fontSize(12)
                                }

                                VrComboBox {
                                    id: compareTargetCombo
                                    Layout.preferredWidth: 160
                                    implicitHeight: 32
                                    model: {
                                        var list = [];
                                        for (var i = 0; i < chat.appVersions.length; ++i) {
                                            if (chat.appVersions[i].version !== root.activeVersion) {
                                                list.push(chat.appVersions[i].version);
                                            }
                                        }
                                        return list;
                                    }
                                    onActivated: index => {
                                        if (index >= 0 && index < model.length) {
                                            root.compareTargetVersion = model[index];
                                        }
                                    }
                                }

                                VrButton {
                                    text: "Comparar bytecode"
                                    variant: "primary"
                                    implicitHeight: 32
                                    enabled: compareTargetCombo.currentText.length > 0 && chat.selectedAppVariantId.length > 0 && targetVariantCombo.currentIndex > 0 && chat.versionComparisonResult.state !== "running"
                                    onClicked: {
                                        var target = compareTargetCombo.currentText;
                                        chat.compareAppVersions(root.activeAppId, root.activeVersion, target, chat.selectedAppVariantId, targetVariantCombo.model[targetVariantCombo.currentIndex].variant_id);
                                    }
                                }
                            }

                            // Comparison Results
                            VrComboBox {
                                id: targetVariantCombo
                                objectName: "appCompareTargetVariant"
                                Layout.fillWidth: true
                                model: {
                                    var versions = chat.appVersions;
                                    var variants = chat.variantsForVersion(compareTargetCombo.currentText);
                                    return [{variant_id: "", label: "Selecione a variante de destino"}].concat(variants.map(function(v) { return {variant_id: v.variant_id, label: v.sha256}; }));
                                }
                                textRole: "label"
                                currentIndex: model.length === 2 ? 1 : 0
                            }
                            Text {
                                Layout.fillWidth: true
                                text: chat.versionComparisonResult.state === "running" ? "Comparando arquivos…" : (chat.versionComparisonResult.error || "")
                                visible: text.length > 0
                                color: Theme.palette.danger
                                wrapMode: Text.Wrap
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 8
                                visible: Boolean(chat.versionComparisonResult && chat.versionComparisonResult.summary)

                                Rectangle {
                                    visible: Boolean(chat.versionComparisonResult && chat.versionComparisonResult.pendingNote && chat.versionComparisonResult.pendingNote.length > 0)
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitHeight: pendingAlertLayout.implicitHeight + 16
                                    radius: Theme.radiusSmall
                                    color: Qt.rgba(0.9, 0.6, 0.0, 0.12)
                                    border.width: 1
                                    border.color: Theme.palette.warning

                                    RowLayout {
                                        id: pendingAlertLayout
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        spacing: 8

                                        VrLineIcon {
                                            width: 16
                                            height: 16
                                            kind: "browser"
                                            foreground: Theme.palette.warning
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            text: chat.versionComparisonResult.pendingNote || ""
                                            color: Theme.palette.warning
                                            font.pixelSize: Theme.fontSizeMicro
                                            wrapMode: Text.WordWrap
                                        }
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 8

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitHeight: 56
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: 1
                                        border.color: Theme.palette.chatBorder

                                        ColumnLayout {
                                            anchors.centerIn: parent
                                            spacing: 2
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: chat.versionComparisonResult.summary ? chat.versionComparisonResult.summary.added : 0
                                                color: Qt.rgba(0.1, 0.7, 0.1, 1.0)
                                                font.pixelSize: Theme.headingSize
                                                font.weight: Font.Bold
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: "Adicionadas"
                                                color: Theme.palette.subtleText
                                                font.pixelSize: Theme.fontSizeCaption
                                            }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitHeight: 56
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: 1
                                        border.color: Theme.palette.chatBorder

                                        ColumnLayout {
                                            anchors.centerIn: parent
                                            spacing: 2
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: chat.versionComparisonResult.summary ? chat.versionComparisonResult.summary.modified : 0
                                                color: Theme.palette.brandOrange
                                                font.pixelSize: Theme.headingSize
                                                font.weight: Font.Bold
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: "Modificadas"
                                                color: Theme.palette.subtleText
                                                font.pixelSize: Theme.fontSizeCaption
                                            }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitHeight: 56
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: 1
                                        border.color: Theme.palette.chatBorder

                                        ColumnLayout {
                                            anchors.centerIn: parent
                                            spacing: 2
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: chat.versionComparisonResult.summary ? chat.versionComparisonResult.summary.removed : 0
                                                color: Qt.rgba(0.9, 0.2, 0.2, 1.0)
                                                font.pixelSize: Theme.headingSize
                                                font.weight: Font.Bold
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: "Removidas"
                                                color: Theme.palette.subtleText
                                                font.pixelSize: Theme.fontSizeCaption
                                            }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitHeight: 56
                                        radius: Theme.radiusSmall
                                        color: Theme.palette.chatBackground
                                        border.width: 1
                                        border.color: Theme.palette.chatBorder

                                        ColumnLayout {
                                            anchors.centerIn: parent
                                            spacing: 2
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: chat.versionComparisonResult.summary ? chat.versionComparisonResult.summary.unchanged : 0
                                                color: Theme.palette.text
                                                font.pixelSize: Theme.headingSize
                                                font.weight: Font.Bold
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: "Inalteradas"
                                                color: Theme.palette.subtleText
                                                font.pixelSize: Theme.fontSizeCaption
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    visible: root.versionSubTab === 2
                    Repeater {
                        model: [
                            {label: "Adicionadas", values: chat.versionComparisonResult.addedClasses || []},
                            {label: "Removidas", values: chat.versionComparisonResult.removedClasses || []},
                            {label: "Modificadas", values: chat.versionComparisonResult.modifiedClasses || []},
                            {label: "Verificação pendente", values: chat.versionComparisonResult.pendingVerificationClasses || []}
                        ]
                        delegate: Text {
                            required property var modelData
                            Layout.fillWidth: true
                            visible: modelData.values.length > 0
                            text: modelData.label + ":\n" + modelData.values.join("\n")
                            textFormat: Text.PlainText
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: root.versionSubTab === 4
                    Text {
                        Layout.fillWidth: true
                        text: chat.applicationSources.context_label || "Selecione uma variante e origem para consultar as classes indexadas."
                        color: Theme.palette.mutedText
                        wrapMode: Text.WrapAnywhere
                    }
                    VrTextField {
                        id: sourceQuery
                        objectName: "applicationSourceQuery"
                        Layout.fillWidth: true
                        placeholderText: "Filtrar pelo nome da classe"
                        onAccepted: chat.loadApplicationSources(text, 0, "")
                    }
                    VrButton {
                        text: "Buscar classes"
                        enabled: chat.applicationSources.state !== "running"
                        onClicked: chat.loadApplicationSources(sourceQuery.text, 0, "")
                    }
                    Text {
                        Layout.fillWidth: true
                        text: chat.applicationSources.state === "running" ? "Carregando…" : (chat.applicationSources.error || ((chat.applicationSources.sources || []).length ? "" : "Nenhuma classe encontrada. Confira o processamento ou ajuste o filtro."))
                        visible: text.length > 0
                        color: Theme.palette.mutedText
                        wrapMode: Text.WordWrap
                    }
                    VrComboBox {
                        id: sourcePicker
                        objectName: "applicationSourcePicker"
                        Layout.fillWidth: true
                        model: [{source_key: "", qualified_name: "Selecione a classe"}].concat(chat.applicationSources.sources || [])
                        textRole: "qualified_name"
                        currentIndex: {
                            for (var i = 0; i < model.length; i++)
                                if (model[i].source_key === chat.applicationSources.source_key) return i
                            return 0
                        }
                        onActivated: index => {
                            if (model[index].source_key) chat.loadApplicationSources(sourceQuery.text, chat.applicationSources.offset || 0, model[index].source_key)
                        }
                    }
                    RowLayout {
                        VrButton {
                            text: "Anteriores"
                            enabled: (chat.applicationSources.offset || 0) > 0 && chat.applicationSources.state !== "running"
                            onClicked: chat.loadApplicationSources(sourceQuery.text, Math.max(0, chat.applicationSources.offset - 100), "")
                        }
                        VrButton {
                            text: "Próximas"
                            enabled: !!chat.applicationSources.has_more && chat.applicationSources.state !== "running"
                            onClicked: chat.loadApplicationSources(sourceQuery.text, chat.applicationSources.offset + 100, "")
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: !!chat.applicationSources.truncated
                        text: "Exibindo os primeiros 200 mil caracteres da classe."
                        color: Theme.palette.warning
                        wrapMode: Text.WordWrap
                    }
                    TextArea {
                        objectName: "applicationSourceBody"
                        Layout.fillWidth: true
                        readOnly: true
                        selectByMouse: true
                        textFormat: TextEdit.PlainText
                        text: chat.applicationSources.body || ""
                        color: Theme.palette.text
                        font.family: "Consolas"
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: TextEdit.WrapAnywhere
                        background: Rectangle { color: Theme.palette.codeSurface; radius: Theme.radiusSmall }
                    }
                }

                // Sub-Tab 3: Origin Packages
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 12
                    visible: root.versionSubTab === 3

                    Text {
                        Layout.fillWidth: true
                        text: chat.selectedAppOriginId
                            ? "Origem selecionada: " + chat.selectedAppOriginId + "\nDistribuição: "
                                + (root.selectedDistribution.distribution_id || "—") + "\nBibliotecas catalogadas: "
                                + (root.selectedDistribution.dependencies || []).length
                            : "Selecione uma origem para consultar suas bibliotecas."
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        wrapMode: Text.WrapAnywhere
                    }
                    Repeater {
                        model: root.selectedDistribution.dependencies || []
                        delegate: Text {
                            required property var modelData
                            Layout.fillWidth: true
                            text: modelData.relative_path + "\nSHA-256: " + modelData.sha256
                            textFormat: Text.PlainText
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            wrapMode: Text.WrapAnywhere
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: originsCardLayout.implicitHeight + 24
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        ColumnLayout {
                            id: originsCardLayout
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8

                            Text {
                                text: "Pacotes que contêm esta versão"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(14)
                                font.weight: Font.DemiBold
                            }

                            Repeater {
                                model: chat.selectedVersionDetails.origin_packages || []
                                delegate: RowLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 8

                                    Text {
                                        text: "• " + (modelData.package_name || modelData.package_id) + " (Importado: " + (modelData.imported_at || "—") + ")"
                                        wrapMode: Text.Wrap
                                        color: Theme.palette.text
                                        font.pixelSize: Theme.fontSize(12)
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

    Dialog {
        id: cleanOrphansDialog
        objectName: "vrUltraCleanOrphansDialog"
        anchors.centerIn: parent
        width: Math.min(500, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Limpar artefatos órfãos?"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "Somente dados gerados sem referência ativa serão removidos. "
                    + "Bancos compartilhados, releases ativas e JARs de origem serão preservados."
                color: Theme.palette.headingText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                VrButton { text: "Cancelar"; onClicked: cleanOrphansDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton {
                    objectName: "vrUltraConfirmCleanOrphansButton"
                    text: "Limpar órfãos"
                    variant: "danger"
                    onClicked: {
                        cleanOrphansDialog.close()
                        chat.cleanCodeProcessingOrphans()
                    }
                }
            }
        }
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.warning
            radius: Theme.radiusSmall
        }
    }

    Dialog {
        id: unlinkConfirmDialog
        objectName: "vrUltraRemoveReleaseDialog"
        anchors.centerIn: parent
        width: Math.min(520, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Remover ou Desvincular Pacote"
        standardButtons: Dialog.NoButton
        onClosed: {
            root.pendingUnlinkPackageId = "";
            root.pendingUnlinkPackageName = "";
        }
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "Deseja remover o pacote '" + (root.pendingUnlinkPackageName || root.pendingUnlinkPackageId) + "' do catálogo de aplicativos?\nOs JARs de origem serão preservados."
                color: Theme.palette.headingText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
                wrapMode: Text.WordWrap
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: checkLayout.implicitHeight + 16
                radius: Theme.radiusSmall
                color: Theme.palette.codeSurface
                border.width: 1
                border.color: unlinkDeleteDataCheckBox.checked ? Theme.palette.danger : Theme.palette.chatBorder

                ColumnLayout {
                    id: checkLayout
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6

                    VrCheckBox {
                        id: unlinkDeleteDataCheckBox
                        Layout.fillWidth: true
                        text: "Excluir também índices e arquivos descompilados"
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 28
                        text: unlinkDeleteDataCheckBox.checked
                            ? "Atenção: Os fontes Java descompilados e os índices de busca do SQLite deste pacote serão permanentemente excluídos do disco."
                            : "Apenas desvincula o pacote do catálogo. Os arquivos descompilados e índices existentes são mantidos no disco."
                        color: unlinkDeleteDataCheckBox.checked ? Theme.palette.danger : Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        wrapMode: Text.WordWrap
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                VrButton { text: "Cancelar"; onClicked: unlinkConfirmDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton {
                    objectName: "vrUltraConfirmRemoveReleaseButton"
                    text: unlinkDeleteDataCheckBox.checked ? "Remover e Excluir Dados" : "Apenas Desvincular"
                    variant: "danger"
                    enabled: !chat.releaseSnapshotRunning
                    onClicked: {
                        var releaseId = root.pendingUnlinkPackageId;
                        var deleteData = unlinkDeleteDataCheckBox.checked;
                        unlinkConfirmDialog.close();
                        if (!chat.unlinkPackage(releaseId, deleteData)) {
                            chat.removeCodeAnalysisRelease(releaseId);
                        }
                    }
                }
            }
        }
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: unlinkDeleteDataCheckBox.checked ? Theme.palette.danger : Theme.palette.chatBorder
            radius: Theme.radiusSmall
        }
    }

    Dialog {
        id: renamePackageDialog
        objectName: "renamePackageDialog"
        anchors.centerIn: parent
        width: Math.min(480, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Renomear Pacote"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "Digite o novo nome para o pacote selecionado:"
                color: Theme.palette.headingText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
            }
            VrTextField {
                id: renamePackageInput
                Layout.fillWidth: true
                placeholderText: "Ex: Release ERP Março 2026"
            }
            RowLayout {
                Layout.fillWidth: true
                VrButton {
                    text: "Cancelar"
                    variant: "secondary"
                    onClicked: renamePackageDialog.close()
                }
                Item { Layout.fillWidth: true }
                VrButton {
                    text: "Salvar"
                    variant: "primary"
                    enabled: renamePackageInput.text.trim().length > 0
                    onClicked: {
                        var ok = chat.renamePackage(root.pendingRenamePackageId, renamePackageInput.text.trim());
                        renamePackageDialog.close();
                    }
                }
            }
        }
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: Theme.radiusSmall
        }
    }

    Dialog {
        id: deleteJarsConfirmDialog
        objectName: "deleteJarsConfirmDialog"
        anchors.centerIn: parent
        width: Math.min(520, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Excluir JARs Originais do Disco?"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "Esta ação excluirá os arquivos .jar originais do diretório de origem do pacote '" + root.pendingDeleteJarsPackageName + "'.\n\n"
                    + "O código já descompilado e o índice no VRStudio continuarão funcionando normalmente e preservados."
                color: Theme.palette.headingText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                VrButton {
                    text: "Cancelar"
                    onClicked: deleteJarsConfirmDialog.close()
                }
                Item { Layout.fillWidth: true }
                VrButton {
                    text: "Confirmar Exclusão"
                    variant: "danger"
                    onClicked: {
                        var pkgId = root.pendingDeleteJarsPackageId;
                        deleteJarsConfirmDialog.close();
                        chat.deleteSourceJars(pkgId);
                    }
                }
            }
        }
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.warning
            radius: Theme.radiusSmall
        }
    }

    Dialog {
        id: decompiledImportDialog
        objectName: "decompiledImportDialog"
        anchors.centerIn: parent
        width: Math.min(540, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Importar Código Descompilado"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.decompiledDetectionResult ? (
                    "Fontes detectados com sucesso!\n" +
                    "Aplicativos: " + (root.decompiledDetectionResult.applications ? root.decompiledDetectionResult.applications.length : 0) +
                    " · Total de arquivos Java: " + (root.decompiledDetectionResult.total_java_files || 0) + "\n" +
                    "Diretório: " + (root.decompiledDetectionResult.source_root || "")
                ) : ""
                color: Theme.palette.headingText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: "O código será indexado diretamente no VRStudio para buscas e análise sem necessitar de descompilador."
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                VrButton {
                    text: "Cancelar"
                    onClicked: decompiledImportDialog.close()
                }
                Item { Layout.fillWidth: true }
                VrButton {
                    text: "Importar e Indexar"
                    variant: "primary"
                    onClicked: {
                        var res = root.decompiledDetectionResult;
                        decompiledImportDialog.close();
                        if (res && res.source_root) {
                            chat.importDecompiledDirectory(res.source_root, res.suggested_release_id || "", res.suggested_name || "");
                        }
                    }
                }
            }
        }
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: Theme.radiusSmall
        }
    }

    Dialog {
        id: globalDecompileConfigDialog
        objectName: "globalDecompileConfigDialog"
        anchors.centerIn: parent
        width: Math.min(620, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Configurações Globais de Descompilação"
        standardButtons: Dialog.NoButton

        contentItem: ColumnLayout {
            spacing: Theme.spaceMd

            Text {
                Layout.fillWidth: true
                text: "Configurações globais de JVM, limites de tempo e paralelismo aplicados na descompilação e indexação em lote dos arquivos JAR."
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                wrapMode: Text.WordWrap
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: globalSummaryCol.implicitHeight + 16
                radius: Theme.radiusSmall
                color: Theme.palette.codeSurface
                border.width: 1
                border.color: Theme.palette.chatBorder

                ColumnLayout {
                    id: globalSummaryCol
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4

                    RowLayout {
                        spacing: 6
                        VrLineIcon {
                            Layout.preferredWidth: 14
                            Layout.preferredHeight: 14
                            kind: "settings"
                            foreground: Theme.palette.brandOrange
                        }
                        Text {
                            text: "Alocação do Processador e Memória"
                            color: Theme.palette.headingText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            font.weight: Font.DemiBold
                        }
                    }

                    Text {
                        objectName: "globalDecompileHardwareSummary"
                        Layout.fillWidth: true
                        text: chat.codeProcessingHardwareSummary || "Carregando perfil de hardware..."
                        color: Theme.palette.subtleText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        wrapMode: Text.WordWrap
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 12
                rowSpacing: 12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: "Memória Máxima da JVM"
                        color: Theme.palette.headingText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.Medium
                    }
                    VrComboBox {
                        id: globalHeapPicker
                        objectName: "globalDecompileHeapPicker"
                        Layout.fillWidth: true
                        model: chat.codeProcessingHeapOptions
                        textRole: "label"
                        valueRole: "value"
                        currentIndex: {
                            var v = chat.codeProcessingMaxHeapMb
                            for (var i = 0; i < (chat.codeProcessingHeapOptions || []).length; ++i) {
                                if (Number(chat.codeProcessingHeapOptions[i].value) === v) return i
                            }
                            return 0
                        }
                        onActivated: index => {
                            var item = (chat.codeProcessingHeapOptions || [])[index]
                            if (item) chat.setCodeProcessingMaxHeapMb(Number(item.value))
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: "Timeout do Lote"
                        color: Theme.palette.headingText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.Medium
                    }
                    VrComboBox {
                        id: globalTimeoutPicker
                        objectName: "globalDecompileTimeoutPicker"
                        Layout.fillWidth: true
                        model: chat.codeProcessingTimeoutOptions
                        textRole: "label"
                        valueRole: "value"
                        currentIndex: {
                            var v = chat.codeProcessingTimeoutSeconds
                            for (var i = 0; i < (chat.codeProcessingTimeoutOptions || []).length; ++i) {
                                if (Number(chat.codeProcessingTimeoutOptions[i].value) === v) return i
                            }
                            return 0
                        }
                        onActivated: index => {
                            var item = (chat.codeProcessingTimeoutOptions || [])[index]
                            if (item) chat.setCodeProcessingTimeoutSeconds(Number(item.value))
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: "Núcleos de CPU / Concorrência"
                        color: Theme.palette.headingText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.Medium
                    }
                    VrComboBox {
                        id: globalCpuPicker
                        objectName: "globalDecompileCpuPicker"
                        Layout.fillWidth: true
                        model: chat.codeProcessingCpuCoreOptions
                        textRole: "label"
                        valueRole: "value"
                        currentIndex: {
                            var v = chat.codeProcessingMaxCpuCores
                            for (var i = 0; i < (chat.codeProcessingCpuCoreOptions || []).length; ++i) {
                                if (Number(chat.codeProcessingCpuCoreOptions[i].value) === v) return i
                            }
                            return 0
                        }
                        onActivated: index => {
                            var item = (chat.codeProcessingCpuCoreOptions || [])[index]
                            if (item) chat.setCodeProcessingMaxCpuCores(Number(item.value))
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: "Multiplicador de Disco"
                        color: Theme.palette.headingText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.Medium
                    }
                    VrComboBox {
                        id: globalDiskPicker
                        objectName: "globalDecompileDiskPicker"
                        Layout.fillWidth: true
                        model: chat.codeProcessingDiskMultiplierOptions
                        textRole: "label"
                        valueRole: "value"
                        currentIndex: {
                            var v = chat.codeProcessingDiskMultiplier
                            for (var i = 0; i < (chat.codeProcessingDiskMultiplierOptions || []).length; ++i) {
                                if (Number(chat.codeProcessingDiskMultiplierOptions[i].value) === v) return i
                            }
                            return 0
                        }
                        onActivated: index => {
                            var item = (chat.codeProcessingDiskMultiplierOptions || [])[index]
                            if (item) chat.setCodeProcessingDiskMultiplier(Number(item.value))
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Text {
                    text: "Janela de Processamento"
                    color: Theme.palette.headingText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: Font.Medium
                }
                VrComboBox {
                    id: globalWindowPicker
                    objectName: "globalDecompileWindowPicker"
                    Layout.fillWidth: true
                    model: chat.codeProcessingWindowOptions
                    textRole: "label"
                    valueRole: "value"
                    currentIndex: {
                        var v = chat.codeProcessingWindow
                        for (var i = 0; i < (chat.codeProcessingWindowOptions || []).length; ++i) {
                            if (String(chat.codeProcessingWindowOptions[i].value) === v) return i
                        }
                        return 0
                    }
                    onActivated: index => {
                        var item = (chat.codeProcessingWindowOptions || [])[index]
                        if (item) chat.setCodeProcessingWindow(String(item.value))
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                VrButton {
                    objectName: "globalDecompileCloseButton"
                    text: "Concluir"
                    variant: "primary"
                    onClicked: globalDecompileConfigDialog.close()
                }
            }
        }

        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: Theme.radiusPopup
        }
    }
}
