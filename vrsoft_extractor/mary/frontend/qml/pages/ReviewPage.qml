import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    property bool filtersVisible: false
    property var filterControls: ({})
    property string pendingAction: ""
    property var pendingReviewIds: []

    function registerFilter(key, control) {
        filterControls[key] = control
    }

    function filterValue(key) {
        var control = filterControls[key]
        if (!control || control.currentIndex < 0) return ""
        var entry = control.model[control.currentIndex]
        if (entry && typeof entry === "object" && entry.value !== undefined)
            return entry.value
        return control.currentIndex === 0 ? "" : control.currentText
    }

    function applyFilters() {
        studio.searchReviewsAdvanced(reviewSearch.text, {
            source: filterValue("source"),
            sourceOrigin: filterValue("origin"),
            currentModule: filterValue("current"),
            suggestedModule: filterValue("suggested"),
            confidence: filterValue("confidence"),
            status: filterValue("status"),
            product: filterValue("product"),
            category: filterValue("category"),
            periodDays: filterValue("period"),
            special: filterValue("special"),
            sort: filterValue("sort")
        })
    }

    function clearFilters() {
        reviewSearch.clear()
        for (var key in filterControls) filterControls[key].currentIndex = 0
        applyFilters()
    }

    function applyPreset(preset) {
        for (var key in filterControls) filterControls[key].currentIndex = 0
        if (preset === "simple") {
            filterControls.special.currentIndex = 4
            filterControls.sort.currentIndex = 1
        } else if (preset === "no_product") {
            filterControls.special.currentIndex = 2
        } else if (preset === "deferred") {
            filterControls.status.currentIndex = 2
        }
        applyFilters()
    }

    Rectangle { anchors.fill: parent; color: frontend.palette.background }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: 8

        VrPageHeader {
            Layout.fillWidth: true
            title: "Revisão"
            subtitle: "Triagem auditável por risco, evidência, produto e módulo."
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border
            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                VrTextField {
                    id: reviewSearch
                    Layout.fillWidth: true
                    placeholderText: "Buscar título, ID, produto, categoria, motivo ou conteúdo"
                    background: Item { }
                    onAccepted: root.applyFilters()
                }
                VrButton { text: (root.filtersVisible ? "▾ " : "▸ ") + "Filtros"; onClicked: root.filtersVisible = !root.filtersVisible }
                Text { text: studio.reviewTotal + " resultados"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11) }
            }
        }

        Rectangle {
            visible: root.filtersVisible
            Layout.fillWidth: true
            Layout.preferredHeight: 168
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 5
                GridLayout {
                    Layout.fillWidth: true
                    columns: 6
                    columnSpacing: 7
                    rowSpacing: 5
                    Repeater {
                        model: [
                            ["Fonte", [{text:"Todas",value:""},{text:"Wiki",value:"wiki"},{text:"KB",value:"kb"}], "source"],
                            ["Origem", [{text:"Todas",value:""},{text:"VRWiki",value:"vrwiki"},{text:"Endoo",value:"endoo"},{text:"Movidesk",value:"movidesk"}], "origin"],
                            ["Módulo atual", studio.moduleItems, "current"],
                            ["Módulo sugerido", studio.moduleItems, "suggested"],
                            ["Confiança", [{text:"Todas",value:""},{text:"Alta",value:"high"},{text:"Média",value:"medium"},{text:"Baixa",value:"low"}], "confidence"],
                            ["Estado", [{text:"Pendente",value:"pending"},{text:"Aprovado",value:"approved"},{text:"Adiado",value:"deferred"},{text:"Mantido",value:"kept"},{text:"Todos",value:"all"}], "status"],
                            ["Produto", studio.productItems, "product"],
                            ["Categoria", studio.categoryItems, "category"],
                            ["Período", [{text:"Todo o período",value:0},{text:"Últimos 7 dias",value:7},{text:"Últimos 30 dias",value:30},{text:"Últimos 90 dias",value:90}], "period"],
                            ["Especial", [{text:"Todos os riscos",value:""},{text:"Mudança de módulo validado",value:"module_change"},{text:"Sem produto identificado",value:"no_product"},{text:"Pouca evidência",value:"low_evidence"},{text:"Aprovação simples",value:"simple"}], "special"],
                            ["Ordenação", [{text:"Maior risco primeiro",value:"risk"},{text:"Maior confiança",value:"confidence_desc"},{text:"Menor confiança",value:"confidence_asc"},{text:"Mais recentes",value:"recent"},{text:"Título A–Z",value:"title"}], "sort"]
                        ]
                        delegate: ColumnLayout {
                            required property int index
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 1
                            Text { text: modelData[0]; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(9) }
                            VrComboBox {
                                id: filterCombo
                                Layout.fillWidth: true
                                implicitHeight: 31
                                model: modelData[1]
                                textRole: modelData[1].length && typeof modelData[1][0] === "object" ? "text" : ""
                                onActivated: filterDelay.restart()
                                Component.onCompleted: root.registerFilter(modelData[2], filterCombo)
                            }
                        }
                    }
                    Item { Layout.fillWidth: true }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "Atalhos:"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                    VrButton { text: "Maior risco"; implicitHeight: 28; onClicked: root.applyPreset("risk") }
                    VrButton { text: "Aprovação simples"; implicitHeight: 28; onClicked: root.applyPreset("simple") }
                    VrButton { text: "Sem produto"; implicitHeight: 28; onClicked: root.applyPreset("no_product") }
                    VrButton { text: "Adiados"; implicitHeight: 28; onClicked: root.applyPreset("deferred") }
                    VrButton { text: "Limpar filtros"; implicitHeight: 28; onClicked: root.clearFilters() }
                    Item { Layout.fillWidth: true }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            VrButton {
                text: "Selecionar todos"
                enabled: studio.reviewTotal > 0
                onClicked: studio.setAllReviewsSelected(true)
            }
            VrButton { text: "Limpar seleção"; enabled: studio.reviewSelectionCount > 0; onClicked: studio.setAllReviewsSelected(false) }
            Item { Layout.fillWidth: true }
            Text { text: studio.reviewSelectionCount + " selecionados"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            handle: Rectangle {
                implicitWidth: 9
                color: reviewHandleHover.hovered
                    ? frontend.palette.brandOrange : "transparent"
                Rectangle {
                    anchors.centerIn: parent
                    width: 1
                    height: parent.height - 12
                    color: reviewHandleHover.hovered
                        ? frontend.palette.brandOrange : frontend.palette.border
                }
                HoverHandler { id: reviewHandleHover }
            }

            Rectangle {
                SplitView.minimumWidth: 620
                SplitView.preferredWidth: 840
                SplitView.fillWidth: true
                radius: Theme.radiusCard
                color: frontend.palette.surface
                border.width: 1
                border.color: frontend.palette.border
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    Rectangle {
                        visible: studio.reviewTotal > 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: 36
                        color: frontend.palette.surfaceRaised
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 5
                            anchors.rightMargin: 5
                            spacing: 5
                            Text { Layout.preferredWidth: 25; text: "✓"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); horizontalAlignment: Text.AlignHCenter }
                            Text { Layout.fillWidth: true; text: "Título"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 45; text: "Fonte"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 80; text: "Atual"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 80; text: "Sugestão"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 45; text: "Conf."; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 75; text: "Produto"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 75; text: "Categoria"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 110; text: "Risco / motivo"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 80; text: "Atualização"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                        }
                    }

                    ListView {
                        id: reviewList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: studio.reviewModel
                        delegate: Rectangle {
                        id: reviewRow
                        required property int index
                        required property int reviewId
                        required property string title
                        required property string source
                        required property string currentModule
                        required property string suggestedModule
                        required property string confidence
                        required property string product
                        required property string category
                        required property string risk
                        required property string updatedAt
                        width: reviewList.width
                        height: 50
                        color: index % 2 ? frontend.palette.surfaceRaised : frontend.palette.surface
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 5
                            anchors.rightMargin: 5
                            spacing: 5
                            VrCheckBox {
                                implicitWidth: 25
                                checked: studio.reviewSelectionCount >= 0
                                    && studio.isReviewSelected(reviewRow.reviewId)
                                onToggled: studio.setReviewSelected(reviewRow.reviewId, checked)
                            }
                            Text { Layout.fillWidth: true; text: reviewRow.title; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: 45; text: reviewRow.source; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: 80; text: reviewRow.currentModule; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: 80; text: reviewRow.suggestedModule; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: 45; text: reviewRow.confidence; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11) }
                            Text { Layout.preferredWidth: 75; text: reviewRow.product; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: 75; text: reviewRow.category; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: 110; text: reviewRow.risk; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: 80; text: reviewRow.updatedAt; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); elide: Text.ElideRight }
                        }
                        TapHandler { onTapped: studio.selectReview(reviewRow.index) }
                    }

                    VrEmptyState {
                        anchors.centerIn: parent
                        visible: studio.reviewTotal === 0
                        title: "Nenhuma revisão encontrada"
                        description: "Sincronize as fontes para gerar revisões"
                        actionText: "Sincronizar fontes"
                        onAction: frontend.setCurrentPage(3)
                    }
                }
                }
            }

            Rectangle {
                visible: studio.reviewTotal > 0
                SplitView.minimumWidth: 330
                SplitView.preferredWidth: 380
                radius: Theme.radiusCard
                color: frontend.palette.surface
                border.width: 1
                border.color: frontend.palette.border
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8
                    Text { Layout.fillWidth: true; text: studio.reviewTitle; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(16); font.weight: Font.DemiBold; elide: Text.ElideRight }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        TextEdit { id: reviewPreviewBody; width: parent.width; text: studio.reviewPreview; textFormat: TextEdit.MarkdownText; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); onTextChanged: frontend.styleMessageDocument(reviewPreviewBody.textDocument, studio.reviewPreview) }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        VrButton { text: "Abrir fonte"; enabled: studio.reviewUrl.length > 0; onClicked: studio.openExternalUrl(studio.reviewUrl) }
                        VrButton { text: "Abrir local"; enabled: studio.reviewLocalPath.length > 0; onClicked: studio.openLocalPath(studio.reviewLocalPath) }
                        VrButton { text: "Copiar citação"; onClicked: studio.copyText(studio.reviewCitation) }
                    }
                    VrTextArea { id: reviewNote; Layout.fillWidth: true; Layout.preferredHeight: 72; placeholderText: "Observação da revisão" }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Destino:"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                        VrComboBox { id: destinationModule; Layout.fillWidth: true; model: ["Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar"] }
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        VrButton { Layout.fillWidth: true; text: "Aprovar"; variant: "primary"; onClicked: decide("approve") }
                        VrButton { Layout.fillWidth: true; text: "Manter atual"; onClicked: decide("keep") }
                        VrButton { Layout.fillWidth: true; text: "Adiar"; onClicked: decide("defer") }
                        VrButton { Layout.fillWidth: true; text: "Reabrir"; onClicked: decide("reopen") }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            VrButton { text: "< Anterior"; enabled: studio.reviewCanPrevious; onClicked: studio.previousReviewPage() }
            Text { text: studio.reviewPageLabel; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
            VrButton { text: "Próxima >"; enabled: studio.reviewCanNext; onClicked: studio.nextReviewPage() }
            Item { Layout.fillWidth: true }
            Text { text: studio.reviewTotal ? studio.reviewTotal + " itens" : "Nenhum item"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11) }
        }
    }

    function decide(action) {
        if (studio.reviewSelectionCount > 0) {
            root.pendingAction = action
            root.pendingReviewIds = studio.selectedReviewIds
            bulkDecisionDialog.open()
            return
        }
        if (studio.currentReviewId > 0)
            applyDecision(action, [studio.currentReviewId])
    }

    function applyDecision(action, reviewIds) {
        studio.decideReviews(action, reviewIds, destinationModule.currentText, reviewNote.text)
    }

    Timer { id: filterDelay; interval: 180; onTriggered: root.applyFilters() }

    Dialog {
        id: bulkDecisionDialog
        anchors.centerIn: parent
        width: 500
        modal: true
        title: "Confirmar ação nos selecionados"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: 10
            Text {
                Layout.fillWidth: true
                text: "A ação será aplicada a " + root.pendingReviewIds.length + " revisão(ões) selecionada(s) e ficará registrada no histórico. Destino: " + destinationModule.currentText + "."
                color: frontend.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                VrButton { text: "Cancelar"; onClicked: bulkDecisionDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton { text: "Aplicar"; variant: "primary"; onClicked: { root.applyDecision(root.pendingAction, root.pendingReviewIds); bulkDecisionDialog.close() } }
            }
        }
        background: Rectangle { color: frontend.palette.surface; border.width: 1; border.color: frontend.palette.border; radius: Theme.radiusPopup }
    }
}
