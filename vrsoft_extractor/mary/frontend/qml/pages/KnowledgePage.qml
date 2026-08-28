import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "knowledgePage"
    property bool filtersVisible: false
    property bool documentExpanded: false

    Rectangle { anchors.fill: parent; color: frontend.palette.background }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: 8

        VrPageHeader {
            Layout.fillWidth: true
            title: "Conhecimento"
            subtitle: "Pesquisa local FTS5 em textos, metadados e OCR."
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 54
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border
            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8
                VrTextField {
                    id: query
                    Layout.fillWidth: true
                    placeholderText: "Ex.: configuração PIX, erro TEF, cadastro de produto"
                    background: Item { }
                    onAccepted: runSearch()
                }
                VrButton { text: (root.filtersVisible ? "▾ " : "▸ ") + "Filtros"; onClicked: root.filtersVisible = !root.filtersVisible }
                Text {
                    text: studio.knowledgeTotal + (studio.knowledgeTotal === 1 ? " documento encontrado" : " documentos encontrados")
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(11)
                }
                VrButton { text: "Pesquisar"; variant: "primary"; onClicked: runSearch() }
            }
        }

        Rectangle {
            visible: root.filtersVisible
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border
            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8
                Text { text: "Módulo:"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13) }
                VrComboBox { id: moduleFilter; Layout.fillWidth: true; model: studio.moduleItems }
                Text { text: "Fonte:"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13) }
                VrComboBox { id: sourceFilter; Layout.fillWidth: true; model: studio.sourceItems }
                Text { text: "Origem:"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13) }
                VrComboBox { id: originFilter; Layout.fillWidth: true; model: ["Todas", "vrwiki", "endoo", "movidesk"] }
                VrButton {
                    text: "Limpar"
                    onClicked: { moduleFilter.currentIndex = 0; sourceFilter.currentIndex = 0; originFilter.currentIndex = 0; query.clear(); runSearch() }
                }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            handle: Rectangle {
                implicitWidth: 9
                color: splitHandleHover.hovered
                    ? frontend.palette.brandOrange : "transparent"
                Rectangle {
                    anchors.centerIn: parent
                    width: 1
                    height: parent.height - 12
                    color: splitHandleHover.hovered
                        ? frontend.palette.brandOrange : frontend.palette.border
                }
                HoverHandler { id: splitHandleHover }
            }

            Rectangle {
                visible: !root.documentExpanded
                SplitView.minimumWidth: 360
                SplitView.preferredWidth: 520
                color: frontend.palette.surface
                border.width: 1
                border.color: frontend.palette.border
                radius: Theme.radiusCard
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        color: frontend.palette.surfaceRaised
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            Text { Layout.fillWidth: true; Layout.preferredWidth: 280; text: "Título"; horizontalAlignment: Text.AlignHCenter; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 130; text: "Módulo"; horizontalAlignment: Text.AlignHCenter; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 62; text: "Fonte"; horizontalAlignment: Text.AlignHCenter; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: 74; text: "Status"; horizontalAlignment: Text.AlignHCenter; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                        }
                    }
                    ListView {
                        id: knowledgeList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: studio.knowledgeModel
                        currentIndex: studio.knowledgeTotal > 0 ? 0 : -1
                        delegate: Rectangle {
                            required property int index
                            required property string title
                            required property string module
                            required property string source
                            required property string status
                            width: knowledgeList.width
                            height: 39
                            color: knowledgeList.currentIndex === index ? frontend.palette.selection
                                : index % 2 ? frontend.palette.surfaceRaised : frontend.palette.surface
                            border.width: 0
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 4
                                anchors.rightMargin: 4
                                spacing: 4
                                Text { Layout.fillWidth: true; Layout.preferredWidth: 280; text: title; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); elide: Text.ElideRight }
                                Text { Layout.preferredWidth: 130; text: module; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); elide: Text.ElideRight }
                                Text { Layout.preferredWidth: 62; text: source; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); elide: Text.ElideRight }
                                Text { Layout.preferredWidth: 74; text: status; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); elide: Text.ElideRight }
                            }
                            TapHandler { onTapped: { knowledgeList.currentIndex = index; studio.selectKnowledge(index) } }
                        }
                        VrEmptyState {
                            anchors.centerIn: parent
                            visible: studio.knowledgeTotal === 0
                            title: "Nenhum documento encontrado"
                            description: "Sincronize as Wikis ou o KB para alimentar a base local."
                            actionText: "Sincronizar fontes"
                            onAction: frontend.setCurrentPage(3)
                        }
                    }
                }
            }

            Rectangle {
                SplitView.minimumWidth: 330
                SplitView.preferredWidth: 540
                SplitView.fillWidth: true
                color: frontend.palette.surface
                border.width: 1
                border.color: frontend.palette.border
                radius: Theme.radiusCard
                clip: true
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        Layout.leftMargin: 10
                        Layout.rightMargin: 8
                        Text { Layout.fillWidth: true; text: "Documento"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(15); font.weight: Font.DemiBold }
                        VrIconButton {
                            symbol: "↗"
                            enabled: studio.knowledgeLocalPath.length > 0
                            ToolTip.visible: hovered
                            ToolTip.text: "Abrir arquivo local"
                            onClicked: studio.openLocalPath(studio.knowledgeLocalPath)
                        }
                        VrIconButton {
                            symbol: root.documentExpanded ? "◫" : "▣"
                            ToolTip.visible: hovered
                            ToolTip.text: root.documentExpanded
                                ? "Restaurar lista de documentos" : "Expandir documento"
                            onClicked: root.documentExpanded = !root.documentExpanded
                        }
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        TextEdit {
                            id: knowledgePreviewBody
                            width: parent.width
                            padding: 16
                            text: studio.knowledgePreview
                            textFormat: TextEdit.MarkdownText
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            color: frontend.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            onLinkActivated: link => {
                                if (studio) studio.openExternalUrl(link)
                            }
                            onTextChanged: frontend.styleMessageDocument(
                                knowledgePreviewBody.textDocument,
                                studio.knowledgePreview
                            )
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            VrButton { text: "← Anterior"; enabled: studio.knowledgeCanPrevious; onClicked: studio.previousKnowledgePage() }
            Text { text: studio.knowledgePageLabel; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
            VrButton { text: "Próxima →"; enabled: studio.knowledgeCanNext; onClicked: studio.nextKnowledgePage() }
            Item { Layout.fillWidth: true }
            Text { text: "Exibindo resultados da base local"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11) }
        }
    }

    function runSearch() {
        studio.searchKnowledge(query.text, moduleFilter.currentText, sourceFilter.currentText,
            originFilter.currentIndex > 0 ? originFilter.currentText : "")
    }
}
