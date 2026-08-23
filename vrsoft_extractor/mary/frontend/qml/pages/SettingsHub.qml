import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

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

                VrNavItem {
                    Layout.fillWidth: true
                    title: "Chat VR"
                    iconSource: frontend.navigationItems[1].icon
                    selected: false
                    compact: false
                    onActivated: frontend.setCurrentPage(1)
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

        Loader {
            SplitView.minimumWidth: 720
            SplitView.fillWidth: true
            sourceComponent: {
                switch (frontend.currentPage) {
                case 0: return dashboardComponent
                case 2: return knowledgeComponent
                case 3: return syncComponent
                case 4: return reviewComponent
                case 5: return videosComponent
                case 6: return logsComponent
                case 7: return settingsComponent
                }
                return settingsComponent
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
