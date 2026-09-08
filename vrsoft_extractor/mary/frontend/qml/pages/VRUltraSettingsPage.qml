import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "vrUltraSettingsPage"
    property string pendingReleaseRemoval: ""

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
        topPadding: 4
        rightPadding: 12
        bottomPadding: 20
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: settingsScroll.availableWidth
            spacing: 16


            // Header
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
                        kind: "models"
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
                        text: "VR Ultra · Agentes Especialistas"
                        color: Theme.palette.headingText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(16)
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Modelos dos pesquisadores base, perfil especialista sênior e índice local de código Java/JAR."
                        color: Theme.palette.subtleText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            VrRetrievalSettings {
                Layout.fillWidth: true
                bridge: chat.retrievalSettings
            }

            // Orchestrator banner
            Rectangle {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: 42
                radius: Theme.radiusSmall
                color: Theme.palette.codeSurface
                border.width: 1
                border.color: Theme.palette.chatBorder

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceMd
                    spacing: Theme.spaceSm

                    VrLineIcon {
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 16
                        kind: "models"
                        foreground: Theme.palette.brandOrange
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Orquestrador: definido pelo seletor de provedor/modelo no compositor do Chat VR"
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        elide: Text.ElideRight
                    }
                }
            }

            // Section 1: Perfil especialista sênior
            VrProviderSection {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                title: "Perfil especialista sênior"
            }

            Rectangle {
                objectName: "vrUltraSeniorProfileCard"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: vrUltraSeniorProfileCardContent.implicitHeight
                color: "transparent"
                border.width: 0

                ColumnLayout {
                    id: vrUltraSeniorProfileCardContent
                    anchors.fill: parent
                    spacing: 12

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Habilitar perfil sênior"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Libera no Chat VR e VR Ultra a escolha manual do formato de resposta. É preferência de trabalho, não autorização."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            objectName: "vrUltraSeniorProfileToggle"
                            Accessible.name: "Habilitar perfil sênior"
                            checked: chat.seniorProfileEnabled
                            onToggled: chat.setSeniorProfileEnabled(checked)
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
                                text: "Modo de resposta"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Diretriz de formatação e tom da resposta dos agentes."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrComboBox {
                            Layout.alignment: Qt.AlignRight
                            id: responseModePicker
                            objectName: "vrUltraResponseModePicker"
                            Layout.preferredWidth: 210
                            implicitHeight: 38
                            enabled: chat.seniorProfileEnabled
                            model: ["Automático", "Treinamento", "Suporte", "Implantação"]
                            property var values: ["auto", "training", "support", "implementation"]
                            currentIndex: Math.max(0, values.indexOf(chat.vrResponseMode))
                            onActivated: index => chat.setVrResponseMode(values[index])
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: responseModePicker.activeFocus ? 2 : 1
                                border.color: responseModePicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }
                    }
                }
            }

            // Section 2: Modelo dos agentes de pesquisa
            VrProviderSection {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                title: "Modelo dos agentes de pesquisa"
            }

            Rectangle {
                objectName: "vrUltraAgentPool"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: vrUltraAgentPoolContent.implicitHeight
                color: "transparent"
                border.width: 0

                ColumnLayout {
                    id: vrUltraAgentPoolContent
                    anchors.fill: parent
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 10

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Pool de pesquisadores"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "A mesma escolha é usada pelos três pesquisadores base e pelo worker opcional de código."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        Rectangle {
                            Layout.preferredWidth: 84
                            Layout.preferredHeight: 26
                            radius: Theme.radiusSmall
                            color: Qt.rgba(1.0, 0.45, 0.0, 0.12)
                            border.width: 1
                            border.color: Qt.rgba(1.0, 0.45, 0.0, 0.3)

                            Text {
                                anchors.centerIn: parent
                                text: chat.codeAnalysisEnabled ? "4 agentes" : "3 agentes"
                                color: Theme.palette.brandOrange
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                            }
                        }
                    }

                    VrModelPicker {
                        id: agentModelPicker
                        objectName: "vrUltraAgentModelPicker"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 42
                        outlined: true
                        popupAbove: false
                        model: chat.modelItems
                        currentIndex: root.selectedModelIndex
                        onActivated: index => chat.setResearchModels([chat.modelItems[index].key])
                        onFavoriteToggled: index => chat.toggleModelFavorite(index)
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: chat.researchModelKeys.length
                            ? "Os agentes usarão " + (agentModelPicker.currentItem.displayName
                                || agentModelPicker.currentItem.label || "o modelo selecionado") + "."
                            : "Selecione o modelo dos agentes do VR Ultra."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Section 3: Agente de Código / JAR
            VrProviderSection {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                title: "Agente de Código / JAR"
            }

            Rectangle {
                objectName: "vrUltraCodeAnalysisCard"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: vrUltraCodeAnalysisCardContent.implicitHeight
                color: "transparent"
                border.width: 0

                ColumnLayout {
                    id: vrUltraCodeAnalysisCardContent
                    anchors.fill: parent
                    spacing: 12

                    VrSettingsRow {
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Análise de código JAR"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Opt-in: consulta somente o índice da release após os outros agentes delimitarem o escopo."
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                wrapMode: Text.WordWrap
                            }
                        }

                        VrSwitch {
                            subdued: true
                            Layout.alignment: Qt.AlignRight
                            objectName: "vrUltraCodeAnalysisToggle"
                            Accessible.name: "Análise de código JAR"
                            checked: chat.codeAnalysisEnabled
                            enabled: chat.codeAnalysisReleaseItems.length > 0
                                && chat.codeAnalysisReleaseFresh
                            onToggled: chat.setCodeAnalysisEnabled(checked)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 8

                        Text {
                            text: "Release"
                            color: Theme.palette.headingText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                            Layout.preferredWidth: 60
                        }

                        VrComboBox {
                            id: codeReleasePicker
                            objectName: "vrUltraCodeAnalysisRelease"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: 38
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
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: codeReleasePicker.activeFocus ? 2 : 1
                                border.color: codeReleasePicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }

                        VrButton {
                            objectName: "vrUltraRemoveReleaseButton"
                            text: "Remover"
                            variant: "danger"
                            implicitHeight: 34
                            enabled: chat.codeAnalysisReleaseItems.length > 0
                                && chat.codeAnalysisRelease.length > 0
                                && !chat.releaseSnapshotRunning
                                && !chat.codeProcessingRunning
                            onClicked: {
                                root.pendingReleaseRemoval = chat.codeAnalysisRelease
                                removeReleaseDialog.open()
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: text.length > 0
                        text: {
                            var index = codeReleasePicker.currentIndex
                            if (index < 0 || index >= chat.codeAnalysisReleaseItems.length)
                                return ""
                            return chat.codeAnalysisReleaseItems[index].warning || ""
                        }
                        color: Theme.palette.warning
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Section 4: Diretório e escopo dos JARs
            VrProviderSection {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                title: "Diretório e escopo dos JARs"
            }

            Rectangle {
                objectName: "vrUltraJarDirectoryCard"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: vrUltraJarDirectoryCardContent.implicitHeight
                color: "transparent"
                border.width: 0

                ColumnLayout {
                    id: vrUltraJarDirectoryCardContent
                    anchors.fill: parent
                    spacing: 12

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
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: jarSourcePicker.activeFocus ? 2 : 1
                                border.color: jarSourcePicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
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
                            enabled: !chat.releaseSnapshotRunning
                                && !chat.codeProcessingRunning
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
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: jarScopePicker.activeFocus ? 2 : 1
                                border.color: jarScopePicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
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
                                return item.path + " · " + item.status
                                    + " · escolha um JAR abaixo"
                            var composition = item.jarCount > 0
                                ? " · " + chat.codeAnalysisExpectedJarCount
                                    + " JARs formam a release completa; quantidades menores serão indexadas como release parcial"
                                : ""
                            return item.path + " · " + item.status + composition
                        }
                        color: {
                            var index = jarSourcePicker.currentIndex
                            if (index < 0 || index >= chat.codeAnalysisJarSourceItems.length)
                                return Theme.palette.mutedText
                            var item = chat.codeAnalysisJarSourceItems[index]
                            return item.exists && item.jarCount > 0
                                ? Theme.palette.mutedText
                                : Theme.palette.warning
                        }
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
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: 1
                                border.color: Theme.palette.chatBorder
                            }
                        }

                        VrButton {
                            objectName: "vrUltraSelectSingleJarButton"
                            text: "Escolher JAR…"
                            implicitHeight: 34
                            enabled: !chat.releaseSnapshotRunning
                                && !chat.codeProcessingRunning
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
                            enabled: !chat.releaseSnapshotRunning
                                && !chat.codeProcessingRunning
                            onAccepted: {
                                chat.snapshotCodeAnalysisRelease(text.trim())
                            }
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.palette.codeSurface
                                border.width: releaseIdField.activeFocus ? 2 : 1
                                border.color: releaseIdField.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                            }
                        }

                        VrButton {
                            objectName: "vrUltraAddReleaseButton"
                            text: chat.releaseSnapshotRunning ? "Detectando…" : "Detectar e adicionar"
                            variant: "primary"
                            implicitHeight: 34
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
                        Layout.minimumWidth: 0
                        visible: text.length > 0
                        text: chat.releaseSnapshotStatus
                        color: text.indexOf("Não foi possível") === 0
                            ? Theme.palette.warning
                            : Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // Section 5: Processamento local do índice
            VrProviderSection {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                title: "Processamento local do índice"
            }

            Rectangle {
                objectName: "vrUltraCodeProcessingCard"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: vrUltraCodeProcessingCardContent.implicitHeight
                color: "transparent"
                border.width: 0

                ColumnLayout {
                    id: vrUltraCodeProcessingCardContent
                    anchors.fill: parent
                    spacing: 12

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "Decompilação, AST/grafo e FTS rodam na máquina do analista. A pausa ocorre com segurança entre grupos de lotes."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        objectName: "vrUltraCodeProcessingHardwareSummary"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: chat.codeProcessingHardwareSummary
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    GridLayout {
                        columns: width < 620 ? 1 : 2
                        columnSpacing: 12
                        rowSpacing: 12
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 4
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Heap máximo por lote"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            VrComboBox {
                                id: codeProcessingHeapPicker
                                objectName: "vrUltraCodeProcessingHeapPicker"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                implicitHeight: 38
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
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: codeProcessingHeapPicker.activeFocus ? 2 : 1
                                    border.color: codeProcessingHeapPicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 4
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Timeout por lote"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            VrComboBox {
                                id: codeProcessingTimeoutPicker
                                objectName: "vrUltraCodeProcessingTimeoutPicker"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                implicitHeight: 38
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
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: codeProcessingTimeoutPicker.activeFocus ? 2 : 1
                                    border.color: codeProcessingTimeoutPicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }
                        }
                    }

                    GridLayout {
                        columns: width < 620 ? 1 : 3
                        columnSpacing: 12
                        rowSpacing: 12
                        Layout.fillWidth: true

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 4
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "CPU máxima"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            VrComboBox {
                                id: codeProcessingCpuPicker
                                objectName: "vrUltraCodeProcessingCpuPicker"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                implicitHeight: 38
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
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: codeProcessingCpuPicker.activeFocus ? 2 : 1
                                    border.color: codeProcessingCpuPicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 4
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Limite do índice"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            VrComboBox {
                                id: codeProcessingDiskPicker
                                objectName: "vrUltraCodeProcessingDiskPicker"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                implicitHeight: 38
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
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: codeProcessingDiskPicker.activeFocus ? 2 : 1
                                    border.color: codeProcessingDiskPicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 4
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: "Janela de execução"
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            VrComboBox {
                                id: codeProcessingWindowPicker
                                objectName: "vrUltraCodeProcessingWindowPicker"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                implicitHeight: 38
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
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: Theme.palette.codeSurface
                                    border.width: codeProcessingWindowPicker.activeFocus ? 2 : 1
                                    border.color: codeProcessingWindowPicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                                }
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: chat.codeProcessingParallelWorkers > 1
                            ? "Modo paralelo automático: " + chat.codeProcessingParallelWorkers
                                + " processos Java, " + chat.codeProcessingCpuCoresPerWorker
                                + " CPU(s) por processo e prioridade normal. AST/FTS usa escrita SQLite serializada."
                            : "Modo equilibrado: 1 processo Java com prioridade baixa. Aumente o limite de CPU para ampliar o paralelismo."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: "Progresso do índice"
                            color: Theme.palette.headingText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            font.weight: Font.DemiBold
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            Layout.minimumWidth: 0
                            objectName: "vrUltraCodeProcessingProgressLabel"
                            horizontalAlignment: Text.AlignRight
                            text: Number(chat.codeProcessingProgress).toFixed(
                                chat.codeProcessingProgress >= 100 ? 0 : 1
                            ) + "% · "
                                + chat.codeProcessingCoveredJars + "/"
                                + chat.codeProcessingTotalJars + " JARs"
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            wrapMode: Text.WordWrap
                        }
                    }

                    ProgressBar {
                        id: codeProcessingProgress
                        objectName: "vrUltraCodeProcessingProgress"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredHeight: 8
                        from: 0
                        to: 100
                        value: Math.max(0, Math.min(100, chat.codeProcessingProgress))
                        Accessible.name: "Progresso do processamento local do índice"
                        Accessible.description: Number(chat.codeProcessingProgress).toFixed(
                            chat.codeProcessingProgress >= 100 ? 0 : 1
                        ) + "% · "
                            + chat.codeProcessingCoveredJars + " de "
                            + chat.codeProcessingTotalJars + " JARs concluídos"

                        background: Rectangle {
                            radius: height / 2
                            color: Theme.palette.codeSurface
                            border.width: 1
                            border.color: Theme.palette.chatBorder
                        }

                        contentItem: Item {
                            clip: true

                            Rectangle {
                                width: codeProcessingProgress.visualPosition * parent.width
                                height: parent.height
                                radius: height / 2
                                color: Theme.palette.brandOrange
                            }

                            Rectangle {
                                id: processingPulse
                                visible: chat.codeProcessingRunning && !frontend.reduceMotion
                                width: Math.max(28, Math.min(96, parent.width * 0.22))
                                height: parent.height
                                radius: height / 2
                                color: Theme.palette.text
                                opacity: 0.25

                                SequentialAnimation on x {
                                    running: chat.codeProcessingRunning && !frontend.reduceMotion
                                        && codeProcessingProgress.visible
                                    loops: Animation.Infinite
                                    NumberAnimation {
                                        from: -processingPulse.width
                                        to: codeProcessingProgress.width
                                        duration: 1150
                                        easing.type: Easing.InOutSine
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        objectName: "vrUltraCodeProcessingStatus"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: chat.codeProcessingStatus
                        color: chat.codeProcessingCanRetry
                            || text.indexOf("Falha") === 0
                            || text.indexOf("desatualizada") >= 0
                            ? Theme.palette.warning
                            : Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 8

                        Text {
                            objectName: "vrUltraCodeProcessingCapacity"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: chat.codeProcessingCapacitySummary
                            color: chat.codeProcessingCanCleanOrphans
                                ? Theme.palette.warning
                                : Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            wrapMode: Text.WordWrap
                        }

                        VrButton {
                            objectName: "vrUltraCleanCodeProcessingOrphans"
                            visible: chat.codeProcessingCanCleanOrphans
                            text: "Limpar órfãos"
                            implicitHeight: 34
                            enabled: !chat.codeProcessingRunning
                                && !chat.codeProcessingStatusLoading
                                && !chat.releaseSnapshotRunning
                            onClicked: cleanOrphansDialog.open()
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: chat.codeProcessingFrozenManifestHash.length > 0
                        text: "Execução congelada em " + chat.codeProcessingFrozenRelease
                            + " · manifesto "
                            + chat.codeProcessingFrozenManifestHash.substring(0, 12)
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        elide: Text.ElideRight
                    }

                    Text {
                        objectName: "vrUltraCodeProcessingCurrentBatch"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: chat.codeProcessingCurrentJar.length > 0
                        text: "JAR atual/próximo: " + chat.codeProcessingCurrentJar
                            + (chat.codeProcessingCurrentBatch.length > 0
                                ? " · lote " + chat.codeProcessingCurrentBatch
                                : "")
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        elide: Text.ElideMiddle
                    }

                    Text {
                        objectName: "vrUltraCodeProcessingTelemetry"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: chat.codeProcessingTelemetrySummary.length > 0
                        text: chat.codeProcessingTelemetrySummary
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        objectName: "vrUltraCodeProcessingEta"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: chat.codeProcessingTotalJars > 0
                            && chat.codeProcessingProgress < 100
                        text: chat.codeProcessingEtaSummary
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        wrapMode: Text.WordWrap
                    }

                    VrComboBox {
                        id: codeProcessingRetryPicker
                        objectName: "vrUltraCodeProcessingRetryPicker"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 38
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
                        background: Rectangle {
                            radius: Theme.radiusSmall
                            color: Theme.palette.codeSurface
                            border.width: codeProcessingRetryPicker.activeFocus ? 2 : 1
                            border.color: codeProcessingRetryPicker.activeFocus ? Theme.palette.focus : Theme.palette.chatBorder
                        }
                    }

                    GridLayout {
                        columns: width < 620 ? 1 : 3
                        columnSpacing: 8
                        rowSpacing: 8
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0

                        VrButton {
                            objectName: "vrUltraStartCodeProcessing"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: 34
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
                                && chat.codeProcessingCapacity.state !== "insufficient"
                                && chat.codeProcessingProgress < 100
                            onClicked: chat.startCodeProcessing()
                        }

                        VrButton {
                            objectName: "vrUltraPauseCodeProcessing"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: 34
                            text: chat.codeProcessingPauseRequested ? "Pausa solicitada" : "Pausar"
                            enabled: chat.codeProcessingRunning
                                && !chat.codeProcessingPauseRequested
                            onClicked: chat.pauseCodeProcessing()
                        }

                        VrButton {
                            objectName: "vrUltraRetryCodeProcessing"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            implicitHeight: 34
                            text: "Retry selecionado"
                            enabled: chat.codeProcessingCanRetry
                                && !chat.codeProcessingRunning
                                && !chat.codeProcessingStatusLoading
                            onClicked: chat.retryCodeProcessing()
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 16 }
        }
    }

    Component.onCompleted: {
        chat.refreshCodeAnalysisReleases()
        chat.refreshCodeProcessingStatus()
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
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
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
            radius: Theme.radiusPopup
        }
    }

    Dialog {
        id: removeReleaseDialog
        objectName: "vrUltraRemoveReleaseDialog"
        anchors.centerIn: parent
        width: Math.min(500, root.width - Theme.spaceLg * 2)
        modal: true
        title: "Remover release do índice?"
        standardButtons: Dialog.NoButton
        onClosed: root.pendingReleaseRemoval = ""
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: "A release " + root.pendingReleaseRemoval
                    + " e seus dados de análise serão removidos. "
                    + "Os JARs de origem serão preservados."
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                VrButton { text: "Cancelar"; onClicked: removeReleaseDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton {
                    objectName: "vrUltraConfirmRemoveReleaseButton"
                    text: "Remover release"
                    variant: "danger"
                    onClicked: {
                        var releaseId = root.pendingReleaseRemoval
                        removeReleaseDialog.close()
                        chat.removeCodeAnalysisRelease(releaseId)
                    }
                }
            }
        }
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.danger
            radius: Theme.radiusPopup
        }
    }
}
