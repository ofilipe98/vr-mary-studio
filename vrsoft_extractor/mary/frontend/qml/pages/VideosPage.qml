import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "videosPage"
    property bool filtersVisible: false
    property var selectedIds: []
    property var collapsedNodeIds: []
    property bool treeInitialized: false
    readonly property bool filterActive: videoSearch.text.trim().length > 0
        || sourceFilter.currentIndex > 0 || moduleFilter.currentIndex > 0
        || statusFilter.currentIndex > 0

    Connections {
        target: studio
        function onVideosChanged() {
            root.ensureInitialCollapse()
        }
    }

    function ensureInitialCollapse() {
        if (root.treeInitialized || root.filterActive) return
        if (studio.videoLoading) return
        if (videoList.count <= 0) return
        if (studio.videoExpandableNodeIds.length <= 0) return
        root.collapsedNodeIds = studio.videoExpandableNodeIds.slice()
        root.treeInitialized = true
    }

    Component.onCompleted: root.ensureInitialCollapse()

    function runFilter() {
        studio.filterVideos(
            videoSearch.text,
            sourceFilter.currentIndex > 0 ? sourceFilter.model[sourceFilter.currentIndex].value : "",
            moduleFilter.currentIndex > 0 ? moduleFilter.currentText : "",
            statusFilter.currentIndex > 0 ? statusFilter.model[statusFilter.currentIndex].value : ""
        )
        selectedIds = []
    }

    function clearFilters() {
        videoSearch.clear()
        sourceFilter.currentIndex = 0
        moduleFilter.currentIndex = 0
        statusFilter.currentIndex = 0
        runFilter()
    }

    function nodeCollapsed(nodeId) {
        return collapsedNodeIds.indexOf(nodeId) >= 0
    }

    function nodeVisible(ancestorIds) {
        if (root.filterActive) return true
        for (var i = 0; i < ancestorIds.length; ++i)
            if (nodeCollapsed(ancestorIds[i])) return false
        return true
    }

    function toggleNode(nodeId) {
        var values = collapsedNodeIds.slice()
        var position = values.indexOf(nodeId)
        if (position >= 0) {
            values.splice(position, 1)
            var descendants = studio.videoDescendantNodeIds(nodeId)
            for (var index = 0; index < descendants.length; ++index)
                if (values.indexOf(descendants[index]) < 0) values.push(descendants[index])
        } else values.push(nodeId)
        collapsedNodeIds = values
    }

    Rectangle { anchors.fill: parent; color: frontend.palette.chatBackground }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: Theme.scaledGeometry(7)

        VrPageHeader {
            Layout.fillWidth: true
            title: "Vídeos"
            subtitle: "Cursos e Biblioteca classificados por módulo; não há transcrição nesta versão."
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(54)
            color: "transparent"
            border.width: 0
            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(8)
                VrTextField {
                    id: videoSearch
                    Layout.fillWidth: true
                    placeholderText: "Filtrar por curso, pasta, capítulo ou vídeo"
                    background: Item { }
                    onTextChanged: videoFilterDelay.restart()
                    onAccepted: root.runFilter()
                }
                VrButton { text: (root.filtersVisible ? "▾ " : "▸ ") + "Filtros"; onClicked: root.filtersVisible = !root.filtersVisible }
                Text { text: videoList.count + " itens"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption }
                VrButton { text: "Inventariar e baixar"; variant: "primary"; onClicked: studio.runVideoAction("run") }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 5
            columnSpacing: Theme.scaledGeometry(8)
            rowSpacing: Theme.scaledGeometry(7)
            VrButton { Layout.fillWidth: true; text: "Login"; onClicked: studio.runVideoAction("login") }
            VrButton { Layout.fillWidth: true; text: "Atualizar cursos"; onClicked: studio.runVideoAction("courses") }
            VrButton { Layout.fillWidth: true; text: "Inventariar"; onClicked: studio.runVideoAction("scan") }
            VrButton { Layout.fillWidth: true; text: "Classificar"; onClicked: studio.runVideoAction("classify-videos") }
            VrButton { Layout.fillWidth: true; text: "Baixar seleção"; onClicked: studio.runVideoSelection("download", root.selectedIds) }
            VrButton { Layout.fillWidth: true; text: "Inscrever selecionados"; onClicked: studio.enrollSelectedCourses(root.selectedIds) }
            VrButton { Layout.fillWidth: true; text: "Organizar downloads"; onClicked: studio.organizeVideoDownloads() }
            VrButton { Layout.fillWidth: true; text: "Parar"; enabled: studio.videoRunning; onClicked: studio.stopVideoAction() }
            Item { Layout.columnSpan: 2; Layout.fillWidth: true }
        }

        Rectangle {
            visible: root.filtersVisible
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(54)
            color: "transparent"
            border.width: 0
            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(7)
                VrComboBox {
                    id: sourceFilter
                    Layout.fillWidth: true
                    model: [{text:"Todas as fontes",value:""},{text:"Cursos",value:"curso"},{text:"Biblioteca/Arquivos",value:"biblioteca"}]
                    textRole: "text"
                    onActivated: root.runFilter()
                }
                VrComboBox { id: moduleFilter; Layout.fillWidth: true; model: studio.moduleItems; onActivated: root.runFilter() }
                VrComboBox {
                    id: statusFilter
                    Layout.fillWidth: true
                    model: [{text:"Todas as situações",value:""},{text:"Disponível",value:"available"},{text:"Inscrito",value:"enrolled"},{text:"Baixado",value:"downloaded"},{text:"Pendente",value:"found"},{text:"Revisar",value:"review"},{text:"Indisponível",value:"unavailable"}]
                    textRole: "text"
                    onActivated: root.runFilter()
                }
                VrButton { text: "Limpar"; onClicked: root.clearFilters() }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Text { text: "Classificar seleção como:"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13) }
            VrComboBox { id: videoModule; Layout.preferredWidth: Theme.scaledGeometry(180); model: ["Fiscal", "ADM_FIN_ESTOQUE", "PDV", "Multimodulo", "Revisar"] }
            VrButton { text: "Aplicar módulo"; onClicked: studio.applyVideoModule(root.selectedIds, videoModule.currentText) }
            Item { Layout.fillWidth: true }
            Text { text: root.selectedIds.length ? root.selectedIds.length + " item(ns) selecionado(s)" : ""; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(32)
            radius: Theme.scaledGeometry(7)
            color: frontend.palette.chatSidebar
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(12)
                anchors.rightMargin: Theme.scaledGeometry(5)
                spacing: Theme.scaledGeometry(3)
                Text { Layout.fillWidth: true; text: studio.videoSummary; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                VrIconButton {
                    implicitWidth: Theme.scaledGeometry(26)
                    implicitHeight: Theme.scaledGeometry(26)
                    iconKind: "chevronRight"
                    Accessible.name: "Recolher todas as pastas"
                    onClicked: root.collapsedNodeIds = studio.videoExpandableNodeIds.slice()
                }
                VrIconButton {
                    implicitWidth: Theme.scaledGeometry(26)
                    implicitHeight: Theme.scaledGeometry(26)
                    iconKind: "chevronDown"
                    Accessible.name: "Expandir todas as pastas"
                    onClicked: root.collapsedNodeIds = []
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
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
                        Item { Layout.preferredWidth: Theme.scaledGeometry(28) }
                        Text { Layout.fillWidth: true; text: "Curso, pasta ou vídeo"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                        Text { Layout.preferredWidth: Theme.scaledGeometry(110); text: "Fonte"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                        Text { Layout.preferredWidth: Theme.scaledGeometry(150); text: "Módulo"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                        Text { Layout.preferredWidth: Theme.scaledGeometry(105); text: "Situação"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                        Text { Layout.preferredWidth: Theme.scaledGeometry(92); text: "Download"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                        Text { Layout.preferredWidth: Theme.scaledGeometry(72); text: "Tamanho"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                        Text { Layout.preferredWidth: Theme.scaledGeometry(72); text: "Confiança"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold }
                    }
                }
                ListView {
                    id: videoList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: studio.videoModel
                    onCountChanged: root.ensureInitialCollapse()
                    delegate: Rectangle {
                        id: videoRow
                        required property int index
                        required property string title
                        required property string source
                        required property string module
                        required property string status
                        required property string download
                        required property string size
                        required property string confidence
                        required property string itemId
                        required property int depth
                        required property bool selectable
                        required property string nodeId
                        required property var ancestorIds
                        required property bool expandable
                        readonly property bool selected: root.selectedIds.indexOf(videoRow.itemId) >= 0
                        width: videoList.width
                        height: visible ? 44 : 0
                        visible: root.nodeVisible(videoRow.ancestorIds)
                        color: videoRow.selected ? frontend.palette.selection
                            : index % 2 ? frontend.palette.surfaceRaised : frontend.palette.surface
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.scaledGeometry(8)
                            anchors.rightMargin: Theme.scaledGeometry(8)
                            spacing: Theme.scaledGeometry(6)
                            Item {
                                Layout.preferredWidth: Theme.scaledGeometry(28)
                                Layout.fillHeight: true
                                VrIconButton {
                                    anchors.centerIn: parent
                                    implicitWidth: Theme.scaledGeometry(24)
                                    implicitHeight: Theme.scaledGeometry(24)
                                    visible: videoRow.expandable
                                    iconKind: root.nodeCollapsed(videoRow.nodeId)
                                        ? "chevronRight" : "chevronDown"
                                    iconSize: 14
                                    foreground: frontend.palette.mutedText
                                    Accessible.name: root.nodeCollapsed(videoRow.nodeId)
                                        ? "Expandir pasta" : "Recolher pasta"
                                    onClicked: root.toggleNode(videoRow.nodeId)
                                }
                                VrCheckBox {
                                    anchors.centerIn: parent
                                    implicitWidth: Theme.scaledGeometry(24)
                                    visible: videoRow.selectable
                                    checked: videoRow.selected
                                    onToggled: {
                                        var values = root.selectedIds.slice()
                                        var position = values.indexOf(videoRow.itemId)
                                        if (checked && position < 0) values.push(videoRow.itemId)
                                        else if (!checked && position >= 0) values.splice(position, 1)
                                        root.selectedIds = values
                                    }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                leftPadding: videoRow.depth * 17
                                text: videoRow.title
                                color: frontend.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: videoRow.depth < 2 ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                                TapHandler {
                                    enabled: videoRow.expandable
                                    onTapped: root.toggleNode(videoRow.nodeId)
                                }
                            }
                            Text { Layout.preferredWidth: Theme.scaledGeometry(110); text: videoRow.source; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: Theme.scaledGeometry(150); text: videoRow.module; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: Theme.scaledGeometry(105); text: videoRow.status; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); elide: Text.ElideRight }
                            Text { Layout.preferredWidth: Theme.scaledGeometry(92); text: videoRow.download; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                            Text { Layout.preferredWidth: Theme.scaledGeometry(72); text: videoRow.size; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                            Text { Layout.preferredWidth: Theme.scaledGeometry(72); text: videoRow.confidence; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                        }
                    }
                    Row {
                        anchors.centerIn: parent
                        visible: studio.videoLoading
                        spacing: Theme.scaledGeometry(8)
                        VrLineIcon {
                            width: Theme.scaledGeometry(16)
                            height: Theme.scaledGeometry(16)
                            kind: "auto"
                            foreground: frontend.palette.brandOrange
                        }
                        Text {
                            text: "Carregando inventário…"
                            color: frontend.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                        }
                    }
                    VrEmptyState {
                        anchors.centerIn: parent
                        visible: videoList.count === 0 && !studio.videoLoading
                        title: "Nenhum vídeo encontrado"
                        description: "Inventarie cursos e biblioteca para preencher esta visão."
                        actionText: "Inventariar vídeos"
                        onAction: studio.runVideoAction("scan")
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(74)
            color: "transparent"
            border.width: 0
            ScrollView {
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(10)
                TextArea {
                    readOnly: true
                    text: studio.videoLog.length ? studio.videoLog : "O inventário, as inscrições, os downloads e eventuais falhas aparecerão aqui."
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    wrapMode: TextEdit.Wrap
                    background: Item { }
                }
            }
        }
    }

    Timer { id: videoFilterDelay; interval: 180; onTriggered: root.runFilter() }
}
