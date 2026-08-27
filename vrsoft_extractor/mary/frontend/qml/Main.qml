import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "pages"
import "theme"

ApplicationWindow {
    id: window

    // QHD and 4K monitors: grow with the screen, capped for comfortable use.
    width: Math.max(minimumWidth, Math.min(Screen.desktopAvailableWidth * 0.88, 1760))
    height: Math.max(minimumHeight, Math.min(Screen.desktopAvailableHeight * 0.86, 1120))
    minimumWidth: 1120
    minimumHeight: 700
    visible: true
    title: frontend.appName
    color: frontend.palette.background

    // Pages stay alive after the first visit: recreating ChatPreview on every
    // switch was the dominant tab-change cost (measured at 40-110 ms).
    property bool chatVisited: frontend.currentPage === 1
    property bool hubVisited: frontend.currentPage !== 1

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
            if (frontend.currentPage === 1) chatVisited = true
            else hubVisited = true
            if (studio) studio.activatePage(frontend.currentPage)
        }
    }

    Component.onCompleted: {
        if (studio) studio.activatePage(frontend.currentPage)
    }

    Loader {
        id: chatLoader
        anchors.fill: parent
        active: window.chatVisited
        visible: active && frontend.currentPage === 1
        opacity: frontend.currentPage === 1 ? 1 : 0.72
        sourceComponent: chatComponent

        transform: Translate {
            y: frontend.currentPage === 1 ? 0 : Theme.motionDistance
            Behavior on y {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.pageDuration; easing.type: Easing.OutCubic }
            }
        }
        Behavior on opacity {
            enabled: !frontend.reduceMotion
            NumberAnimation { duration: Theme.pageDuration; easing.type: Easing.OutCubic }
        }
    }

    Loader {
        id: hubLoader
        anchors.fill: parent
        active: window.hubVisited
        visible: active && frontend.currentPage !== 1
        opacity: frontend.currentPage !== 1 ? 1 : 0.72
        sourceComponent: settingsHubComponent

        transform: Translate {
            y: frontend.currentPage !== 1 ? 0 : Theme.motionDistance
            Behavior on y {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.pageDuration; easing.type: Easing.OutCubic }
            }
        }
        Behavior on opacity {
            enabled: !frontend.reduceMotion
            NumberAnimation { duration: Theme.pageDuration; easing.type: Easing.OutCubic }
        }
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
