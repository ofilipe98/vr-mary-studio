import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "knowledgePage"
    readonly property bool compact: width < Theme.scaledGeometry(760)
    property bool filtersVisible: false
    property bool documentExpanded: false

    Rectangle { anchors.fill: parent; color: frontend.palette.chatBackground }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: Theme.scaledGeometry(8)

        VrPageHeader {
            Layout.fillWidth: true
            title: "Conhecimento"
            subtitle: "Pesquisa local FTS5 em textos, metadados e OCR."
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: searchActions.implicitHeight + Theme.spaceLg
            color: "transparent"
            border.width: 0
            GridLayout {
                id: searchActions
                columns: root.compact ? 2 : 4
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(8)
                columnSpacing: Theme.scaledGeometry(8)
                VrTextField {
                    id: query
                    Layout.columnSpan: root.compact ? 2 : 1
                    Layout.minimumWidth: 0
                    Layout.fillWidth: true
                    placeholderText: "Ex.: configuração PIX, erro TEF, cadastro de produto"
                    background: Item { }
                    onAccepted: runSearch()
                }
                VrButton { text: (root.filtersVisible ? "▾ " : "▸ ") + "Filtros"; onClicked: root.filtersVisible = !root.filtersVisible }
                Text {
                    visible: !root.compact
                    text: studio.knowledgeTotal + (studio.knowledgeTotal === 1 ? " documento encontrado" : " documentos encontrados")
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                }
                VrButton { text: "Pesquisar"; variant: "primary"; onClicked: runSearch() }
            }
        }

        Rectangle {
            visible: root.filtersVisible
            Layout.fillWidth: true
            Layout.preferredHeight: filterActions.implicitHeight + Theme.spaceLg
            color: frontend.palette.chatSidebar
            border.width: 0
            GridLayout {
                id: filterActions
                columns: root.compact ? 2 : 7
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(8)
                columnSpacing: Theme.scaledGeometry(8)
                Text { text: "Módulo:"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl }
                VrComboBox { id: moduleFilter; Layout.fillWidth: true; model: studio.moduleItems }
                Text { text: "Fonte:"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl }
                VrComboBox { id: sourceFilter; Layout.fillWidth: true; model: studio.sourceItems }
                Text { text: "Origem:"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl }
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
            orientation: root.compact ? Qt.Vertical : Qt.Horizontal

            handle: Rectangle {
                implicitWidth: Theme.scaledGeometry(9)
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
                SplitView.minimumWidth: 0
                SplitView.minimumHeight: root.compact ? Theme.scaledGeometry(180) : 0
                SplitView.preferredHeight: Theme.scaledGeometry(280)
                SplitView.preferredWidth: Theme.scaledGeometry(520)
                color: "transparent"
                border.width: 0
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Theme.scaledGeometry(42)
                        color: frontend.palette.chatSidebar
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.scaledGeometry(8)
                            anchors.rightMargin: Theme.scaledGeometry(8)
                            Text { Layout.fillWidth: true; Layout.preferredWidth: Theme.scaledGeometry(280); text: "Título"; horizontalAlignment: Text.AlignHCenter; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; font.weight: Font.DemiBold }
                            Text { visible: !root.compact; Layout.preferredWidth: Theme.scaledGeometry(130); text: "Módulo"; horizontalAlignment: Text.AlignHCenter; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: Theme.scaledGeometry(62); text: "Fonte"; horizontalAlignment: Text.AlignHCenter; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; font.weight: Font.DemiBold }
                            Text { Layout.preferredWidth: Theme.scaledGeometry(74); text: "Status"; horizontalAlignment: Text.AlignHCenter; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; font.weight: Font.DemiBold }
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
                            height: Theme.scaledGeometry(39)
                            color: knowledgeList.currentIndex === index ? frontend.palette.selection
                                : index % 2 ? frontend.palette.chatSidebar : "transparent"
                            border.width: 0
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.scaledGeometry(4)
                                anchors.rightMargin: Theme.scaledGeometry(4)
                                spacing: Theme.scaledGeometry(4)
                                Text { Layout.fillWidth: true; Layout.preferredWidth: Theme.scaledGeometry(280); text: title; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; elide: Text.ElideRight }
                                Text { visible: !root.compact; Layout.preferredWidth: Theme.scaledGeometry(130); text: module; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; elide: Text.ElideRight }
                                Text { Layout.preferredWidth: Theme.scaledGeometry(62); text: source; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; elide: Text.ElideRight }
                                Text { Layout.preferredWidth: Theme.scaledGeometry(74); text: status; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; elide: Text.ElideRight }
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
                SplitView.minimumWidth: 0
                SplitView.minimumHeight: root.compact ? Theme.scaledGeometry(120) : 0
                SplitView.fillHeight: true
                SplitView.preferredWidth: Theme.scaledGeometry(540)
                SplitView.fillWidth: true
                color: "transparent"
                border.width: 0
                clip: true
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Theme.scaledGeometry(42)
                        Layout.leftMargin: Theme.scaledGeometry(10)
                        Layout.rightMargin: Theme.scaledGeometry(8)
                        Text { Layout.fillWidth: true; text: "Documento"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl; font.weight: Font.DemiBold }
                        VrIconButton {
                            symbol: "↗"
                            enabled: studio.knowledgeLocalPath.length > 0
                            Accessible.name: "Abrir arquivo local"
                            onClicked: studio.openLocalPath(studio.knowledgeLocalPath)
                        }
                        VrIconButton {
                            symbol: root.documentExpanded ? "◫" : "▣"
                            Accessible.name: root.documentExpanded
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
                            padding: Theme.scaledGeometry(16)
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
                            Connections {
                                target: frontend
                                function onThemeChanged() {
                                    frontend.styleMessageDocument(
                                        knowledgePreviewBody.textDocument,
                                        studio.knowledgePreview
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            VrButton { text: "Anterior"; enabled: studio.knowledgeCanPrevious; onClicked: studio.previousKnowledgePage() }
            Text { text: studio.knowledgePageLabel; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl; font.weight: Font.DemiBold }
            VrButton { text: "Próxima"; enabled: studio.knowledgeCanNext; onClicked: studio.nextKnowledgePage() }
            Item { Layout.fillWidth: true }
            Text { visible: !root.compact; text: "Exibindo resultados da base local"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption }
        }
    }

    function runSearch() {
        studio.searchKnowledge(query.text, moduleFilter.currentText, sourceFilter.currentText,
            originFilter.currentIndex > 0 ? originFilter.currentText : "")
    }
}
