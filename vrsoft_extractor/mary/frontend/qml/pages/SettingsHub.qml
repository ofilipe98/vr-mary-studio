import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root
    objectName: "settingsHub"

    property string settingsSearch: ""
    property bool syncingSearch: false
    property bool idlePagesPreloaded: false
    readonly property bool settingsActive: frontend.currentPage === 7
    readonly property SettingsPage loadedSettings: settingsPageLoader.item as SettingsPage
    readonly property bool compactSettings: settingsActive && root.width < 980
    readonly property real sidebarBorderOffset: (!compactSettings && settingsNavigation && settingsNavigation.visible)
        ? (settingsNavigation.width + 4)
        : 0
    readonly property bool settingsSearching: settingsActive
        && settingsSearch.trim().length > 0
    readonly property var settingsSearchItems: [
        { title: "Fonte de conhecimento VR", category: "Geral", tab: 0, icon: "folder" },
        { title: "Credenciais Movidesk", category: "Geral", tab: 0, icon: "settings" },
        { title: "Credenciais Wiki Endoo", category: "Geral", tab: 0, icon: "settings" },
        { title: "Repetir sincronização", category: "Geral", tab: 0, icon: "reload" },
        { title: "Diagnóstico", category: "Geral", tab: 0, icon: "context" },
        { title: "Provedores e modelos", category: "Provedores", tab: 1, icon: "models" },
        { title: "Agentes VR Ultra", category: "VR Ultra", tab: 2, icon: "agents" },
        { title: "Modelos dos pesquisadores", category: "VR Ultra", tab: 2, icon: "models" },
        { title: "Perfil especialista sênior", category: "VR Ultra", tab: 2, icon: "settings" },
        { title: "Contexto de código no VR Ultra", category: "VR Ultra", tab: 2, icon: "files" },
        { title: "Catálogo de aplicativos e versões", category: "Aplicativos e versões", tab: 3, icon: "package" },
        { title: "Importação de pacotes e JARs", category: "Aplicativos e versões", tab: 3, icon: "folder" },
        { title: "Descompilação e indexação local de JARs", category: "Aplicativos e versões", tab: 3, icon: "task" },
        { title: "Comparação entre versões", category: "Aplicativos e versões", tab: 3, icon: "edit" },
        { title: "Tema", category: "Aparência", tab: 4, icon: "settings" },
        { title: "Esquema de cores e modo escuro", category: "Aparência", tab: 4, icon: "settings" },
        { title: "Biblioteca de temas e temas customizados", category: "Aparência", tab: 4, icon: "settings" },
        { title: "Importar e exportar temas (JSON)", category: "Aparência", tab: 4, icon: "folder" },
        { title: "Contraste e nitidez visual", category: "Aparência", tab: 4, icon: "edit" },
        { title: "Opacidade de vidro e superfícies translúcidas", category: "Aparência", tab: 4, icon: "settings" },
        { title: "Animações de painéis e movimento", category: "Aparência", tab: 4, icon: "settings" },
        { title: "Fonte da interface", category: "Aparência", tab: 4, icon: "edit" },
        { title: "Tipografia avançada (Interface, Prompt, Código, Terminal)", category: "Aparência", tab: 4, icon: "edit" },
        { title: "Suavização de fontes e quebra de linha (Word wrap)", category: "Aparência", tab: 4, icon: "edit" },
        { title: "Browser e acesso do agente", category: "Browser", tab: 5, icon: "browser" },
        { title: "Projetos arquivados", category: "Projetos arquivados", tab: 6, icon: "archive" },
        { title: "Skills e ferramentas", category: "Skills", tab: 7, icon: "settings" }
    ]
    readonly property var filteredSettings: settingsSearchItems.filter(function(item) {
        var query = root.settingsSearch.trim().toLocaleLowerCase()
        return !query.length
            || item.title.toLocaleLowerCase().indexOf(query) >= 0
            || item.category.toLocaleLowerCase().indexOf(query) >= 0
    })

    Timer {
        interval: 250
        running: frontend.currentPage !== 1 && !root.idlePagesPreloaded
        repeat: false
        onTriggered: {
            root.idlePagesPreloaded = true
            var pages = root.visitedPages.slice()
            pages[6] = true
            root.visitedPages = pages
        }
    }

    readonly property var sections: [
        { title: "Dashboard", page: 0, icon: "nav-dashboard.svg" },
        { title: "Conhecimento", page: 2, icon: "nav-knowledge.svg" },
        { title: "Sincronizações", page: 3, icon: "nav-sync.svg" },
        { title: "Revisão", page: 4, icon: "nav-review.svg" },
        { title: "Vídeos", page: 5, icon: "nav-videos.svg" },
        { title: "Logs", page: 6, icon: "nav-logs.svg" }
    ]

    // Visited pages stay alive: recreating heavy pages (Vídeos, Conhecimento)
    // on every switch added measurable tab-change latency.
    property var visitedPages: []

    function markVisited() {
        var pages = visitedPages.slice()
        pages[frontend.currentPage] = true
        visitedPages = pages
    }

    function syncSearchField() {
        root.syncingSearch = true
        settingsConversationSearch.text = root.settingsActive
            ? root.settingsSearch : chat.search
        root.syncingSearch = false
    }

    function openSetting(tab) {
        frontend.setCurrentPage(7)
        Qt.callLater(function() {
            if (root.loadedSettings)
                root.loadedSettings.openSearchResult(tab)
        })
    }

    function activateSettingSearchResult(index) {
        if (index < 0 || index >= root.filteredSettings.length)
            return false
        root.openSetting(root.filteredSettings[index].tab)
        return true
    }

    Connections {
        target: frontend
        function onCurrentPageChanged() {
            root.markVisited()
            root.syncSearchField()
            if (frontend.currentPage !== 1 && !frontend.reduceMotion)
                pageEntrance.restart()
        }
    }

    Component.onCompleted: {
        root.markVisited()
        root.syncSearchField()
    }

    Rectangle { anchors.fill: parent; color: Theme.palette.chatBackground }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        handle: Rectangle {
            id: splitHandle
            implicitWidth: 7
            color: "transparent"

            // Left slice matches navigation background
            Rectangle {
                anchors.left: parent.left
                anchors.right: centerLine.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                color: Theme.palette.navigationBackground
            }

            // Right slice matches content background
            Rectangle {
                anchors.left: centerLine.right
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                color: Theme.palette.chatBackground
            }

            // Subtle depth gradient along the content edge
            Rectangle {
                anchors.left: centerLine.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 3
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.14) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }

            // Crisp 1px hairline divider
            Rectangle {
                id: centerLine
                objectName: "hubCenterLine"
                anchors.horizontalCenter: parent.horizontalCenter
                width: 1
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                color: SplitHandle.pressed
                    ? Theme.palette.brandOrange
                    : SplitHandle.hovered
                        ? Theme.palette.focus
                        : Theme.palette.chatBorder
                opacity: SplitHandle.pressed ? 1.0 : SplitHandle.hovered ? 0.9 : 1.0

                Behavior on color {
                    enabled: !frontend.reduceMotion
                    ColorAnimation { duration: Theme.fastDuration }
                }
                Behavior on opacity {
                    enabled: !frontend.reduceMotion
                    NumberAnimation { duration: Theme.fastDuration }
                }
            }

            // Interactive grip indicator pill on hover/press
            Rectangle {
                anchors.centerIn: parent
                width: 3
                height: 36
                radius: 1.5
                visible: SplitHandle.hovered || SplitHandle.pressed
                color: SplitHandle.pressed ? Theme.palette.brandOrange : Theme.palette.focus
                opacity: SplitHandle.pressed ? 0.95 : 0.85

                Behavior on opacity {
                    enabled: !frontend.reduceMotion
                    NumberAnimation { duration: Theme.fastDuration }
                }
            }
        }

        Rectangle {
            id: settingsNavigation
            objectName: "settingsNavigation"
            visible: !root.compactSettings
            SplitView.minimumWidth: 220
            SplitView.preferredWidth: 260
            SplitView.maximumWidth: 430
            color: Theme.palette.navigationBackground

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                VrBrandHeader {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 62
                    primaryColor: Theme.palette.navText
                    toggleColor: Theme.palette.navMuted
                    onBrandActivated: frontend.setCurrentPage(1)
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36

                    VrTextField {
                        id: settingsConversationSearch
                        objectName: "settingsConversationSearch"
                        anchors.fill: parent
                        leftPadding: 31
                        rightPadding: 30
                        placeholderText: root.settingsActive
                            ? "Pesquisar configurações" : "Pesquisar conversas"
                        background: Rectangle {
                            radius: 8
                            color: settingsConversationSearch.hovered
                                || settingsConversationSearch.activeFocus
                                ? Theme.palette.chatControl : "transparent"
                            border.width: 1
                            border.color: settingsConversationSearch.activeFocus
                                ? Theme.palette.focus : Theme.palette.chatBorder
                        }
                        onTextChanged: {
                            if (root.syncingSearch)
                                return
                            if (root.settingsActive)
                                root.settingsSearch = text
                            else
                                chat.setSearch(text)
                        }
                    }
                    VrLineIcon {
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        width: 15
                        height: 15
                        kind: "search"
                        foreground: Theme.palette.mutedText
                    }
                    VrIconButton {
                        anchors.right: parent.right
                        anchors.rightMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        visible: settingsConversationSearch.text.length > 0
                        width: 26
                        height: 26
                        iconKind: "close"
                        iconSize: 11
                        foreground: Theme.palette.mutedText
                        ToolTip.visible: hovered
                        ToolTip.text: "Limpar pesquisa"
                        onClicked: settingsConversationSearch.clear()
                    }
                }

                Connections {
                    target: chat
                    function onSearchChanged() {
                        if (!root.settingsActive
                                && !settingsConversationSearch.activeFocus)
                            root.syncSearchField()
                    }
                }

                Rectangle {
                    visible: !root.settingsSearching
                    Layout.fillWidth: true
                    Layout.leftMargin: 7
                    Layout.rightMargin: 7
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    implicitHeight: 1
                    color: Theme.palette.navDivider
                }

                Repeater {
                    visible: !root.settingsSearching
                    model: root.sections
                    delegate: VrNavItem {
                        required property var modelData
                        Layout.fillWidth: true
                        title: modelData.title
                        iconSource: Qt.resolvedUrl("../../../assets/" + modelData.icon)
                        selected: frontend.currentPage === modelData.page
                        compact: false
                        onActivated: frontend.setCurrentPage(modelData.page)
                    }
                }

                ListView {
                    id: settingsSearchResults
                    objectName: "settingsSearchResults"
                    visible: root.settingsSearching
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 4
                    model: root.filteredSettings
                    delegate: Rectangle {
                        id: settingResult
                        required property int index
                        required property var modelData
                        width: settingsSearchResults.width
                        height: 54
                        radius: Theme.radiusSmall
                        color: resultHover.hovered
                            ? Theme.palette.chatControl : "transparent"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 8
                            spacing: 9
                            VrLineIcon {
                                Layout.preferredWidth: 16
                                Layout.preferredHeight: 16
                                kind: settingResult.modelData.icon
                                foreground: Theme.palette.navMuted
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Text {
                                    Layout.fillWidth: true
                                    text: settingResult.modelData.title
                                    color: Theme.palette.navText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: settingResult.modelData.category
                                    color: Theme.palette.navMuted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(10)
                                }
                            }
                        }
                        HoverHandler { id: resultHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            onTapped: root.activateSettingSearchResult(settingResult.index)
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: settingsSearchResults.count === 0
                        width: parent.width - 20
                        text: "Nenhuma configuração encontrada."
                        color: Theme.palette.navMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                    }
                }

                Item {
                    visible: !settingsSearchResults.visible
                    Layout.fillHeight: true
                }

                Button {
                    id: settingsReturnButton
                    objectName: "settingsReturnButton"
                    Layout.fillWidth: true
                    implicitHeight: 38
                    padding: 8
                    hoverEnabled: true
                    Accessible.name: "Retornar ao Chat VR"
                    onClicked: frontend.setCurrentPage(1)
                    contentItem: RowLayout {
                        spacing: 8
                        VrLineIcon {
                            Layout.preferredWidth: 16
                            Layout.preferredHeight: 16
                            kind: "back"
                            foreground: settingsReturnButton.hovered
                                ? Theme.palette.navText : Theme.palette.navMuted
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Retornar"
                            color: settingsReturnButton.hovered
                                ? Theme.palette.navText : Theme.palette.navMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                    background: Rectangle {
                        radius: Theme.radiusSmall
                        color: settingsReturnButton.down || settingsReturnButton.hovered
                            ? Theme.palette.chatControl : "transparent"
                    }
                }
            }
        }

        Item {
            id: pageViewport
            SplitView.minimumWidth: root.compactSettings ? 0 : 720
            SplitView.fillWidth: true

            transform: Translate { id: pageShift; y: 0 }

            SequentialAnimation {
                id: pageEntrance
                PropertyAction { target: pageViewport; property: "opacity"; value: 0.15 }
                PropertyAction { target: pageShift; property: "y"; value: 8 }
                ParallelAnimation {
                    NumberAnimation {
                        target: pageViewport
                        property: "opacity"
                        to: 1.0
                        duration: Theme.motionDuration
                        easing.type: Easing.OutCubic
                    }
                    NumberAnimation {
                        target: pageShift
                        property: "y"
                        to: 0
                        duration: Theme.motionDuration
                        easing.type: Easing.OutCubic
                    }
                }
            }

            // Explicit Loaders (not a Repeater): Repeater delegates get no
            // QObject parent, which disconnects them from window.findChild.
            Loader {
                anchors.fill: parent
                active: root.visitedPages[0] === true
                visible: frontend.currentPage === 0
                sourceComponent: dashboardComponent
            }
            Loader {
                anchors.fill: parent
                active: root.visitedPages[2] === true
                visible: frontend.currentPage === 2
                sourceComponent: knowledgeComponent
            }
            Loader {
                anchors.fill: parent
                active: root.visitedPages[3] === true
                visible: frontend.currentPage === 3
                sourceComponent: syncComponent
            }
            Loader {
                anchors.fill: parent
                active: root.visitedPages[4] === true
                visible: frontend.currentPage === 4
                sourceComponent: reviewComponent
            }
            Loader {
                anchors.fill: parent
                active: root.visitedPages[5] === true
                visible: frontend.currentPage === 5
                sourceComponent: videosComponent
            }
            Loader {
                anchors.fill: parent
                active: root.visitedPages[6] === true
                visible: frontend.currentPage === 6
                sourceComponent: logsComponent
            }
            Loader {
                id: settingsPageLoader
                anchors.fill: parent
                active: root.visitedPages[7] === true
                visible: frontend.currentPage === 7
                sourceComponent: settingsComponent
            }
        }
    }

    Component { id: dashboardComponent; DashboardPreview { } }
    Component { id: knowledgeComponent; KnowledgePage { } }
    Component { id: syncComponent; SyncPage { } }
    Component { id: reviewComponent; ReviewPage { } }
    Component { id: videosComponent; VideosPage { } }
    Component { id: logsComponent; LogsPage { } }
    Component { id: settingsComponent; SettingsPage { } }
}
