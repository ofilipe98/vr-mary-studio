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
    readonly property bool compactProviders: settingsActive && loadedSettings
        && loadedSettings.tabIndex === 1 && root.width < 980
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
        { title: "Análise de código e JARs", category: "VR Ultra", tab: 2, icon: "files" },
        { title: "Diretório dos JARs", category: "VR Ultra", tab: 2, icon: "folder" },
        { title: "Processamento local do índice", category: "VR Ultra", tab: 2, icon: "task" },
        { title: "Tema", category: "Aparência", tab: 3, icon: "settings" },
        { title: "Fonte e escala da interface", category: "Aparência", tab: 3, icon: "edit" },
        { title: "Browser e acesso do agente", category: "Browser", tab: 4, icon: "browser" },
        { title: "Projetos arquivados", category: "Projetos arquivados", tab: 5, icon: "archive" }
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

    Rectangle { anchors.fill: parent; color: frontend.palette.background }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        handle: Rectangle {
            implicitWidth: 5
            color: SplitHandle.hovered || SplitHandle.pressed
                ? frontend.palette.focus : frontend.palette.chatDivider
            opacity: SplitHandle.hovered || SplitHandle.pressed ? 0.75 : 0.45
        }

        Rectangle {
            objectName: "settingsNavigation"
            visible: !root.compactProviders
            SplitView.minimumWidth: 220
            SplitView.preferredWidth: 260
            SplitView.maximumWidth: 430
            color: frontend.palette.navigationBackground

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                VrBrandHeader {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 62
                    primaryColor: frontend.palette.navText
                    toggleColor: frontend.palette.navMuted
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
                                ? frontend.palette.chatControl : "transparent"
                            border.width: 1
                            border.color: settingsConversationSearch.activeFocus
                                ? frontend.palette.focus : frontend.palette.chatBorder
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
                        foreground: frontend.palette.mutedText
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
                        foreground: frontend.palette.mutedText
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
                    color: frontend.palette.navDivider
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
                            ? frontend.palette.chatControl : "transparent"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 8
                            spacing: 9
                            VrLineIcon {
                                Layout.preferredWidth: 16
                                Layout.preferredHeight: 16
                                kind: settingResult.modelData.icon
                                foreground: frontend.palette.navMuted
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Text {
                                    Layout.fillWidth: true
                                    text: settingResult.modelData.title
                                    color: frontend.palette.navText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: settingResult.modelData.category
                                    color: frontend.palette.navMuted
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
                        color: frontend.palette.navMuted
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
                                ? frontend.palette.navText : frontend.palette.navMuted
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Retornar"
                            color: settingsReturnButton.hovered
                                ? frontend.palette.navText : frontend.palette.navMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                    background: Rectangle {
                        radius: Theme.radiusSmall
                        color: settingsReturnButton.down || settingsReturnButton.hovered
                            ? frontend.palette.chatControl : "transparent"
                    }
                }
            }
        }

        Item {
            id: pageViewport
            SplitView.minimumWidth: root.compactProviders ? 0 : 720
            SplitView.fillWidth: true

            transform: Translate { id: pageShift; y: 0 }

            SequentialAnimation {
                id: pageEntrance
                PropertyAction { target: pageViewport; property: "opacity"; value: 0.94 }
                PropertyAction { target: pageShift; property: "y"; value: Theme.motionDistance }
                ParallelAnimation {
                    NumberAnimation {
                        target: pageViewport
                        property: "opacity"
                        to: 1
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
