pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../theme"

Item {
    id: root
    objectName: "vrTitleBar"
    property Window window: null
    property var chatPage: null
    property var hubPage: null
    implicitHeight: 36

    readonly property bool isChatPage: typeof frontend !== "undefined" && frontend && frontend.currentPage === 1
    readonly property bool isBootstrapping: root.window && root.window.isBootstrapReady === false
    readonly property bool hasSidebar: isBootstrapping ? false : (isChatPage
        ? (root.chatPage && root.chatPage.conversationSidebarVisible && root.chatPage.width >= 760)
        : (root.hubPage ? root.hubPage.sidebarBorderOffset > 0 : ((typeof frontend !== "undefined" && frontend && frontend.currentPage !== 1) && root.window && root.window.width >= 980)))
    readonly property real sidebarWidth: isChatPage
        ? (root.chatPage && root.chatPage.conversationSidebarVisible && root.chatPage.width >= 760
            ? (root.chatPage.sidebarBorderOffset > 0 ? root.chatPage.sidebarBorderOffset : (root.chatPage.sidebarBorderX > 0 ? root.chatPage.sidebarBorderX + 1 : 264))
            : 0)
        : (root.hubPage && root.hubPage.sidebarBorderOffset > 0
            ? root.hubPage.sidebarBorderOffset
            : (hasSidebar ? 264 : 0))
    readonly property real surfaceWidth: isChatPage
        ? (root.chatPage && root.chatPage.surfaceVisible && root.chatPage.width >= 1000
            ? (root.chatPage.surfaceBorderOffset > 0 ? root.chatPage.surfaceBorderOffset : root.chatPage.surfacePanelWidth + 4)
            : 0)
        : 0
    readonly property bool isMaximized: root.window ? (root.window.visibility === Window.Maximized) : false

    // Sidebar split background
    Rectangle {
        id: sidebarBg
        visible: root.hasSidebar && root.sidebarWidth > 0
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.sidebarWidth
        color: root.isChatPage ? Theme.palette.chatSidebar : Theme.palette.navigationBackground

        Rectangle {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: Theme.palette.chatBorder
        }
    }

    // Right panel split background (when surface is visible on Chat page)
    Rectangle {
        id: surfacePanelBg
        visible: root.isChatPage && root.chatPage && root.chatPage.surfaceVisible && root.surfaceWidth > 0
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.surfaceWidth
        color: Theme.palette.chatSidebar

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: Theme.palette.chatBorder
        }
    }

    // Center chat canvas / page background
    Rectangle {
        id: mainCanvasBg
        anchors.left: root.hasSidebar && root.sidebarWidth > 0 ? sidebarBg.right : parent.left
        anchors.right: surfacePanelBg.visible ? surfacePanelBg.left : parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        color: Theme.palette.chatBackground
    }



    // Left brand identity / title
    RowLayout {
        id: brandRow
        anchors.left: parent.left
        anchors.leftMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6

        // Sidebar toggle button (Chat page)
        VrIconButton {
            id: conversationSidebarToggle
            objectName: "conversationSidebarToggle"
            visible: root.isChatPage && !root.isBootstrapping
            implicitWidth: 32
            implicitHeight: 32
            iconKind: "panelLeft"
            iconSize: 16
            focusPolicy: Qt.NoFocus
            foreground: Theme.palette.mutedText
            Accessible.name: (root.chatPage && root.chatPage.conversationSidebarVisible)
                ? "Recolher barra lateral" : "Mostrar conversas"
            onClicked: {
                if (root.chatPage)
                    root.chatPage.conversationSidebarVisible = !root.chatPage.conversationSidebarVisible
            }
        }

        Item {
            width: 16
            height: 16

            Rectangle {
                objectName: "environmentArtwork"
                anchors.fill: parent
                radius: 4
                visible: typeof frontend !== "undefined" && frontend && frontend.environmentStage !== "" && frontend.environmentIdentification === "artwork"
                color: Qt.alpha(Theme.palette.focus, .2)
                border.color: Theme.palette.focus
            }

            Image {
                anchors.fill: parent
                source: (typeof frontend !== "undefined" && frontend && frontend.brandSymbolUrl) ? frontend.brandSymbolUrl : ""
                sourceSize.width: 32
                sourceSize.height: 32
                fillMode: Image.PreserveAspectFit
                smooth: true
            }
        }

        Text {
            text: (typeof frontend !== "undefined" && frontend && frontend.appName) ? frontend.appName : "VR Norte Studio"
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.controlSize
            font.weight: Font.Bold
            renderType: Theme.textRenderType
        }

        Rectangle {
            objectName: "environmentVersionPill"
            visible: typeof frontend !== "undefined" && frontend && frontend.environmentStage !== "" && frontend.environmentIdentification === "pill"
            implicitWidth: stageLabel.implicitWidth + 8
            implicitHeight: 20
            radius: 4
            color: Theme.palette.accentSoft

            Text {
                id: stageLabel
                anchors.centerIn: parent
                text: (typeof frontend !== "undefined" && frontend ? frontend.appVersion : "v0.6.3") + " " + (typeof frontend !== "undefined" && frontend ? frontend.environmentStage : "Dev")
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeMicro
                font.weight: Font.Medium
                renderType: Theme.textRenderType
            }
        }

        Rectangle {
            visible: !(typeof frontend !== "undefined" && frontend && frontend.environmentStage !== "" && frontend.environmentIdentification === "pill")
            implicitWidth: defaultBadge.implicitWidth + 10
            implicitHeight: 20
            radius: 10
            color: Theme.palette.surfaceRaised
            border.width: 1
            border.color: Theme.palette.border

            Text {
                id: defaultBadge
                anchors.centerIn: parent
                text: (typeof frontend !== "undefined" && frontend) ? (frontend.appVersion + " Dev") : "v0.6.3 Dev"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeMicro
                font.weight: Font.Medium
                renderType: Theme.textRenderType
            }
        }
    }

    // Center breadcrumb row (Chat page)
    RowLayout {
        id: breadcrumbRow
        visible: root.isChatPage && root.chatPage !== null
        anchors.left: root.hasSidebar ? sidebarBg.right : brandRow.right
        anchors.leftMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 7

        VrProjectIcon {
            Layout.preferredWidth: 20
            Layout.preferredHeight: 20
            boxSize: 20
            iconSize: 12
            projectLabel: {
                if (!root.chatPage || !root.chatPage.chatBridge) return ""
                var bridge = root.chatPage.chatBridge
                var idx = bridge.currentProjectIndex
                var items = bridge.projectItems
                if (idx > 0 && idx < items.length) return items[idx].label
                return ""
            }
            iconPath: {
                if (!root.chatPage || !root.chatPage.chatBridge) return ""
                var b2 = root.chatPage.chatBridge
                var i2 = b2.currentProjectIndex
                var list2 = b2.projectItems
                if (i2 > 0 && i2 < list2.length) return String(list2[i2].icon || "")
                return ""
            }
            iconEmoji: {
                if (!root.chatPage || !root.chatPage.chatBridge) return ""
                var b3 = root.chatPage.chatBridge
                var i3 = b3.currentProjectIndex
                var list3 = b3.projectItems
                if (i3 > 0 && i3 < list3.length) return String(list3[i3].iconEmoji || list3[i3].icon_emoji || "")
                return ""
            }
            iconKind: {
                if (!root.chatPage || !root.chatPage.chatBridge) return ""
                var b5 = root.chatPage.chatBridge
                var i5 = b5.currentProjectIndex
                var list5 = b5.projectItems
                if (i5 > 0 && i5 < list5.length) return String(list5[i5].iconKind || list5[i5].icon_kind || "")
                return ""
            }
            iconText: {
                if (!root.chatPage || !root.chatPage.chatBridge) return ""
                var b6 = root.chatPage.chatBridge
                var i6 = b6.currentProjectIndex
                var list6 = b6.projectItems
                if (i6 > 0 && i6 < list6.length) return String(list6[i6].iconText || list6[i6].icon_text || "")
                return ""
            }
            iconColor: {
                if (!root.chatPage || !root.chatPage.chatBridge) return ""
                var b4 = root.chatPage.chatBridge
                var i4 = b4.currentProjectIndex
                var list4 = b4.projectItems
                if (i4 > 0 && i4 < list4.length) return String(list4[i4].iconColor || list4[i4].icon_color || "")
                return ""
            }
            isAll: {
                if (!root.chatPage || !root.chatPage.chatBridge) return true
                return !(root.chatPage.chatBridge.currentProjectIndex > 0)
            }
        }

        Text {
            text: {
                if (!root.chatPage || !root.chatPage.chatBridge) return "Projeto"
                var bridge = root.chatPage.chatBridge
                var idx = bridge.currentProjectIndex
                var items = bridge.projectItems
                if (idx > 0 && idx < items.length) return items[idx].label
                return "Projeto"
            }
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.controlSize
            font.weight: Font.DemiBold
            renderType: Theme.textRenderType
            elide: Text.ElideRight
            Layout.maximumWidth: 160
        }

        Text {
            text: "/"
            color: Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeCaption
            renderType: Theme.textRenderType
        }

        Text {
            text: (root.chatPage && root.chatPage.chatBridge && root.chatPage.chatBridge.selectedTitle)
                ? root.chatPage.chatBridge.selectedTitle : "Nova conversa"
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.controlSize
            font.weight: Font.DemiBold
            renderType: Theme.textRenderType
            elide: Text.ElideRight
            Layout.maximumWidth: Math.max(120, root.width - 680)
        }
    }

    // Draggable middle area
    Item {
        id: dragArea
        anchors.left: breadcrumbRow.visible ? breadcrumbRow.right : brandRow.right
        anchors.right: rightActionsRow.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: 10

        DragHandler {
            target: null
            grabPermissions: TapHandler.CanTakeOverFromAnything
            onActiveChanged: {
                if (active && root.window && !root.isMaximized) {
                    root.window.startSystemMove()
                }
            }
        }

        TapHandler {
            onDoubleTapped: {
                if (!root.window) return
                if (root.isMaximized)
                    root.window.showNormal()
                else
                    root.window.showMaximized()
            }
        }
    }

    // Right actions (Chat controls: subagents, copy, right panel expand/retract)
    RowLayout {
        id: rightActionsRow
        anchors.right: windowControlsRow.left
        anchors.verticalCenter: parent.verticalCenter
        anchors.rightMargin: 4
        spacing: 4

        VrButton {
            visible: root.isChatPage
                && root.chatPage && root.chatPage.chatBridge && root.chatPage.chatBridge.agentItems && root.chatPage.chatBridge.agentItems.length > 0
            implicitHeight: 26
            text: "Subagentes · " + (root.chatPage && root.chatPage.chatBridge && root.chatPage.chatBridge.agentItems ? root.chatPage.chatBridge.agentItems.length : 0)
            variant: "ghost"
            onClicked: {
                if (root.chatPage) {
                    root.chatPage.openSurface(5)
                    if (root.chatPage.selectedAgentIndex < 0) root.chatPage.selectedAgentIndex = 0
                }
            }
        }

        VrIconButton {
            id: surfaceExpandButton
            objectName: "surfaceToggleButton"
            visible: root.isChatPage && !root.isBootstrapping
            implicitWidth: 32
            implicitHeight: 32
            iconSize: 16
            iconKind: "panelRight"
            focusPolicy: Qt.NoFocus
            foreground: (root.chatPage && root.chatPage.surfaceVisible)
                ? Theme.palette.brandOrange : Theme.palette.mutedText
            Accessible.name: (root.chatPage && root.chatPage.surfaceVisible)
                ? "Recolher painel direito" : "Expandir painel direito"
            onClicked: {
                if (root.chatPage)
                    root.chatPage.surfaceVisible = !root.chatPage.surfaceVisible
            }
        }
    }

    // Right window controls (Minimize, Maximize/Restore, Close)
    RowLayout {
        id: windowControlsRow
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        spacing: 0

        // Minimize
        Rectangle {
            id: minBtn
            width: 46
            height: parent.height
            color: minHover.hovered ? Theme.palette.chatControl : "transparent"

            Rectangle {
                anchors.centerIn: parent
                width: 10
                height: 1
                color: Theme.palette.text
            }

            HoverHandler { id: minHover }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.ArrowCursor
                onClicked: if (root.window) root.window.showMinimized()
            }
        }

        // Maximize / Restore
        Rectangle {
            id: maxBtn
            width: 46
            height: parent.height
            color: maxHover.hovered ? Theme.palette.chatControl : "transparent"

            // Restored icon (two overlapping squares)
            Item {
                anchors.centerIn: parent
                width: 10
                height: 10
                visible: root.isMaximized

                Rectangle {
                    x: 2; y: 0
                    width: 7; height: 7
                    color: "transparent"
                    border.width: 1
                    border.color: Theme.palette.text
                }
                Rectangle {
                    x: 0; y: 2
                    width: 7; height: 7
                    color: maxHover.hovered ? Theme.palette.chatControl : (surfacePanelBg.visible ? Theme.palette.chatSidebar : Theme.palette.chatBackground)
                    border.width: 1
                    border.color: Theme.palette.text
                }
            }

            // Maximized icon (single square)
            Rectangle {
                anchors.centerIn: parent
                width: 10
                height: 10
                visible: !root.isMaximized
                color: "transparent"
                border.width: 1
                border.color: Theme.palette.text
            }

            HoverHandler { id: maxHover }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.ArrowCursor
                onClicked: {
                    if (!root.window) return
                    if (root.isMaximized)
                        root.window.showNormal()
                    else
                        root.window.showMaximized()
                }
            }
        }

        // Close
        Rectangle {
            id: closeBtn
            width: 46
            height: parent.height
            color: closeHover.hovered ? "#E81123" : "transparent"

            Canvas {
                id: closeIconCanvas
                anchors.centerIn: parent
                width: 10
                height: 10
                renderTarget: Canvas.FramebufferObject
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = closeHover.hovered ? "#FFFFFF" : Theme.palette.text
                    ctx.lineWidth = 1.0
                    ctx.beginPath()
                    ctx.moveTo(1.0, 1.0); ctx.lineTo(9.0, 9.0)
                    ctx.moveTo(9.0, 1.0); ctx.lineTo(1.0, 9.0)
                    ctx.stroke()
                }
                Connections {
                    target: closeHover
                    function onHoveredChanged() { closeIconCanvas.requestPaint() }
                }
                Connections {
                    target: Theme
                    function onPaletteChanged() { closeIconCanvas.requestPaint() }
                }
            }

            HoverHandler { id: closeHover }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.ArrowCursor
                onClicked: if (root.window) root.window.close()
            }
        }
    }
}
