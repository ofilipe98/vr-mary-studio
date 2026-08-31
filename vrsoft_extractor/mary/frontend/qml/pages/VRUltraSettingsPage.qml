import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "vrUltraSettingsPage"

    readonly property int selectedModelIndex: {
        if (!chat.researchModelKeys.length) return -1
        var selectedKey = chat.researchModelKeys[0]
        for (var index = 0; index < chat.modelItems.length; ++index) {
            if (chat.modelItems[index].key === selectedKey) return index
        }
        return -1
    }

    ScrollView {
        id: settingsScroll
        objectName: "vrUltraSettingsScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            width: settingsScroll.availableWidth
            spacing: Theme.spaceLg

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            Text {
                text: "VR Ultra · agentes"
                color: frontend.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.headingSize
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: "Escolha um modelo para os três agentes base e, quando habilitado, para o Agente de Código. O Chat VR continua sendo o orquestrador."
                color: frontend.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                wrapMode: Text.WordWrap
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            radius: Theme.radiusControl
            color: Qt.rgba(1.0, 0.45, 0.0, 0.09)
            border.width: 1
            border.color: Qt.rgba(1.0, 0.45, 0.0, 0.45)

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceMd
                anchors.rightMargin: Theme.spaceMd
                spacing: Theme.spaceSm
                VrLineIcon {
                    Layout.preferredWidth: 18
                    Layout.preferredHeight: 18
                    kind: "models"
                    foreground: frontend.palette.brandOrange
                }
                Text {
                    Layout.fillWidth: true
                    text: "Orquestrador: definido pelo seletor de provedor/modelo no compositor do Chat VR"
                    color: frontend.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    elide: Text.ElideRight
                }
            }
        }

        Rectangle {
            objectName: "vrUltraSeniorProfileCard"
            Layout.fillWidth: true
            Layout.preferredHeight: 146
            color: "transparent"
            border.width: 0

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Perfil especialista sênior"
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Libera no Chat VR e VR Ultra a escolha manual do formato. É preferência de trabalho, não autorização."
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            wrapMode: Text.WordWrap
                        }
                    }
                    VrCheckBox {
                        objectName: "vrUltraSeniorProfileToggle"
                        text: "Ativo"
                        checked: chat.seniorProfileEnabled
                        onToggled: chat.setSeniorProfileEnabled(checked)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Modo de resposta"
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.captionSize
                    }
                    VrComboBox {
                        id: responseModePicker
                        objectName: "vrUltraResponseModePicker"
                        Layout.fillWidth: true
                        enabled: chat.seniorProfileEnabled
                        model: ["Automático", "Treinamento", "Suporte", "Implantação"]
                        property var values: ["auto", "training", "support", "implementation"]
                        currentIndex: Math.max(0, values.indexOf(chat.vrResponseMode))
                        onActivated: index => chat.setVrResponseMode(values[index])
                    }
                }
            }
        }

        Rectangle {
            objectName: "vrUltraAgentPool"
            Layout.fillWidth: true
            Layout.preferredHeight: 152
            color: "transparent"
            border.width: 0

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm
                    VrLineIcon {
                        Layout.preferredWidth: 20
                        Layout.preferredHeight: 20
                        kind: "agents"
                        foreground: frontend.palette.text
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text {
                            text: "Modelo dos agentes de pesquisa"
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "A mesma escolha é usada pelos três pesquisadores base e pelo worker opcional de código."
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                        }
                    }
                    Rectangle {
                        Layout.preferredWidth: 78
                        Layout.preferredHeight: 24
                        radius: 8
                        color: Qt.rgba(1.0, 0.45, 0.0, 0.12)
                        Text {
                            anchors.centerIn: parent
                            text: chat.codeAnalysisEnabled ? "4 agentes" : "3 agentes"
                            color: frontend.palette.brandOrange
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            font.weight: Font.DemiBold
                        }
                    }
                }

                VrModelPicker {
                    id: agentModelPicker
                    objectName: "vrUltraAgentModelPicker"
                    Layout.fillWidth: true
                    implicitHeight: 42
                    popupAbove: false
                    model: chat.modelItems
                    currentIndex: root.selectedModelIndex
                    onActivated: index => chat.setResearchModels([chat.modelItems[index].key])
                    onFavoriteToggled: index => chat.toggleModelFavorite(index)
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: chat.researchModelKeys.length
                ? "Os agentes usarão " + (agentModelPicker.currentItem.displayName
                    || agentModelPicker.currentItem.label || "o modelo selecionado") + "."
                : "Selecione o modelo dos agentes do VR Ultra."
            color: frontend.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.captionSize
            wrapMode: Text.WordWrap
        }

        Rectangle {
            objectName: "vrUltraCodeAnalysisCard"
            Layout.fillWidth: true
            Layout.preferredHeight: codeAnalysisContent.implicitHeight + Theme.spaceMd * 2
            color: "transparent"
            border.width: 0

            ColumnLayout {
                id: codeAnalysisContent
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Agente de Código / JAR"
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "Opt-in: consulta somente o índice da release após os outros agentes delimitarem o escopo."
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                            wrapMode: Text.WordWrap
                        }
                    }
                    VrCheckBox {
                        objectName: "vrUltraCodeAnalysisToggle"
                        text: "Ativo"
                        checked: chat.codeAnalysisEnabled
                        enabled: chat.codeAnalysisReleaseItems.length > 0
                            && chat.codeAnalysisReleaseFresh
                        onToggled: chat.setCodeAnalysisEnabled(checked)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Release"
                        color: frontend.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.captionSize
                    }
                    VrComboBox {
                        id: codeReleasePicker
                        objectName: "vrUltraCodeAnalysisRelease"
                        Layout.fillWidth: true
                        enabled: chat.codeAnalysisReleaseItems.length > 0
                            && !chat.codeProcessingRunning
                        model: chat.codeAnalysisReleaseItems.length
                            ? chat.codeAnalysisReleaseItems
                            : [{"label": "Nenhuma release inventariada", "releaseId": ""}]
                        textRole: "label"
                        currentIndex: {
                            for (var index = 0; index < chat.codeAnalysisReleaseItems.length; ++index) {
                                if (chat.codeAnalysisReleaseItems[index].releaseId === chat.codeAnalysisRelease)
                                    return index
                            }
                            return 0
                        }
                        onActivated: index => {
                            if (index < chat.codeAnalysisReleaseItems.length)
                                chat.setCodeAnalysisRelease(chat.codeAnalysisReleaseItems[index].releaseId)
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: {
                        var index = codeReleasePicker.currentIndex
                        if (index < 0 || index >= chat.codeAnalysisReleaseItems.length)
                            return ""
                        return chat.codeAnalysisReleaseItems[index].warning || ""
                    }
                    color: frontend.palette.warning
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            objectName: "vrUltraJarDirectoryCard"
            Layout.fillWidth: true
            Layout.preferredHeight: jarDirectoryContent.implicitHeight + Theme.spaceMd * 2
            color: "transparent"
            border.width: 0

            ColumnLayout {
                id: jarDirectoryContent
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                Text {
                    text: "Diretório padrão dos JARs"
                    color: frontend.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.bodySize
                    font.weight: Font.DemiBold
                }

                VrComboBox {
                    id: jarSourcePicker
                    objectName: "vrUltraJarDirectoryPicker"
                    Layout.fillWidth: true
                    enabled: !chat.releaseSnapshotRunning
                        && !chat.codeProcessingRunning
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

                Text {
                    text: "Escopo da análise"
                    color: frontend.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    font.weight: Font.DemiBold
                }

                VrComboBox {
                    id: jarScopePicker
                    objectName: "vrUltraJarScopePicker"
                    Layout.fillWidth: true
                    enabled: !chat.releaseSnapshotRunning
                        && !chat.codeProcessingRunning
                    model: [
                        { "label": "Pacote completo ou incremental", "value": "full_release" },
                        { "label": "Somente um JAR", "value": "single_jar" }
                    ]
                    textRole: "label"
                    currentIndex: chat.codeAnalysisSnapshotScope === "single_jar" ? 1 : 0
                    onActivated: index => chat.setCodeAnalysisSnapshotScope(
                        index === 1 ? "single_jar" : "full_release"
                    )
                }

                Text {
                    Layout.fillWidth: true
                    text: {
                        var index = jarSourcePicker.currentIndex
                        if (index < 0 || index >= chat.codeAnalysisJarSourceItems.length)
                            return ""
                        var item = chat.codeAnalysisJarSourceItems[index]
                        if (chat.codeAnalysisSnapshotScope === "single_jar")
                            return item.path + " · " + item.status
                                + " · escolha um JAR abaixo"
                        var composition = item.jarCount > 0
                            && item.jarCount < chat.codeAnalysisExpectedJarCount
                            ? " · pacote incremental: os demais JARs virão da base completa"
                            : ""
                        return item.path + " · " + item.status + composition
                    }
                    color: {
                        var index = jarSourcePicker.currentIndex
                        if (index < 0 || index >= chat.codeAnalysisJarSourceItems.length)
                            return frontend.palette.mutedText
                        var item = chat.codeAnalysisJarSourceItems[index]
                        return item.exists && item.jarCount > 0
                            ? frontend.palette.mutedText
                            : frontend.palette.warning
                    }
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    objectName: "vrUltraSingleJarRow"
                    Layout.fillWidth: true
                    visible: chat.codeAnalysisSnapshotScope === "single_jar"
                    spacing: Theme.spaceSm

                    VrTextField {
                        objectName: "vrUltraSingleJarPath"
                        Layout.fillWidth: true
                        readOnly: true
                        text: chat.codeAnalysisSingleJarPath
                        placeholderText: "Nenhum JAR selecionado"
                    }

                    VrButton {
                        objectName: "vrUltraSelectSingleJarButton"
                        text: "Escolher JAR…"
                        enabled: !chat.releaseSnapshotRunning
                            && !chat.codeProcessingRunning
                        onClicked: chat.selectCodeAnalysisSingleJar()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm

                    VrTextField {
                        id: releaseIdField
                        objectName: "vrUltraReleaseIdField"
                        Layout.fillWidth: true
                        placeholderText: chat.codeAnalysisSnapshotScope === "single_jar"
                            ? "Automático: aplicação e versão do vr*.properties"
                            : "ID automático; informe somente se quiser personalizar"
                        enabled: !chat.releaseSnapshotRunning
                            && !chat.codeProcessingRunning
                        onAccepted: {
                            chat.snapshotCodeAnalysisRelease(text.trim())
                        }
                    }

                    VrButton {
                        objectName: "vrUltraAddReleaseButton"
                        text: chat.releaseSnapshotRunning ? "Detectando…" : "Detectar e adicionar"
                        variant: "primary"
                        enabled: !chat.releaseSnapshotRunning
                            && !chat.codeProcessingRunning
                            && (chat.codeAnalysisSnapshotScope !== "single_jar"
                                || chat.codeAnalysisSingleJarPath.length > 0)
                        onClicked: chat.snapshotCodeAnalysisRelease(releaseIdField.text.trim())
                    }
                }

                Text {
                    objectName: "vrUltraReleaseSnapshotStatus"
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: chat.releaseSnapshotStatus
                    color: text.indexOf("Não foi possível") === 0
                        ? frontend.palette.warning
                        : frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            objectName: "vrUltraCodeProcessingCard"
            Layout.fillWidth: true
            Layout.preferredHeight: codeProcessingContent.implicitHeight + Theme.spaceMd * 2
            color: "transparent"
            border.width: 0

            ColumnLayout {
                id: codeProcessingContent
                anchors.fill: parent
                anchors.margins: Theme.spaceMd
                spacing: Theme.spaceSm

                Text {
                    text: "Processamento local do índice"
                    color: frontend.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.bodySize
                    font.weight: Font.DemiBold
                }

                Text {
                    Layout.fillWidth: true
                    text: "Decompilação, AST/grafo e FTS rodam na máquina do analista. A pausa ocorre com segurança entre lotes."
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Heap máximo por lote"
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                        }
                        VrComboBox {
                            id: codeProcessingHeapPicker
                            objectName: "vrUltraCodeProcessingHeapPicker"
                            Layout.fillWidth: true
                            enabled: !chat.codeProcessingRunning
                            model: chat.codeProcessingHeapOptions
                            textRole: "label"
                            currentIndex: {
                                for (var index = 0; index < chat.codeProcessingHeapOptions.length; ++index) {
                                    if (chat.codeProcessingHeapOptions[index].value === chat.codeProcessingMaxHeapMb)
                                        return index
                                }
                                return 0
                            }
                            onActivated: index => chat.setCodeProcessingMaxHeapMb(
                                chat.codeProcessingHeapOptions[index].value
                            )
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Timeout por lote"
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                        }
                        VrComboBox {
                            id: codeProcessingTimeoutPicker
                            objectName: "vrUltraCodeProcessingTimeoutPicker"
                            Layout.fillWidth: true
                            enabled: !chat.codeProcessingRunning
                            model: chat.codeProcessingTimeoutOptions
                            textRole: "label"
                            currentIndex: {
                                for (var index = 0; index < chat.codeProcessingTimeoutOptions.length; ++index) {
                                    if (chat.codeProcessingTimeoutOptions[index].value === chat.codeProcessingTimeoutSeconds)
                                        return index
                                }
                                return 0
                            }
                            onActivated: index => chat.setCodeProcessingTimeoutSeconds(
                                chat.codeProcessingTimeoutOptions[index].value
                            )
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "CPU máxima"
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                        }
                        VrComboBox {
                            objectName: "vrUltraCodeProcessingCpuPicker"
                            Layout.fillWidth: true
                            enabled: !chat.codeProcessingRunning
                            model: chat.codeProcessingCpuCoreOptions
                            textRole: "label"
                            currentIndex: {
                                for (var index = 0; index < chat.codeProcessingCpuCoreOptions.length; ++index) {
                                    if (chat.codeProcessingCpuCoreOptions[index].value === chat.codeProcessingMaxCpuCores)
                                        return index
                                }
                                return 0
                            }
                            onActivated: index => chat.setCodeProcessingMaxCpuCores(
                                chat.codeProcessingCpuCoreOptions[index].value
                            )
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Limite do índice"
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                        }
                        VrComboBox {
                            objectName: "vrUltraCodeProcessingDiskPicker"
                            Layout.fillWidth: true
                            enabled: !chat.codeProcessingRunning
                            model: chat.codeProcessingDiskMultiplierOptions
                            textRole: "label"
                            currentIndex: {
                                for (var index = 0; index < chat.codeProcessingDiskMultiplierOptions.length; ++index) {
                                    if (chat.codeProcessingDiskMultiplierOptions[index].value === chat.codeProcessingDiskMultiplier)
                                        return index
                                }
                                return 0
                            }
                            onActivated: index => chat.setCodeProcessingDiskMultiplier(
                                chat.codeProcessingDiskMultiplierOptions[index].value
                            )
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Janela de execução"
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.captionSize
                        }
                        VrComboBox {
                            objectName: "vrUltraCodeProcessingWindowPicker"
                            Layout.fillWidth: true
                            enabled: !chat.codeProcessingRunning
                            model: chat.codeProcessingWindowOptions
                            textRole: "label"
                            currentIndex: {
                                for (var index = 0; index < chat.codeProcessingWindowOptions.length; ++index) {
                                    if (chat.codeProcessingWindowOptions[index].value === chat.codeProcessingWindow)
                                        return index
                                }
                                return 0
                            }
                            onActivated: index => chat.setCodeProcessingWindow(
                                chat.codeProcessingWindowOptions[index].value
                            )
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Concorrência Java fixa: 1 processo, com prioridade baixa. Heap, CPU, disco e janela são congelados ao iniciar."
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    wrapMode: Text.WordWrap
                }

                Rectangle {
                    objectName: "vrUltraCodeProcessingProgress"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 8
                    radius: 4
                    color: frontend.palette.border

                    Rectangle {
                        width: parent.width * Math.max(0, Math.min(100, chat.codeProcessingProgress)) / 100
                        height: parent.height
                        radius: parent.radius
                        color: frontend.palette.brandOrange
                    }
                }

                Text {
                    objectName: "vrUltraCodeProcessingStatus"
                    Layout.fillWidth: true
                    text: chat.codeProcessingStatus
                    color: chat.codeProcessingCanRetry
                        || text.indexOf("Falha") === 0
                        || text.indexOf("desatualizada") >= 0
                        ? frontend.palette.warning
                        : frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    wrapMode: Text.WordWrap
                }

                Text {
                    Layout.fillWidth: true
                    visible: chat.codeProcessingFrozenManifestHash.length > 0
                    text: "Execução congelada em " + chat.codeProcessingFrozenRelease
                        + " · manifesto "
                        + chat.codeProcessingFrozenManifestHash.substring(0, 12)
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    elide: Text.ElideRight
                }

                Text {
                    objectName: "vrUltraCodeProcessingCurrentBatch"
                    Layout.fillWidth: true
                    visible: chat.codeProcessingCurrentJar.length > 0
                    text: "JAR atual/próximo: " + chat.codeProcessingCurrentJar
                        + (chat.codeProcessingCurrentBatch.length > 0
                            ? " · lote " + chat.codeProcessingCurrentBatch
                            : "")
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    elide: Text.ElideMiddle
                }

                Text {
                    objectName: "vrUltraCodeProcessingTelemetry"
                    Layout.fillWidth: true
                    visible: chat.codeProcessingTelemetrySummary.length > 0
                    text: chat.codeProcessingTelemetrySummary
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    wrapMode: Text.WordWrap
                }

                Text {
                    objectName: "vrUltraCodeProcessingEta"
                    Layout.fillWidth: true
                    visible: chat.codeProcessingTotalJars > 0
                        && chat.codeProcessingProgress < 100
                    text: chat.codeProcessingEtaSummary
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.captionSize
                    wrapMode: Text.WordWrap
                }

                VrComboBox {
                    id: codeProcessingRetryPicker
                    objectName: "vrUltraCodeProcessingRetryPicker"
                    Layout.fillWidth: true
                    visible: chat.codeProcessingCanRetry
                    enabled: !chat.codeProcessingRunning
                    model: chat.codeProcessingAttentionBatches
                    textRole: "label"
                    currentIndex: {
                        for (var index = 0; index < chat.codeProcessingAttentionBatches.length; ++index) {
                            if (chat.codeProcessingAttentionBatches[index].batchId === chat.codeProcessingRetryBatch)
                                return index
                        }
                        return 0
                    }
                    onActivated: index => chat.setCodeProcessingRetryBatch(
                        chat.codeProcessingAttentionBatches[index].batchId
                    )
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm

                    VrButton {
                        objectName: "vrUltraStartCodeProcessing"
                        Layout.fillWidth: true
                        text: chat.codeProcessingProgress >= 100
                            ? "Concluído"
                            : chat.codeProcessingCoveredJars > 0
                                || chat.codeProcessingFrozenManifestHash.length > 0
                            ? "Retomar"
                            : "Iniciar"
                        variant: "primary"
                        enabled: chat.codeAnalysisReleaseFresh
                            && !chat.codeProcessingRunning
                            && !chat.codeProcessingStatusLoading
                            && !chat.releaseSnapshotRunning
                            && !chat.codeProcessingCanRetry
                            && chat.codeProcessingProgress < 100
                        onClicked: chat.startCodeProcessing()
                    }

                    VrButton {
                        objectName: "vrUltraPauseCodeProcessing"
                        Layout.fillWidth: true
                        text: chat.codeProcessingPauseRequested ? "Pausa solicitada" : "Pausar"
                        enabled: chat.codeProcessingRunning
                            && !chat.codeProcessingPauseRequested
                        onClicked: chat.pauseCodeProcessing()
                    }

                    VrButton {
                        objectName: "vrUltraRetryCodeProcessing"
                        Layout.fillWidth: true
                        text: "Retry selecionado"
                        enabled: chat.codeProcessingCanRetry
                            && !chat.codeProcessingRunning
                            && !chat.codeProcessingStatusLoading
                        onClicked: chat.retryCodeProcessing()
                    }
                }
            }
        }

            Item { Layout.preferredHeight: Theme.spaceMd }
        }
    }

    Component.onCompleted: {
        chat.refreshModels()
        chat.refreshCodeAnalysisReleases()
        chat.refreshCodeProcessingStatus()
    }
}
