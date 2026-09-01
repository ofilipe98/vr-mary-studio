import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    id: root

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

    Connections {
        target: frontend
        function onCurrentPageChanged() {
            root.markVisited()
            if (frontend.currentPage !== 1 && !frontend.reduceMotion)
                pageEntrance.restart()
        }
    }

    Component.onCompleted: root.markVisited()

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
                        rightPadding: 12
                        text: chat.search
                        placeholderText: "Pesquisar conversas"
                        background: Rectangle {
                            radius: 8
                            color: settingsConversationSearch.hovered
                                || settingsConversationSearch.activeFocus
                                ? frontend.palette.chatControl : "transparent"
                            border.width: 1
                            border.color: settingsConversationSearch.activeFocus
                                ? frontend.palette.focus : frontend.palette.chatBorder
                        }
                        onTextChanged: chat.setSearch(text)
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
                }

                Connections {
                    target: chat
                    function onSearchChanged() {
                        if (!settingsConversationSearch.activeFocus)
                            settingsConversationSearch.text = chat.search
                    }
                }

                Button {
                    id: settingsReturnButton
                    objectName: "settingsReturnButton"
                    Layout.fillWidth: true
                    implicitHeight: 36
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
                        radius: 8
                        color: settingsReturnButton.down || settingsReturnButton.hovered
                            ? frontend.palette.chatControl : "transparent"
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 7
                    Layout.rightMargin: 7
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    implicitHeight: 1
                    color: frontend.palette.navDivider
                }

                Repeater {
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

                Item { Layout.fillHeight: true }

                VrIconButton {
                    Layout.alignment: Qt.AlignLeft
                    implicitWidth: 38
                    implicitHeight: 38
                    iconKind: "settings"
                    foreground: frontend.palette.navMuted
                    ToolTip.visible: hovered
                    ToolTip.text: "Configurações"
                    Accessible.name: "Abrir Configurações"
                    onClicked: frontend.setCurrentPage(7)
                }
            }
        }

        Item {
            id: pageViewport
            SplitView.minimumWidth: 720
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
