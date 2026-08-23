import QtQuick
import QtQuick.Controls
import "pages"
import "theme"

ApplicationWindow {
    id: window

    width: 1480
    height: 900
    minimumWidth: 1120
    minimumHeight: 700
    visible: true
    title: frontend.appName
    color: frontend.palette.background

    Connections {
        target: studio
        function onNavigationRequested(index) { frontend.setCurrentPage(index) }
        function onToastRequested(message, kind) {
            toast.message = message
            toast.kind = kind
            toast.open()
        }
    }

    Connections {
        target: frontend
        function onCurrentPageChanged() {
            if (studio) studio.activatePage(frontend.currentPage)
        }
    }

    Component.onCompleted: {
        if (studio) studio.activatePage(frontend.currentPage)
    }

    Loader {
        id: pageLoader
        anchors.fill: parent
        sourceComponent: frontend.currentPage === 1 ? chatComponent : settingsHubComponent
    }

    Popup {
        id: toast
        property string message: ""
        property string kind: "success"
        x: window.width - width - 24
        y: 20
        width: Math.min(440, window.width - 48)
        height: toastText.implicitHeight + 28
        padding: 14
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        modal: false

        contentItem: Text {
            id: toastText
            text: toast.message
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            wrapMode: Text.WordWrap
        }
        background: Rectangle {
            color: frontend.palette.surfaceRaised
            radius: Theme.radiusPopup
            border.width: 1
            border.color: toast.kind === "error" ? frontend.palette.danger
                : toast.kind === "warning" ? frontend.palette.warning : frontend.palette.success
        }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 120 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 120 } }
        onOpened: toastTimer.restart()
        Timer { id: toastTimer; interval: 4200; onTriggered: toast.close() }
    }

    Component { id: chatComponent; ChatPreview { } }
    Component { id: settingsHubComponent; SettingsHub { } }
}
