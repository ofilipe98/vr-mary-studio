import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "pages"
import "theme"
import "components"

ApplicationWindow {
    id: window
    flags: Qt.Window | Qt.FramelessWindowHint

    // QHD and 4K monitors: grow with the screen, capped for comfortable use.
    width: Math.max(minimumWidth, Math.min(Screen.desktopAvailableWidth * 0.88, 1760))
    height: Math.max(minimumHeight, Math.min(Screen.desktopAvailableHeight * 0.86, 1120))
    minimumWidth: 390
    minimumHeight: 520
    visible: true
    title: frontend.appName
    color: "transparent"
    font.family: Theme.fontFamily
    font.pixelSize: Theme.bodySize

    Shortcut { sequences: ["Ctrl++", "Ctrl+="]; onActivated: frontend.stepUiScale(1) }
    Shortcut { sequence: "Ctrl+-"; onActivated: frontend.stepUiScale(-1) }
    Shortcut { sequence: "Ctrl+0"; onActivated: frontend.stepUiScale(0) }

    Binding { target: Theme; property: "viewportWidth"; value: window.width }
    Binding { target: Theme; property: "viewportHeight"; value: window.height }

    // Pages stay alive after the first visit: recreating ChatPreview on every
    // switch was the dominant tab-change cost (measured at 40-110 ms).
    property bool chatVisited: frontend.currentPage === 1
    property bool hubVisited: frontend.currentPage !== 1

    readonly property bool isBootstrapReady: typeof bootstrap === "undefined" || !bootstrap || bootstrap.isReady
    readonly property bool isSetupActive: typeof bootstrap !== "undefined" && bootstrap && bootstrap.isSetupActive

    onIsBootstrapReadyChanged: {
        if (isBootstrapReady && typeof studio !== "undefined" && studio) {
            studio.activatePage(frontend.currentPage)
        }
    }

    Connections {
        target: typeof studio !== "undefined" ? studio : null
        function onNavigationRequested(index) { frontend.setCurrentPage(index) }
        function onToastRequested(message, kind) {
            toast.message = message
            toast.kind = kind
            toast.open()
        }
    }

    Connections {
        target: typeof bootstrap !== "undefined" ? bootstrap : null
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
            if (window.isBootstrapReady && typeof studio !== "undefined" && studio) studio.activatePage(frontend.currentPage)
        }
    }

    Component.onCompleted: {
        if (window.isBootstrapReady && typeof studio !== "undefined" && studio) studio.activatePage(frontend.currentPage)
    }

    Rectangle {
        id: windowRoot
        anchors.fill: parent
        radius: (window.visibility === Window.Maximized || window.visibility === Window.FullScreen) ? 0 : 10
        color: Theme.palette.background
        border.width: (window.visibility === Window.Maximized || window.visibility === Window.FullScreen) ? 0 : 1
        border.color: Theme.palette.chatBorder
        clip: true

        VrTitleBar {
            id: titleBar
            window: window
            chatPage: chatLoader.item
            hubPage: hubLoader.item
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            z: 9999
        }

        Loader {
            id: setupLoader
            objectName: "setupLoader"
            anchors.top: titleBar.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            active: window.isSetupActive
            visible: active
            source: "pages/StartupSetupPage.qml"
        }

        Loader {
            id: loadingLoader
            objectName: "loadingLoader"
            anchors.top: titleBar.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            active: !window.isBootstrapReady && !window.isSetupActive
            visible: active
            source: "pages/StartupLoadingPage.qml"
        }

        Loader {
            id: chatLoader
            anchors.top: titleBar.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            active: window.isBootstrapReady && (window.chatVisited || frontend.currentPage === 1)
            visible: window.isBootstrapReady && active && frontend.currentPage === 1
            opacity: frontend.currentPage === 1 ? 1 : 0
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
            anchors.top: titleBar.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            active: window.isBootstrapReady && (window.hubVisited || frontend.currentPage !== 1)
            visible: window.isBootstrapReady && active && frontend.currentPage !== 1
            opacity: frontend.currentPage !== 1 ? 1 : 0
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
    }

    VrResizeBorders {
        window: window
    }

    Popup {
        id: toast
        property string message: ""
        property string kind: "success"
        x: window.width - width - 24
        y: titleBar.height + 12
        width: Math.min(440, window.width - 48)
        height: toastText.implicitHeight + 28
        padding: 14
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        modal: false

        contentItem: Text {
            id: toastText
            text: toast.message
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            wrapMode: Text.WordWrap
        }
        background: Rectangle {
            color: Theme.palette.surfaceRaised
            radius: Theme.radiusPopup
            border.width: 1
            border.color: toast.kind === "error" ? Theme.palette.danger
                : toast.kind === "warning" ? Theme.palette.warning : Theme.palette.success
        }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 120 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 120 } }
        onOpened: toastTimer.restart()
        Timer { id: toastTimer; interval: 4200; onTriggered: toast.close() }
    }

    Component {
        id: chatComponent
        ChatPreview {
            chatBridge: chat
            studioBridge: studio
            frontendBridge: frontend
        }
    }
    Component { id: settingsHubComponent; SettingsHub { } }
}
