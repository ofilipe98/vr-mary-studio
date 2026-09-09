import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

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
    property string pendingReleaseRemoval: ""
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

        ColumnLayout {
            width: appsScroll.availableWidth
            spacing: 16

            // Header Section
            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 12

                Rectangle {
                    Layout.preferredWidth: 36
                    Layout.preferredHeight: 36
                    radius: Theme.radiusSmall
                    color: Theme.palette.codeSurface
                    border.width: 1
                    border.color: Theme.palette.chatBorder

                    VrLineIcon {
                        anchors.centerIn: parent
                        width: 18
                        height: 18
                        kind: "files"
                        foreground: Theme.palette.brandOrange
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Aplicativos e versões"
                        color: Theme.palette.headingText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(16)
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Catálogo de aplicativos VR, histórico de versões, pacotes de origem, descompilação e comparação de bytecode."
                        color: Theme.palette.subtleText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Top Action Toolbar (Importation & Directory options)
            Text {
                Layout.fillWidth: true
                text: chat.applicationsCatalogError
                visible: text.length > 0
                color: Theme.palette.danger
                wrapMode: Text.Wrap
            }
            ColumnLayout {
                objectName: "applicationImportPreview"
                Layout.fillWidth: true
                visible: !!chat.applicationImportPreview.state
                Text {
                    Layout.fillWidth: true
                    text: chat.applicationImportPreview.state === "running" ? "Preparando prévia…" : (chat.applicationImportPreview.error || "Prévia da importação — confira aplicativos, versões e variantes")
                    color: Theme.palette.headingText
                    wrapMode: Text.WordWrap
                }
                Repeater {
                    model: chat.applicationImportPreview.rows || []
                    delegate: Text {
                        required property var modelData
                        Layout.fillWidth: true
                        text: modelData.application + " · " + modelData.version + " · " + modelData.status + "\n" + modelData.relative_path + " · SHA-256 " + modelData.sha256
                        textFormat: Text.PlainText
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        wrapMode: Text.WrapAnywhere
                    }
                }
                RowLayout {
                    VrButton {
                        objectName: "confirmApplicationImport"
                        text: "Confirmar importação"
                        enabled: chat.applicationImportPreview.state === "ready"
                        onClicked: chat.confirmApplicationImport()
                    }
                    VrButton {
                        text: "Cancelar"
                        variant: "secondary"
                        onClicked: chat.cancelApplicationImport()
                    }
                }
            }
            Rectangle {
                objectName: "appsImportCard"
                visible: root.navigationLevel === 0
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: importActionsLayout.implicitHeight + 24
                radius: Theme.radiusSmall
                color: Theme.palette.codeSurface
                border.width: 1
                border.color: Theme.palette.chatBorder

                ColumnLayout {
                    id: importActionsLayout
                    objectName: "vrUltraJarDirectoryCard"
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    GridLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        columns: root.width < 800 ? 1 : 3
                        rowSpacing: 8
                        columnSpacing: 8

                        Text {
                            text: "Importação de Pacotes e JARs"
                            color: Theme.palette.headingText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                        }

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
                            text: "Atualizar"
                            variant: "ghost"
                            implicitHeight: 32
                            onClicked: chat.refreshApplicationsCatalog()
                        }
                    }

                    // Directory picker and scope
                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Diretório padrão dos JARs"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Pasta raiz onde as compilações e bibliotecas JAR estão armazenadas."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            id: jarSourcePicker
                            objectName: "vrUltraJarDirectoryPicker"
                            Layout.preferredWidth: 260
                            implicitHeight: 38
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
                        }
                    }

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Escopo da análise"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Indexar todos os componentes da release ou isolar um único JAR."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            id: jarScopePicker
                            objectName: "vrUltraJarScopePicker"
                            Layout.preferredWidth: 260
                            implicitHeight: 38
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
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
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

                    RowLayout {
                        objectName: "vrUltraSingleJarRow"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: chat.codeAnalysisSnapshotScope === "single_jar"
                        spacing: 8

                        VrTextField {
                            objectName: "vrUltraSingleJarPath"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: 38
                            readOnly: true
                            text: chat.codeAnalysisSingleJarPath
                            placeholderText: "Nenhum JAR selecionado"
                        }

                        VrButton {
                            objectName: "vrUltraSelectSingleJarButton"
                            text: "Escolher JAR…"
                            implicitHeight: 34
                            enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                            onClicked: chat.selectCodeAnalysisSingleJar()
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 8

                        VrTextField {
                            id: releaseIdField
                            objectName: "vrUltraReleaseIdField"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: 38
                            placeholderText: chat.codeAnalysisSnapshotScope === "single_jar"
                                ? "Automático: aplicação e versão do vr*.properties"
                                : "ID automático; informe somente se quiser personalizar"
                            enabled: !chat.releaseSnapshotRunning && !chat.codeProcessingRunning
                            onAccepted: chat.previewConfiguredImport(text.trim())
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

                    Text {
                        objectName: "vrUltraReleaseSnapshotStatus"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: text.length > 0
                        text: chat.releaseSnapshotStatus
                        color: text.indexOf("Não foi possível") === 0 ? Theme.palette.warning : Theme.palette.mutedText
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
                implicitHeight: 38
                radius: Theme.radiusSmall
                color: Theme.palette.chatBackground
                border.width: 1
                border.color: Theme.palette.chatBorder
                visible: root.navigationLevel > 0

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 8

                    VrButton {
                        text: root.width < 600 ? "← Aplicativos" : "← Catálogo de Aplicativos"
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

                VrProviderSection {
                    Layout.fillWidth: true
                    title: "Aplicativos Detectados"
                }

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    visible: chat.applicationsCatalog.length === 0
                    text: "Nenhum aplicativo catalogado ainda. Importe um pacote VR ou JAR avulso acima."
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                }

                Repeater {
                    model: chat.applicationsCatalog
                    delegate: Rectangle {
                        id: appCard
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: appCardLayout.implicitHeight + 20
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        RowLayout {
                            id: appCardLayout
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 12

                            Rectangle {
                                Layout.preferredWidth: 32
                                Layout.preferredHeight: 32
                                radius: Theme.radiusSmall
                                color: Theme.palette.chatBackground
                                border.width: 1
                                border.color: Theme.palette.chatBorder

                                VrLineIcon {
                                    anchors.centerIn: parent
                                    width: 16
                                    height: 16
                                    kind: "browser"
                                    foreground: Theme.palette.brandOrange
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 2

                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 8

                                    Text {
                                        text: modelData.name || modelData.appId
                                        color: Theme.palette.headingText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(14)
                                        font.weight: Font.DemiBold
                                    }

                                    Rectangle {
                                        visible: modelData.hasUnidentified
                                        implicitWidth: unidentText.implicitWidth + 10
                                        implicitHeight: 20
                                        radius: Theme.radiusSmall
                                        color: Qt.rgba(0.9, 0.6, 0.0, 0.15)
                                        border.width: 1
                                        border.color: Theme.palette.warning

                                        Text {
                                            id: unidentText
                                            anchors.centerIn: parent
                                            text: "Versão pendente"
                                            color: Theme.palette.warning
                                            font.pixelSize: Theme.fontSize(10)
                                            font.weight: Font.Medium
                                        }
                                    }

                                    Rectangle {
                                        visible: modelData.hasVariants
                                        implicitWidth: varText.implicitWidth + 10
                                        implicitHeight: 20
                                        radius: Theme.radiusSmall
                                        color: Qt.rgba(0.2, 0.6, 1.0, 0.15)
                                        border.width: 1
                                        border.color: Theme.palette.accentSoft

                                        Text {
                                            id: varText
                                            anchors.centerIn: parent
                                            text: "Variantes"
                                            color: Theme.palette.brandOrange
                                            font.pixelSize: Theme.fontSize(10)
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
                                    font.pixelSize: Theme.fontSize(12)
                                }
                            }

                            VrButton {
                                text: "Ver versões →"
                                variant: "secondary"
                                implicitHeight: 32
                                onClicked: {
                                    chat.selectApplication(modelData.appId);
                                    root.activeAppId = modelData.appId;
                                    root.navigationLevel = 1;
                                }
                            }
                        }
                    }
                }

                // Packages List Section
                VrProviderSection {
                    Layout.fillWidth: true
                    title: "Pacotes de Origem Importados"
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
                        implicitHeight: pkgCardLayout.implicitHeight + 16
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

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
                                    font.pixelSize: Theme.fontSize(11)
                                }
                            }

                            VrButton {
                                objectName: "vrUltraRemoveReleaseButton"
                                text: "Remover / Desvincular"
                                variant: "danger"
                                implicitHeight: 28
                                onClicked: {
                                    root.pendingUnlinkPackageId = modelData.package_id;
                                    unlinkConfirmDialog.open();
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

                VrProviderSection {
                    Layout.fillWidth: true
                    title: "Histórico de Versões: " + (root.activeAppId ? root.activeAppId.toUpperCase() : "")
                }

                // Versions Repeater
                Repeater {
                    model: chat.appVersions
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: verCardLayout.implicitHeight + 20
                        radius: Theme.radiusSmall
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.chatBorder

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
                                            font.pixelSize: Theme.fontSize(10)
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
                                            font.pixelSize: Theme.fontSize(10)
                                            font.weight: Font.Medium
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
                                text: "Detalhes e Código →"
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
                                columns: root.width < 800 ? 1 : 4
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
                                    objectName: "vrUltraRetryCodeProcessing"
                                    text: "Repetir"
                                    variant: "secondary"
                                    implicitHeight: 30
                                    enabled: chat.codeProcessingCanRetry && !chat.codeProcessingRunning
                                        && !!chat.selectedAppVariantId && chat.selectedAppOriginId === chat.codeAnalysisRelease
                                    onClicked: chat.retryCodeProcessing()
                                }
                            }

                            ProgressBar {
                                objectName: "vrUltraCodeProcessingProgress"
                                Layout.fillWidth: true
                                from: 0
                                to: 100
                                value: chat.codeProcessingProgress
                                indeterminate: chat.codeProcessingRunning && chat.codeProcessingProgress === 0
                                Behavior on value {
                                    enabled: chat.codeProcessingRunning
                                    NumberAnimation {
                                        duration: 160
                                    }
                                }
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
                                    font.pixelSize: Theme.fontSize(11)
                                }

                                Text {
                                    objectName: "vrUltraCodeProcessingTelemetry"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    wrapMode: Text.Wrap
                                    text: chat.codeProcessingTelemetrySummary
                                    color: Theme.palette.subtleText
                                    font.pixelSize: Theme.fontSize(11)
                                }

                                Text {
                                    objectName: "vrUltraCodeProcessingEta"
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    wrapMode: Text.Wrap
                                    text: chat.codeProcessingEtaSummary
                                    color: Theme.palette.subtleText
                                    font.pixelSize: Theme.fontSize(11)
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
                                    font.pixelSize: Theme.fontSize(11)
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
                                            font.pixelSize: Theme.fontSize(11)
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
                                        implicitHeight: 50
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
                                                font.pixelSize: Theme.fontSize(16)
                                                font.weight: Font.Bold
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: "Adicionadas"
                                                color: Theme.palette.subtleText
                                                font.pixelSize: Theme.fontSize(10)
                                            }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitHeight: 50
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
                                                font.pixelSize: Theme.fontSize(16)
                                                font.weight: Font.Bold
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: "Modificadas"
                                                color: Theme.palette.subtleText
                                                font.pixelSize: Theme.fontSize(10)
                                            }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitHeight: 50
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
                                                font.pixelSize: Theme.fontSize(16)
                                                font.weight: Font.Bold
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: "Removidas"
                                                color: Theme.palette.subtleText
                                                font.pixelSize: Theme.fontSize(10)
                                            }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitHeight: 50
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
                                                font.pixelSize: Theme.fontSize(16)
                                                font.weight: Font.Bold
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignHCenter
                                                text: "Inalteradas"
                                                color: Theme.palette.subtleText
                                                font.pixelSize: Theme.fontSize(10)
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
        width: Math.min(500, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Remover release do índice?"
        standardButtons: Dialog.NoButton
        onClosed: root.pendingUnlinkPackageId = ""
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "A release " + root.pendingUnlinkPackageId
                    + " e seus dados de análise serão removidos. "
                    + "Os JARs de origem serão preservados."
                color: Theme.palette.headingText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                VrButton { text: "Cancelar"; onClicked: unlinkConfirmDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton {
                    objectName: "vrUltraConfirmRemoveReleaseButton"
                    text: "Remover release"
                    variant: "danger"
                    onClicked: {
                        var releaseId = root.pendingUnlinkPackageId
                        unlinkConfirmDialog.close()
                        chat.removeCodeAnalysisRelease(releaseId)
                    }
                }
            }
        }
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.danger
            radius: Theme.radiusSmall
        }
    }
}
