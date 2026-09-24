import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"
import "../settings/appearance"

Item {
    id: root
    objectName: "knowledgeTransferSettingsPage"

    property var detectionResult: null
    property string resultMessage: ""
    property bool resultIsError: false

    readonly property bool busy: chat.releaseSnapshotRunning || chat.codeProcessingRunning

    function formatCount(value) {
        return String(Math.round(Number(value) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ".")
    }

    function formatBytes(value) {
        var bytes = Number(value) || 0
        if (bytes >= 1073741824)
            return (bytes / 1073741824).toFixed(1) + " GB"
        if (bytes >= 1048576)
            return (bytes / 1048576).toFixed(1) + " MB"
        if (bytes >= 1024)
            return (bytes / 1024).toFixed(1) + " KB"
        return Math.round(bytes) + " B"
    }

    function startImport() {
        var detection = root.detectionResult
        knowledgeImportDialog.close()
        if (!detection)
            return
        var chosen = knowledgeImportMode.values[knowledgeImportMode.currentIndex]
        chat.importKnowledgePackageArchive(detection.source_archive, chosen || "merge")
    }

    Component.onCompleted: chat.refreshKnowledgeTransferSummary()

    Connections {
        target: chat

        function onKnowledgePackageDetected(result) {
            if (result.busy || result.canceled)
                return
            if (result.is_valid) {
                root.resultMessage = ""
                root.resultIsError = false
                root.detectionResult = result
                knowledgeImportMode.currentIndex = 0
                knowledgeImportDialog.open()
            } else {
                root.detectionResult = null
                root.resultMessage = result.error || "Pacote de conhecimento inválido."
                root.resultIsError = true
            }
        }

        function onKnowledgePackageImported(result) {
            var failures = Number(result.error_count || 0)
            root.resultIsError = failures > 0
            root.resultMessage = "Importação concluída: "
                + root.formatCount(result.created) + " criados, "
                + root.formatCount(result.updated) + " atualizados, "
                + root.formatCount(result.unchanged) + " inalterados"
                + (failures > 0
                    ? " · " + root.formatCount(failures) + " falhas."
                    : ".")
            if (typeof studio !== "undefined" && studio)
                studio.refreshKnowledgeData()
        }

        function onKnowledgePackageExported(result) {
            root.resultIsError = false
            root.resultMessage = "Pacote exportado: "
                + root.formatCount(result.document_count) + " documentos, "
                + root.formatCount(result.asset_count) + " anexos ("
                + root.formatBytes(result.total_bytes) + ")."
        }

        function onKnowledgeTransferFailed(message) {
            root.resultIsError = true
            root.resultMessage = String(message || "")
        }
    }

    ScrollView {
        id: knowledgeScroll
        objectName: "knowledgeTransferScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        topPadding: Theme.scaledGeometry(4)
        rightPadding: Theme.scaledGeometry(12)
        bottomPadding: Theme.scaledGeometry(24)
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        Item {
            width: knowledgeScroll.availableWidth
            implicitHeight: knowledgeColumn.implicitHeight

            ColumnLayout {
                id: knowledgeColumn
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(900, parent.width)
                spacing: Theme.spaceLg

                Rectangle {
                    objectName: "knowledgeTransferProgressCard"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    visible: chat.knowledgeTransferRunning
                    implicitHeight: knowledgeProgressLayout.implicitHeight + Theme.spaceMd
                    radius: Theme.radiusSmall
                    color: Theme.palette.codeSurface
                    border.width: 1
                    border.color: Theme.palette.chatBorder

                    ColumnLayout {
                        id: knowledgeProgressLayout
                        anchors.fill: parent
                        anchors.margins: Theme.spaceSm
                        spacing: Theme.spaceXs

                        Text {
                            objectName: "knowledgeTransferProgressLabel"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: chat.releaseSnapshotStatus
                            color: Theme.palette.headingText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeCaption
                            font.weight: Theme.weightMedium
                            elide: Text.ElideRight
                            renderType: Theme.textRenderType
                        }

                        VrProgressBar {
                            objectName: "knowledgeTransferProgressBar"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            barHeight: 6
                            accentColor: Theme.palette.brandOrange
                            from: 0
                            to: 100
                            value: chat.knowledgeTransferProgress
                            indeterminate: chat.knowledgeTransferRunning
                                && chat.knowledgeTransferTotal <= 0
                        }
                    }
                }

                Rectangle {
                    objectName: "knowledgeTransferResultBanner"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    visible: root.resultMessage.length > 0 && !chat.knowledgeTransferRunning
                    implicitHeight: resultBannerLayout.implicitHeight + Theme.spaceMd
                    radius: Theme.radiusSmall
                    color: root.resultIsError
                        ? Qt.rgba(0.86, 0.24, 0.24, 0.10)
                        : Qt.rgba(0.06, 0.72, 0.50, 0.10)
                    border.width: 1
                    border.color: root.resultIsError
                        ? Theme.palette.danger : Theme.palette.success

                    RowLayout {
                        id: resultBannerLayout
                        anchors.fill: parent
                        anchors.margins: Theme.spaceSm
                        spacing: Theme.spaceXs

                        Text {
                            objectName: "knowledgeTransferResultText"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: root.resultMessage
                            color: root.resultIsError
                                ? Theme.palette.danger : Theme.palette.success
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeCaption
                            wrapMode: Text.WordWrap
                            renderType: Theme.textRenderType
                        }

                        VrIconButton {
                            iconKind: "close"
                            iconSize: Theme.iconMicro
                            foreground: Theme.palette.mutedText
                            Accessible.name: "Dispensar aviso"
                            onClicked: root.resultMessage = ""
                        }
                    }
                }

                Text {
                    text: "Fontes de conhecimento"
                    Layout.leftMargin: Theme.scaledGeometry(16)
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeControl
                }

                AppearanceGroup {
                    Layout.fillWidth: true

                    Repeater {
                        model: chat.knowledgeTransferSources

                        delegate: AppearanceRow {
                            required property var modelData
                            required property int index
                            title: modelData.label
                            description: modelData.available
                                ? "Origem disponível para exportação e importação."
                                : "Nenhum documento ativo desta origem nesta base."
                            divider: index < chat.knowledgeTransferSources.length - 1

                            VrStatusBadge {
                                text: root.formatCount(modelData.documents) + " docs"
                                kind: modelData.available ? "success" : "info"
                            }

                            VrStatusBadge {
                                text: root.formatCount(modelData.assets) + " anexos"
                                kind: "info"
                            }
                        }
                    }
                }

                Text {
                    text: "Exportar pacote"
                    Layout.leftMargin: Theme.scaledGeometry(16)
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeControl
                }

                AppearanceGroup {
                    Layout.fillWidth: true

                    AppearanceRow {
                        title: "Origens"
                        description: "Documentos e anexos referenciados entram no pacote .zip portátil."
                        divider: true

                        VrCheckBox {
                            id: vrwikiExportCheck
                            objectName: "knowledgeExportVrwikiCheck"
                            text: "VRWiki pública"
                            checked: true
                            enabled: !root.busy
                        }

                        VrCheckBox {
                            id: endooExportCheck
                            objectName: "knowledgeExportEndooCheck"
                            text: "Wiki Endoo"
                            checked: false
                        }

                        VrCheckBox {
                            id: kbExportCheck
                            objectName: "knowledgeExportKbCheck"
                            text: "KB Movidesk"
                            checked: true
                        }
                    }

                    Text {
                        objectName: "knowledgeExportEndooWarning"
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.scaledGeometry(16)
                        Layout.rightMargin: Theme.scaledGeometry(16)
                        Layout.bottomMargin: Theme.scaledGeometry(10)
                        visible: endooExportCheck.checked
                        text: "A Wiki Endoo é conteúdo autenticado: o pacote conterá artigos privados. "
                            + "Compartilhe apenas com quem tem acesso à origem."
                        color: Theme.palette.warning
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeCaption
                        wrapMode: Text.WordWrap
                        renderType: Theme.textRenderType
                    }

                    AppearanceRow {
                        title: "Módulo"
                        description: "Exporte todos os módulos ou isole um deles."
                        divider: true

                        VrComboBox {
                            id: knowledgeModuleCombo
                            objectName: "knowledgeExportModuleCombo"
                            Layout.preferredWidth: Theme.scaledGeometry(220)
                            implicitHeight: Theme.scaledGeometry(34)
                            enabled: !root.busy
                            model: (typeof studio !== "undefined" && studio)
                                ? studio.moduleItems
                                : ["Todos"]
                            background: Rectangle {
                                radius: Theme.scaledGeometry(8)
                                color: Theme.palette.codeSurface
                                border.width: knowledgeModuleCombo.activeFocus ? 2 : 1
                                border.color: knowledgeModuleCombo.activeFocus
                                    ? Theme.palette.focus : Theme.palette.border
                            }
                        }
                    }

                    AppearanceRow {
                        title: "Anexos"
                        description: "Imagens e arquivos referenciados sempre acompanham o pacote; "
                            + "pacotes completos podem ficar grandes."
                        divider: false

                        VrButton {
                            objectName: "exportKnowledgePackageButton"
                            text: "Exportar pacote…"
                            variant: "primary"
                            implicitHeight: Theme.scaledGeometry(32)
                            enabled: !root.busy
                                && (vrwikiExportCheck.checked
                                    || endooExportCheck.checked
                                    || kbExportCheck.checked)
                            onClicked: chat.exportKnowledgePackage(
                                vrwikiExportCheck.checked,
                                endooExportCheck.checked,
                                kbExportCheck.checked,
                                knowledgeModuleCombo.currentText,
                                "")
                        }
                    }
                }

                Text {
                    text: "Importar pacote"
                    Layout.leftMargin: Theme.scaledGeometry(16)
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeControl
                }

                AppearanceGroup {
                    Layout.fillWidth: true

                    AppearanceRow {
                        title: "Pacote de conhecimento VRStudio (.zip)"
                        description: "Valida o manifesto e os hashes antes de gravar. "
                            + "No modo mesclar, módulos e revisões aprovados localmente são preservados."
                        divider: false

                        VrButton {
                            objectName: "importKnowledgePackageButton"
                            text: "Importar pacote…"
                            variant: "secondary"
                            implicitHeight: Theme.scaledGeometry(32)
                            enabled: !root.busy
                            onClicked: chat.detectKnowledgePackageArchive("")
                        }
                    }
                }

                Item { Layout.preferredHeight: Theme.scaledGeometry(16) }
            }
        }
    }

    Dialog {
        id: knowledgeImportDialog
        objectName: "knowledgeImportDialog"
        anchors.centerIn: parent
        width: Math.min(560, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Importar Pacote de Conhecimento"
        standardButtons: Dialog.NoButton

        contentItem: ColumnLayout {
            spacing: Theme.spaceMd

            Text {
                Layout.fillWidth: true
                text: "Pacote portátil VRStudio (.zip)"
                color: Theme.palette.brandOrange
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeControl
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }

            Text {
                objectName: "knowledgeImportSummary"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.detectionResult ? (
                    "Pacote: " + (root.detectionResult.package_id || "—") + "\n"
                    + "Documentos: " + root.formatCount(root.detectionResult.document_count)
                    + " · Anexos: " + root.formatCount(root.detectionResult.asset_count)
                    + " · Tamanho: " + root.formatBytes(root.detectionResult.total_bytes) + "\n"
                    + "Módulos: " + ((root.detectionResult.modules || []).join(", ") || "—")
                ) : ""
                color: Theme.palette.headingText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeControl
                wrapMode: Text.WordWrap
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: Theme.spaceXs

                Repeater {
                    model: root.detectionResult ? root.detectionResult.origins : []

                    delegate: Text {
                        required property var modelData
                        Layout.fillWidth: true
                        text: "· " + modelData.label + ": "
                            + root.formatCount(modelData.documents) + " documentos, "
                            + root.formatCount(modelData.assets) + " anexos"
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeCaption
                        wrapMode: Text.WordWrap
                    }
                }
            }

            VrComboBox {
                id: knowledgeImportMode
                objectName: "knowledgeImportModeCombo"
                Layout.fillWidth: true
                implicitHeight: Theme.scaledGeometry(34)
                property var values: ["merge", "restore"]
                model: [
                    "Mesclar — preserva revisões locais",
                    "Restaurar — sobrescreve decisões locais"
                ]
                background: Rectangle {
                    radius: Theme.scaledGeometry(8)
                    color: Theme.palette.codeSurface
                    border.width: knowledgeImportMode.activeFocus ? 2 : 1
                    border.color: knowledgeImportMode.activeFocus
                        ? Theme.palette.focus : Theme.palette.border
                }
            }

            Text {
                objectName: "knowledgeImportRestoreWarning"
                Layout.fillWidth: true
                visible: knowledgeImportMode.currentIndex === 1
                text: "O modo restaurar grava módulo e revisão exatamente como no pacote, "
                    + "substituindo decisões de revisão locais desses documentos."
                color: Theme.palette.warning
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeCaption
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.fillWidth: true

                VrButton {
                    text: "Cancelar"
                    onClicked: knowledgeImportDialog.close()
                }

                Item { Layout.fillWidth: true }

                VrButton {
                    objectName: "confirmKnowledgeImportButton"
                    text: "Importar conhecimento"
                    variant: "primary"
                    enabled: !!root.detectionResult
                    onClicked: root.startImport()
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
}
