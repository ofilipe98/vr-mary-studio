import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models
import "../components"
import "../theme"

Item {
    id: root
    objectName: "chatPage"
    component ProjectMenuEntry: MenuItem {
        id: entry
        implicitHeight: 34
        contentItem: Text {
            text: entry.text
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 6
            color: entry.highlighted ? Theme.palette.chatControl : "transparent"
        }
    }
    property bool conversationSidebarVisible: width >= 1000
    property bool surfaceVisible: false
    property int surfaceIndex: 0
    property int displayedSurfaceIndex: 0
    property var openSurfaceTabs: []
    property bool activityExpanded: false
    property bool taskBarExpanded: false
    property bool taskBarDismissed: false
    property bool previousTurnRunning: false
    property bool copyFeedbackVisible: false
    readonly property var surfaceTabs: [
        { title: "Navegador", kind: "browser", page: 1, description: "Abrir uma aplicação local ou URL." },
        { title: "Terminal", kind: "terminal", page: 2, description: "Executar comandos neste projeto." },
        { title: "Arquivos", kind: "files", page: 3, description: "Navegar pelos arquivos do projeto." },
        { title: "Contexto", kind: "context", page: 4, description: "Consultar arquivos e contexto local." },
        { title: "Agentes", kind: "agents", page: 5, description: "Acompanhar subagentes e saídas." }
    ]
    property var approvalPayload: ({})
    property var composerSuggestions: []
    property var surfaceFiles: []
    property var expandedFileFolders: ({})
    property string surfaceFilePath: ""
    property string surfaceFilePreview: ""
    property var contextItems: []
    property int selectedAgentIndex: -1
    property string pendingBrowserAddress: ""
    property bool composerDropActive: false
    property real clockNow: Date.now() / 1000
    property var expertProfiles: [
        { key: "senior", label: "Sênior", icon: "expertSenior" },
        { key: "support", label: "Suporte", icon: "expertSupport" },
        { key: "implementation", label: "Implantação", icon: "expertImplementation" }
    ]
    property real expertReveal: chat.vrMode !== "off" ? 1.0 : 0.0
    readonly property real expertStripHeight: 42 * expertReveal
    property string addProjectView: "sources"
    property bool projectSettingsVisible: false
    property int projectSettingsIndex: -1
    property string projectSettingsName: ""
    property string projectSettingsPath: ""
    property string projectSettingsIconPath: ""
    property real conversationSidebarWidth: conversationSidebarVisible ? (width < 760 ? 210 : 244) : 0
    property real surfacePanelWidth: surfaceVisible ? 430 : 0
    readonly property var addProjectSources: [
        { key: "local", title: "Local folder", description: "Browse a folder on disk", icon: "folder", enabled: true, badge: "" },
        { key: "git", title: "Git URL", description: "Clone from a remote URL", icon: "models", enabled: false, badge: "Em breve" },
        { key: "github", title: "GitHub repository", description: "Clone GitHub owner/repo", icon: "models", enabled: false, badge: "Em breve" },
        { key: "azure", title: "Azure DevOps repository", description: "Clone Azure DevOps project/repository", icon: "models", enabled: false, badge: "Configurar" },
        { key: "bitbucket", title: "Bitbucket repository", description: "Clone Bitbucket workspace/repository", icon: "models", enabled: false, badge: "Configurar" },
        { key: "gitlab", title: "GitLab repository", description: "Clone GitLab group/project", icon: "models", enabled: false, badge: "Configurar" }
    ]

    Behavior on conversationSidebarWidth {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
    }
    Behavior on surfacePanelWidth {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
    }
    Behavior on expertReveal {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
    }

    onSurfaceIndexChanged: {
        if (frontend.reduceMotion || !root.surfaceVisible) {
            surfaceSwitch.stop()
            root.displayedSurfaceIndex = root.surfaceIndex
            surfaceStack.opacity = 1
            surfaceShift.x = 0
        } else {
            surfaceSwitch.restart()
        }
    }

    Rectangle { anchors.fill: parent; color: Theme.palette.chatBackground }

    Connections {
        target: chat
        function onApprovalRequested(payload) {
            root.approvalPayload = payload
            approvalDialog.open()
        }
        function onStateChanged() {
            if (chat.turnRunning && !root.previousTurnRunning) {
                root.taskBarDismissed = false
                root.taskBarExpanded = false
                root.activityExpanded = false
            }
            root.previousTurnRunning = chat.turnRunning
        }
        function onMessageCopied(_content) {
            root.copyFeedbackVisible = true
            copyFeedbackTimer.restart()
        }
        function onDraftRestored(text) {
            composerInput.text = text
            composerInput.cursorPosition = composerInput.length
        }
        function onBrowserNavigationRequested(address) {
            if (!frontend.browserAgentAccess || !frontend.browserAutoShowPreview)
                return
            root.openSurface(1)
            root.navigateBrowser(address)
        }
        function onProjectsChanged() {
            root.syncOpenProjectSettings()
        }
    }

    Connections {
        target: studio
        function onProvidersChanged() { chat.refreshModels() }
    }

    Component.onCompleted: {
        root.previousTurnRunning = chat.turnRunning
        // Finish constructing delegates before refreshModels emits stateChanged.
        Qt.callLater(chat.refreshModels)
    }

    Timer {
        interval: 1000
        running: root.visible && chat.turnRunning
        repeat: true
        onTriggered: root.clockNow = Date.now() / 1000
    }

    Rectangle {
        anchors.fill: parent
        z: 30
        visible: root.width < 760 && root.conversationSidebarVisible
        color: "#80000000"
        MouseArea { anchors.fill: parent; onClicked: root.conversationSidebarVisible = false }
    }

    SplitView {
        id: mainSplit
        anchors.fill: parent
        orientation: Qt.Horizontal

        handle: Rectangle {
            implicitWidth: 5
            color: SplitHandle.hovered || SplitHandle.pressed
                ? Theme.palette.focus : Theme.palette.chatDivider
            opacity: SplitHandle.hovered || SplitHandle.pressed ? 0.75 : 0.35
        }

        Rectangle {
            id: conversationSidebar
            parent: root.width < 760 ? root : mainSplit
            z: root.width < 760 ? 40 : 0
            width: root.conversationSidebarWidth
            height: root.height
            objectName: "conversationSidebar"
            visible: root.conversationSidebarWidth > 0.5
            opacity: root.conversationSidebarVisible ? 1 : 0
            SplitView.minimumWidth: 0
            SplitView.preferredWidth: root.conversationSidebarWidth
            SplitView.maximumWidth: root.conversationSidebarWidth > 0.5 ? 430 : 0
            color: Theme.palette.chatSidebar
            transform: Translate {
                x: root.conversationSidebarVisible ? 0 : -Theme.motionDistance
                Behavior on x {
                    enabled: !frontend.reduceMotion
                    NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
                }
            }
            Behavior on opacity {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
            }
            Rectangle { anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right; width: 1; color: Theme.palette.chatDivider }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                VrBrandHeader {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    showToggle: false
                    onBrandActivated: frontend.setCurrentPage(1)
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 5

                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 36

                        VrTextField {
                            id: conversationSearch
                            objectName: "conversationSearch"
                            anchors.fill: parent
                            leftPadding: 31
                            rightPadding: 25
                            placeholderText: "Pesquisar conversas"
                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: conversationSearch.hovered
                                    || conversationSearch.activeFocus
                                    ? Theme.palette.chatControl
                                    : Theme.palette.surfaceRaised
                                border.width: 1
                                border.color: conversationSearch.activeFocus
                                    ? Theme.palette.focus : Theme.palette.border
                            }
                            onTextChanged: searchDelay.restart()
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
                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 9
                            anchors.verticalCenter: parent.verticalCenter
                            text: "/"
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(10)
                        }
                    }
                    VrIconButton {
                        objectName: "newChatButton"
                        implicitWidth: 32
                        implicitHeight: 32
                        iconKind: "newChat"
                        foreground: Theme.palette.mutedText
                        ToolTip.visible: hovered
                        ToolTip.text: "Nova conversa"
                        Accessible.name: "Nova conversa"
                        onClicked: {
                            root.projectSettingsVisible = false
                            conversationSearch.clear()
                            chat.saveCurrentDraft(composerInput.text)
                            chat.startNewChat()
                            composerInput.clear()
                            Qt.callLater(function() {
                                newChatProjectPopup.open()
                            })
                        }
                        background: Rectangle {
                            radius: 8
                            color: parent.down || parent.hovered
                                ? Theme.palette.chatControl : "transparent"
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    VrProjectSelector {
                        id: projectSelector
                        objectName: "projectSelector"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        model: chat.projectItems
                        currentIndex: chat.currentProjectIndex
                        popupObjectName: "projectSelectorMenu"
                        onActivated: index => {
                            root.projectSettingsVisible = false
                            chat.setProject(index)
                        }
                        onSettingsRequested: index => root.openProjectSettings(index)
                    }
                    VrIconButton {
                        id: addProjectButton
                        objectName: "addProjectButton"
                        implicitWidth: 34
                        implicitHeight: 34
                        iconKind: "plus"
                        foreground: Theme.palette.mutedText
                        ToolTip.visible: hovered
                        ToolTip.text: "Adicionar projeto"
                        onClicked: {
                            root.addProjectView = "sources"
                            addProjectSearch.clear()
                            addProjectPopup.open()
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 3
                    Layout.bottomMargin: -2
                    spacing: 7
                    Text {
                        text: "Chats"
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(10)
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: Theme.palette.chatDivider
                        opacity: 0.6
                    }
                }

                ListView {
                    id: conversationList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    reuseItems: true
                    cacheBuffer: 240
                    spacing: 3
                    model: chat.conversations
                    currentIndex: chat.selectedIndex
                    ScrollBar.vertical: VrScrollBar { }
                    section.property: "section"
                    section.criteria: ViewSection.FullString
                    section.delegate: Rectangle {
                        required property string section
                        width: conversationList.width
                        height: 26
                        color: "transparent"
                        RowLayout {
                            anchors.fill: parent
                            spacing: 7
                            Text { text: section; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); font.weight: Font.DemiBold }
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.palette.chatDivider; opacity: 0.6 }
                        }
                    }
                    delegate: Rectangle {
                        id: conversationItem
                        objectName: "conversationItem"
                        required property int index
                        required property string conversationId
                        required property string title
                        required property string provider
                        required property string modelName
                        required property string status
                        required property bool running
                        required property string projectLabel
                        required property string updatedAt
                        required property bool editing
                        required property bool pinned
                        required property real startedAtEpoch
                        width: conversationList.width
                        height: 78
                        radius: 8
                        color: chat.selectedIndex === index ? Theme.palette.selection
                            : itemHover.hovered ? Theme.palette.chatControl : "transparent"
                        ColumnLayout {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            anchors.topMargin: 6
                            anchors.bottomMargin: 6
                            spacing: 2

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 5
                                VrLineIcon {
                                    Layout.preferredWidth: 14
                                    Layout.preferredHeight: 14
                                    kind: conversationItem.editing ? "edit" : "folder"
                                    foreground: conversationItem.editing
                                        ? "#F3C74E" : Theme.palette.mutedText
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: conversationItem.projectLabel
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(9)
                                    elide: Text.ElideRight
                                }
                                VrLineIcon {
                                    visible: conversationItem.pinned && !conversationItem.running
                                    Layout.preferredWidth: 13
                                    Layout.preferredHeight: 13
                                    kind: "pin"
                                    foreground: Theme.palette.brandOrange
                                }
                                Item {
                                    visible: conversationItem.running
                                    Layout.preferredWidth: 14
                                    Layout.preferredHeight: 14
                                    Canvas {
                                        anchors.fill: parent
                                        onPaint: {
                                            var ctx = getContext("2d")
                                            ctx.reset(); ctx.lineWidth = 2; ctx.lineCap = "round"
                                            ctx.strokeStyle = "#18A8E8"
                                            ctx.beginPath(); ctx.arc(width / 2, height / 2, 5,
                                                -Math.PI / 2, Math.PI * 0.85); ctx.stroke()
                                        }
                                        RotationAnimator on rotation {
                                            running: conversationItem.running && !frontend.reduceMotion
                                            loops: Animation.Infinite
                                            from: 0; to: 360; duration: 1100
                                        }
                                    }
                                }
                                Text {
                                    text: conversationItem.running
                                        ? "Trabalhando " + root.elapsedFromEpoch(conversationItem.startedAtEpoch)
                                        : root.relativeAge(conversationItem.updatedAt)
                                    color: conversationItem.running ? "#18A8E8" : Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(9)
                                    font.weight: conversationItem.running ? Font.DemiBold : Font.Normal
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: conversationItem.title
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 5
                                Text {
                                    Layout.fillWidth: true
                                    text: conversationItem.modelName
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(9)
                                    elide: Text.ElideRight
                                }
                                Rectangle {
                                    visible: !conversationItem.editing
                                    Layout.preferredWidth: 6
                                    Layout.preferredHeight: 6
                                    radius: 3
                                    color: conversationItem.running ? "#18A8E8"
                                        : conversationItem.status === "error" ? Theme.palette.danger
                                        : Theme.palette.success
                                }
                                VrProviderIcon {
                                    Layout.preferredWidth: 13
                                    Layout.preferredHeight: 13
                                    provider: conversationItem.provider.toLowerCase()
                                }
                            }
                        }
                        HoverHandler { id: itemHover }
                        TapHandler {
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onTapped: function(eventPoint, button) {
                                if (button === Qt.RightButton) {
                                    var menuPoint = conversationItem.mapToItem(
                                        root, eventPoint.position.x, eventPoint.position.y)
                                    root.openConversationMenu(
                                        conversationItem.conversationId, menuPoint.x, menuPoint.y)
                                } else
                                    root.activateConversation(conversationItem.conversationId)
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: !chat.hasConversations
                        width: parent.width - 20
                        text: conversationSearch.text ? "Nenhuma conversa encontrada." : "Nenhum chat iniciado."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                    }
                }

                VrMiddleAutoScroller {
                    objectName: "conversationAutoScroller"
                    parent: conversationSidebar
                    x: conversationList.mapToItem(conversationSidebar, 0, 0).x
                    y: conversationList.mapToItem(conversationSidebar, 0, 0).y
                    width: conversationList.width
                    height: conversationList.height
                    target: conversationList
                    enabled: conversationList.count > 0
                    z: 40
                }

                VrIconButton {
                    objectName: "chatSettingsButton"
                    Layout.alignment: Qt.AlignLeft
                    implicitWidth: 38
                    implicitHeight: 38
                    iconKind: "settings"
                    foreground: Theme.palette.mutedText
                    ToolTip.visible: hovered
                    ToolTip.text: "Configurações"
                    Accessible.name: "Abrir Configurações"
                    onClicked: frontend.setCurrentPage(7)
                }
            }
        }

        Item {
            id: chatMain
            SplitView.minimumWidth: 320
            SplitView.fillWidth: true

            VrChatHeader {
                id: chatHeader
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                sidebarVisible: root.conversationSidebarVisible
                panelVisible: root.surfaceVisible
                hasMessages: messageList.count > 0
                title: chat.selectedTitle
                projectLabel: chat.currentProjectIndex > 0 && chat.currentProjectIndex < chat.projectItems.length
                    ? chat.projectItems[chat.currentProjectIndex].label : "Projeto"
                agentCount: chat.agentItems.length
                onToggleSidebar: root.conversationSidebarVisible = !root.conversationSidebarVisible
                onCopyConversation: chat.copyConversation()
                onShowAgents: {
                    root.openSurface(5)
                    if (root.selectedAgentIndex < 0) root.selectedAgentIndex = 0
                }
                onShowPanel: root.surfaceVisible = true
            }

            Flickable {
                id: messageList
                objectName: "messageList"
                readonly property int count: messageRepeater.count
                contentWidth: width
                contentHeight: messageColumn.height
                flickableDirection: Flickable.VerticalFlick
                boundsBehavior: Flickable.StopAtBounds
                function positionViewAtEnd() {
                    contentY = Math.max(0, contentHeight - height)
                }
                property bool followTail: true
                property bool holdingReader: false
                property real readerY: 0
                function beginManualScroll() {
                    wheelAnimation.stop()
                    followTail = false
                    holdingReader = false
                    readerTimer.stop()
                    tailTimer.stop()
                }
                function preserveReader() {
                    if (followTail || moving || dragging || wheelAnimation.running || messageScrollBar.pressed) return
                    if (!holdingReader) readerY = contentY
                    holdingReader = true
                    readerTimer.restart()
                    Qt.callLater(restoreReader)
                }
                function restoreReader() {
                    if (holdingReader && !followTail && !moving && !wheelAnimation.running && !messageScrollBar.pressed)
                        contentY = readerY
                }
                Timer {
                    id: readerTimer
                    interval: 120
                    onTriggered: { messageList.restoreReader(); messageList.holdingReader = false }
                }
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: chatHeader.bottom
                anchors.bottom: taskBar.visible ? taskBar.top : composerCard.top
                anchors.leftMargin: chatMain.width < 600 ? 14 : 24
                anchors.rightMargin: chatMain.width < 600 ? 14 : 24
                anchors.topMargin: 20
                anchors.bottomMargin: 10
                visible: count > 0
                clip: true
                // Keep actual message geometry stable across the entire history.
                // ListView estimates unseen heights from visible delegates, which
                // changes the scroll range drastically for long chat responses.
                Column {
                    id: messageColumn
                    width: messageList.width
                    spacing: Theme.messageGap
                    Repeater {
                        id: messageRepeater
                        model: chat.messages
                        delegate: Item {
                            id: messageItem
                            required property int index
                            required property string role
                            required property string content
                            required property string displayContent
                            required property var segments
                            required property string messageKey
                            required property bool isStreaming
                            required property var activityData
                            width: messageList.width
                            height: presentation.item ? presentation.item.implicitHeight : 0
                            Loader {
                                id: presentation
                                width: Math.min(parent.width, Theme.contentWidth)
                                anchors.horizontalCenter: parent.horizontalCenter
                                sourceComponent: messageItem.role === "activity" ? activityComponent
                                    : messageItem.role === "user" ? userComponent : assistantComponent
                            }
                            Component {
                                id: activityComponent
                                VrChatActivity {
                                    items: messageItem.messageKey ? messageItem.activityData : chat.traceItems
                                    reasoningText: messageItem.messageKey ? "" : chat.reasoningText
                                    statusText: messageItem.messageKey ? (messageItem.isStreaming ? "Trabalhando…" : "Concluído") : chat.statusText
                                    elapsedLabel: chat.activityElapsedLabel
                                    running: messageItem.messageKey ? messageItem.isStreaming : chat.turnRunning
                                    expanded: root.activityExpanded
                                    onToggleRequested: root.activityExpanded = !root.activityExpanded
                                }
                            }
                            Component {
                                id: userComponent
                                VrUserMessage {
                                    content: messageItem.displayContent
                                    onCopyRequested: chat.copyMessage(messageItem.index)
                                }
                            }
                            Component {
                                id: assistantComponent
                                VrAssistantMessage {
                                    onLayoutChanging: messageList.preserveReader()
                                    markdown: messageItem.displayContent
                                    streaming: messageItem.isStreaming || (chat.turnRunning && messageItem.index === messageList.count - 1 && !messageItem.messageKey)
                                    onCopyRequested: chat.copyMessage(messageItem.index)
                                }
                            }
                        }
                    }
                }
                // Follow only while pinned; dragging/scrolling back detaches the reader.
                onMovementStarted: beginManualScroll()
                onMovementEnded: followTail = atYEnd
                onContentYChanged: {
                    if (holdingReader && !followTail && contentY !== readerY)
                        Qt.callLater(restoreReader)
                }
                onContentHeightChanged: {
                    if (followTail && !moving) tailTimer.restart()
                    else if (holdingReader) Qt.callLater(restoreReader)
                }
                onCountChanged: { if (followTail) tailTimer.restart() }
                Timer { id: tailTimer; interval: 0; onTriggered: { if (messageList.followTail) messageList.positionViewAtEnd() } }
                NumberAnimation {
                    id: wheelAnimation
                    target: messageList
                    property: "contentY"
                    duration: 120
                    easing.type: Easing.OutCubic
                    onFinished: messageList.followTail = messageList.atYEnd
                }
                WheelHandler {
                    target: null
                    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                    onWheel: event => {
                        var precise = event.pixelDelta.y !== 0
                        var lines = Math.max(1, Math.min(3, Qt.styleHints.wheelScrollLines))
                        var delta = precise ? event.pixelDelta.y
                            : event.angleDelta.y / 120 * lines * Theme.bodySize * 1.6
                        if (delta === 0) { event.accepted = false; return }
                        var start = !precise && wheelAnimation.running ? wheelAnimation.to : messageList.contentY
                        messageList.beginManualScroll()
                        messageList.cancelFlick()
                        var top = messageList.originY
                        var bottom = top + Math.max(0, messageList.contentHeight - messageList.height)
                        var destination = Math.max(top, Math.min(bottom, start - delta))
                        if (precise) {
                            messageList.contentY = destination
                            messageList.followTail = messageList.atYEnd
                        } else {
                            wheelAnimation.from = messageList.contentY
                            wheelAnimation.to = destination
                            wheelAnimation.start()
                        }
                        event.accepted = true
                    }
                }
                ScrollBar.vertical: VrScrollBar {
                    id: messageScrollBar
                    objectName: "messageScrollBar"
                    onPressedChanged: {
                        if (pressed) messageList.beginManualScroll()
                        else messageList.followTail = messageList.atYEnd
                    }
                }
            }


            Column {
                id: landing
                objectName: "chatLanding"
                visible: messageList.count === 0
                anchors.horizontalCenter: parent.horizontalCenter
                y: composerCard.y - height - 24
                width: Math.min(parent.width - 48, 720)
                spacing: 8
                Text {
                    width: parent.width
                    text: root.greetingText()
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(22)
                    font.weight: Font.Normal
                    horizontalAlignment: Text.AlignHCenter
                }
                Text {
                    width: parent.width
                    text: root.greetingPrompt()
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }
                VrButton {
                    id: landingProjectButton
                    objectName: "landingProjectButton"
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(implicitWidth, parent.width)
                    variant: "ghost"
                    text: (chat.currentProjectIndex > 0
                        ? chat.projectItems[chat.currentProjectIndex].label : "Escolher projeto") + "  ▾"
                    onClicked: landingProjectMenu.open()
                    Menu {
                        id: landingProjectMenu
                        objectName: "landingProjectMenu"
                        y: parent.height
                        width: 260
                        padding: 5
                        background: Rectangle {
                            radius: 10
                            color: Theme.palette.chatSidebar
                            border.color: Theme.palette.chatBorder
                        }
                        Instantiator {
                            model: root.filteredProjects("")
                            delegate: ProjectMenuEntry {
                                required property var modelData
                                text: modelData.label
                                onTriggered: chat.setProject(Number(modelData.sourceIndex))
                            }
                            onObjectAdded: (index, object) => landingProjectMenu.insertItem(index, object)
                            onObjectRemoved: (index, object) => landingProjectMenu.removeItem(object)
                        }
                        MenuSeparator { }
                        ProjectMenuEntry {
                            objectName: "landingChooseFolder"
                            text: "Escolher pasta do projeto…"
                            onTriggered: {
                                root.addProjectView = "folder"
                                chat.beginProjectFolderBrowse()
                                addProjectPopup.open()
                            }
                        }
                    }
                }
            }

            VrTaskBar {
                id: taskBar
                visible: chat.turnRunning
                    && chat.activitySteps.length > 0
                    && !root.taskBarDismissed
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: composerCard.top
                anchors.bottomMargin: 8
                width: Math.min(Theme.contentWidth, parent.width - (parent.width < 600 ? 28 : 48))
                z: 20
                steps: chat.activitySteps
                running: chat.turnRunning
                expanded: root.taskBarExpanded
                onToggleRequested: root.taskBarExpanded = !root.taskBarExpanded
                onCloseRequested: root.taskBarDismissed = true
            }

            Rectangle {
                id: scrollToEndPill
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Ir para o fim da conversa"
                function jump() { messageList.followTail = true; messageList.positionViewAtEnd() }
                Keys.onReturnPressed: jump()
                Keys.onSpacePressed: jump()
                objectName: "scrollToEndPill"
                visible: messageList.visible
                    && messageList.count > 0
                    && !messageList.atYEnd
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: composerCard.top
                anchors.bottomMargin: taskBar.visible ? taskBar.height + 16 : 10
                z: 25
                radius: height / 2
                width: pillRow.implicitWidth + 26
                height: 30
                color: Theme.palette.chatComposer
                border.width: 1
                border.color: pillHover.hovered
                    ? Theme.palette.focus : Theme.palette.chatBorder

                Row {
                    id: pillRow
                    anchors.centerIn: parent
                    spacing: 6
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Ir para o fim"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(11)
                    }
                    VrLineIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 12
                        height: 12
                        kind: "chevronDown"
                        foreground: Theme.palette.mutedText
                    }
                }

                HoverHandler { id: pillHover }
                TapHandler {
                    onTapped: {
                        messageList.followTail = true
                        messageList.positionViewAtEnd()
                    }
                }
            }

            Rectangle {
                id: composerCard
                objectName: "chatComposerCard"
                anchors.horizontalCenter: parent.horizontalCenter
                y: messageList.count > 0 ? parent.height - height - root.expertStripHeight - 24
                    : Math.max(chatHeader.height + landing.height + 32,
                        (parent.height + chatHeader.height + landing.height + 24 - height - root.expertStripHeight) / 2)
                width: Math.min(Theme.contentWidth, parent.width - (parent.width < 600 ? 28 : 48))
                height: composerInput.height
                    + (chat.attachments.length ? 88 : 54)
                radius: Theme.composerRadius
                color: Theme.palette.chatComposer
                border.width: 1
                border.color: root.composerDropActive
                    ? Theme.palette.brandOrange
                    : composerInput.activeFocus
                        ? Theme.palette.focus : Theme.palette.chatBorder

                DropArea {
                    id: composerDropArea
                    objectName: "chatComposerDropArea"
                    anchors.fill: parent
                    z: 100
                    onEntered: function(drag) {
                        root.composerDropActive = drag.hasUrls
                        drag.accepted = drag.hasUrls
                    }
                    onExited: root.composerDropActive = false
                    onDropped: function(drop) {
                        root.composerDropActive = false
                        if (drop.hasUrls) {
                            chat.addDroppedAttachments(drop.urls)
                            drop.acceptProposedAction()
                        }
                    }
                }

                VrTextArea {
                    id: composerInput
                    objectName: "chatComposerInput"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    anchors.topMargin: 8
                    height: Math.min(chatMain.height * 0.28, Math.max(54,
                        contentHeight + topPadding + bottomPadding))
                    clip: true
                    placeholderText: chatMain.width < 600 ? "Pergunte algo…" : "Pergunte algo…  @ arquivos · / comandos"
                    readOnly: chat.turnRunning
                    background: Item { }
                    onTextChanged: composerAssistDelay.restart()
                    Keys.priority: Keys.BeforeItem
                    Keys.onPressed: event => {
                        if (event.matches(StandardKey.Paste) && chat.pasteClipboardAttachment())
                            event.accepted = true
                    }
                    Keys.onReturnPressed: event => root.handleComposerEnter(event)
                    Keys.onEnterPressed: event => root.handleComposerEnter(event)
                }

                ListView {
                    id: attachmentList
                    objectName: "chatAttachmentList"
                    visible: chat.attachments.length > 0
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: composerInput.bottom
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    anchors.topMargin: 2
                    height: visible ? 30 : 0
                    orientation: ListView.Horizontal
                    spacing: 6
                    clip: true
                    model: chat.attachments
                    delegate: Rectangle {
                        required property int index
                        required property var modelData
                        width: Math.min(220, attachmentLabel.implicitWidth + 34)
                        height: 26
                        radius: 8
                        color: Theme.palette.chatControl
                        border.width: 1
                        border.color: Theme.palette.chatBorder
                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 4
                            spacing: 4
                            Text {
                                id: attachmentLabel
                                width: parent.parent.width - 30
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.name
                                elide: Text.ElideMiddle
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(10)
                            }
                            VrIconButton {
                                width: 22
                                height: 22
                                anchors.verticalCenter: parent.verticalCenter
                                iconKind: "close"
                                iconSize: 11
                                foreground: Theme.palette.mutedText
                                onClicked: chat.removeAttachment(index)
                            }
                        }
                    }
                }

                Flickable {
                    id: composerControls
                    anchors.left: parent.left
                    anchors.right: sendButton.left
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 10
                    anchors.rightMargin: 8
                    anchors.bottomMargin: 8
                    height: 34
                    contentWidth: controlsRow.width
                    contentHeight: height
                    clip: true
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    RowLayout {
                    id: controlsRow
                    width: Math.max(implicitWidth, composerControls.width)
                    height: 34
                    spacing: 5
                    VrIconButton {
                        id: attachButton
                        objectName: "chatAttachButton"
                        implicitWidth: 32
                        implicitHeight: 32
                        iconKind: "attachment"
                        iconSize: 17
                        foreground: Theme.palette.mutedText
                        enabled: !chat.turnRunning
                        ToolTip.visible: hovered
                        ToolTip.text: "Anexar arquivos"
                        Accessible.name: "Anexar arquivos"
                        onClicked: chat.chooseAttachments()
                    }
                    VrModelPicker {
                        id: modelSelector
                        objectName: "chatModelPicker"
                        model: chat.modelItems
                        currentIndex: chat.modelIndex
                        enabled: !chat.turnRunning
                        onActivated: index => chat.setModel(index)
                        onFavoriteToggled: index => chat.toggleModelFavorite(index)
                    }
                    Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.palette.chatBorder }
                    VrReasoningPicker {
                        id: effortSelector
                        objectName: "chatReasoningPicker"
                        effortModel: chat.effortItems
                        tierModel: chat.serviceTierItems
                        currentEffortIndex: chat.effortIndex
                        currentTierIndex: chat.serviceTierIndex
                        onEffortActivated: index => chat.setEffort(index)
                        onTierActivated: index => chat.setServiceTier(index)
                    }
                    Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.palette.chatBorder }
                    VrPermissionPicker {
                        id: approvalSelector
                        objectName: "chatPermissionPicker"
                        model: chat.approvalItems
                        currentIndex: chat.approvalIndex
                        onActivated: index => chat.setApproval(index)
                    }
                    Item { Layout.fillWidth: true }
                    VrButton {
                        id: vrModeButton
                        objectName: "vrModeButton"
                        implicitWidth: chat.vrMode === "ultra" ? 104 : 58
                        implicitHeight: 32
                        leftPadding: 7; rightPadding: 7
                        text: chat.vrMode === "ultra" ? "VR Ultra" : "VR"
                        variant: chat.vrMode !== "off" ? "primary" : "ghost"
                        background: Rectangle {
                            radius: 10
                            color: chat.vrMode !== "off"
                                ? (parent.down
                                    ? Qt.darker(Theme.palette.accessibleOrange, 1.12)
                                    : Theme.palette.accessibleOrange)
                                : parent.hovered ? Theme.palette.chatControl : "transparent"
                            border.width: chat.vrMode !== "off" || parent.activeFocus ? 1 : 0
                            border.color: chat.vrMode === "ultra"
                                ? Theme.palette.brandOrange
                                : parent.activeFocus ? Theme.palette.focus : Theme.palette.brandOrange
                        }
                        onClicked: chat.cycleVrMode()
                    }
                    VrContextButton {
                        id: contextUsageButton
                        objectName: "contextUsageButton"
                        implicitWidth: 30; implicitHeight: 30
                        visible: chat.hasContextWindow
                        fraction: chat.contextUsageFraction
                        usageLabel: chat.contextUsageCompactLabel
                        totalLabel: chat.totalProcessedLabel
                        note: chat.contextUsageNote
                    }
                    }
                }
                    VrIconButton {
                        id: sendButton
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.rightMargin: 12
                        anchors.bottomMargin: 8
                        implicitWidth: 32; implicitHeight: 32; round: true
                        enabled: chat.turnRunning || composerInput.text.trim().length > 0 || chat.attachments.length > 0
                        ToolTip.visible: hovered || activeFocus
                        ToolTip.text: chat.turnRunning ? "Interromper geração" : "Enviar · Enter (Shift+Enter para nova linha)"
                        Accessible.name: chat.turnRunning ? "Interromper geração" : "Enviar mensagem"
                        iconSource: Qt.resolvedUrl(chat.turnRunning
                            ? "../../../assets/chat-stop.svg"
                            : "../../../assets/chat-send.svg")
                        foreground: "#FFFFFF"
                        background: Rectangle {
                            radius: height / 2
                            color: chat.turnRunning
                                ? (parent.down
                                    ? Qt.darker(Theme.palette.danger, 1.18)
                                    : Theme.palette.danger)
                                : (parent.down
                                    ? Theme.palette.brandOrange
                                    : Theme.palette.accessibleOrange)
                        }
                        onClicked: chat.turnRunning ? chat.stopTurn() : root.submitMessage()
                    }
            }

            Item {
                id: expertProfileStrip
                objectName: "expertProfileStrip"
                visible: root.expertReveal > 0.001
                anchors.horizontalCenter: composerCard.horizontalCenter
                y: composerCard.y + composerCard.height
                    + 8 - (1.0 - root.expertReveal) * 8
                width: composerCard.width
                height: 34
                opacity: root.expertReveal
                scale: 0.94 + root.expertReveal * 0.06

                Row {
                    id: profileRow
                    anchors.centerIn: parent
                    spacing: 7

                    Repeater {
                        model: root.expertProfiles
                        delegate: Rectangle {
                            id: expertChip
                            objectName: "expertProfile_" + modelData.key
                            required property var modelData
                            readonly property bool selected: root.expertProfileSelected(
                                modelData.key)
                            width: chipContent.implicitWidth + 20
                            height: 32
                            radius: 8
                            color: selected ? Theme.palette.chatControl
                                : chipHover.hovered ? Theme.palette.hover
                                : Theme.palette.chatComposer
                            border.width: 1
                            border.color: selected ? Theme.palette.brandOrange
                                : Theme.palette.chatBorder

                            Row {
                                id: chipContent
                                anchors.centerIn: parent
                                spacing: 6
                                VrProfileIcon {
                                    anchors.verticalCenter: parent.verticalCenter
                                    kind: expertChip.modelData.icon
                                    selected: expertChip.selected
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: expertChip.modelData.label
                                    color: Theme.palette.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(11)
                                    font.weight: Font.DemiBold
                                }
                            }
                            HoverHandler {
                                id: chipHover
                                cursorShape: Qt.PointingHandCursor
                            }
                            TapHandler {
                                onTapped: root.activateExpertProfile(
                                    expertChip.modelData.key)
                            }
                        }
                    }
                }
            }

            // VR Ultra uses only the institutional orange. The restrained
            // pulse communicates activity without introducing other colors.
            Rectangle {
                id: ultraGlowOuter
                visible: chat.vrMode === "ultra"
                anchors.centerIn: composerCard
                width: composerCard.width + 16
                height: composerCard.height + 16
                radius: 30
                color: "transparent"
                border.width: 5
                border.color: Qt.rgba(1.0, 0.45, 0.0, 0.18)
                opacity: 0.78
                SequentialAnimation on opacity {
                    running: ultraGlowOuter.visible && root.visible && chat.turnRunning && !frontend.reduceMotion
                    loops: Animation.Infinite
                    NumberAnimation { from: 0.55; to: 0.86; duration: 1400; easing.type: Easing.InOutSine }
                    NumberAnimation { from: 0.86; to: 0.55; duration: 1400; easing.type: Easing.InOutSine }
                }
            }
            Canvas {
                id: ultraArc
                visible: chat.vrMode === "ultra"
                anchors.centerIn: composerCard
                width: composerCard.width + 8
                height: composerCard.height + 8
                property real sweep: 0
                onSweepChanged: requestPaint()
                onVisibleChanged: requestPaint()
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()

                function traceRoundRect(ctx, inset, radius) {
                    var left = inset
                    var top = inset
                    var right = width - inset
                    var bottom = height - inset
                    ctx.beginPath()
                    ctx.moveTo(left + radius, top)
                    ctx.lineTo(right - radius, top)
                    ctx.quadraticCurveTo(right, top, right, top + radius)
                    ctx.lineTo(right, bottom - radius)
                    ctx.quadraticCurveTo(right, bottom, right - radius, bottom)
                    ctx.lineTo(left + radius, bottom)
                    ctx.quadraticCurveTo(left, bottom, left, bottom - radius)
                    ctx.lineTo(left, top + radius)
                    ctx.quadraticCurveTo(left, top, left + radius, top)
                    ctx.closePath()
                }

                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.lineCap = "round"
                    ctx.lineWidth = 2.2
                    ctx.globalAlpha = 0.92
                    traceRoundRect(ctx, 2, 27)
                    ctx.strokeStyle = Theme.palette.brandOrange
                    ctx.setLineDash([])
                    ctx.stroke()

                    ctx.lineWidth = 3.0
                    ctx.lineCap = "round"
                    var perimeter = 2 * (width + height) - 8 * 26 + 2 * Math.PI * 26
                    traceRoundRect(ctx, 2, 27)
                    ctx.globalAlpha = 1.0
                    ctx.strokeStyle = Theme.palette.brandOrange
                    ctx.setLineDash([perimeter * 0.16, perimeter * 0.06,
                        perimeter * 0.08, perimeter * 0.70])
                    ctx.lineDashOffset = -sweep * perimeter
                    ctx.stroke()
                    ctx.setLineDash([])
                }
                SequentialAnimation on sweep {
                    running: ultraArc.visible && root.visible && chat.turnRunning && !frontend.reduceMotion
                    loops: Animation.Infinite
                    NumberAnimation { from: 0; to: 1; duration: 4200; easing.type: Easing.Linear }
                }
            }

            VrProjectSettings {
                id: projectSettingsPage
                objectName: "projectSettingsPage"
                anchors.fill: parent
                z: 50
                visible: root.projectSettingsVisible
                projectIndex: root.projectSettingsIndex
                projectName: root.projectSettingsName
                projectPath: root.projectSettingsPath
                projectIconPath: root.projectSettingsIconPath
                threadCount: chat.conversationCount
                onCloseRequested: root.projectSettingsVisible = false
                onSaveRequested: name => {
                    if (chat.renameProject(root.projectSettingsIndex, name))
                        root.projectSettingsName = name
                }
                onIconRequested: chat.chooseProjectIcon(root.projectSettingsIndex)
                onOpenFolderRequested: chat.openProjectFolder(root.projectSettingsIndex)
                onCopyPathRequested: chat.copyProjectPath(root.projectSettingsIndex)
                onRemoveRequested: {
                    if (chat.removeProject(root.projectSettingsIndex))
                        root.projectSettingsVisible = false
                }
            }
        }

        Rectangle {
            id: surfacePanel
            parent: root.width < 1000 ? root : mainSplit
            z: root.width < 1000 ? 45 : 0
            x: root.width < 1000 ? root.width - width : 0
            width: Math.min(root.width, root.surfacePanelWidth)
            height: root.height
            objectName: "surfacePanel"
            visible: root.surfacePanelWidth > 0.5
            opacity: root.surfaceVisible ? 1 : 0
            SplitView.minimumWidth: 0
            SplitView.preferredWidth: root.surfacePanelWidth
            SplitView.maximumWidth: root.surfacePanelWidth > 0.5 ? 720 : 0
            color: Theme.palette.chatSidebar
            border.width: 1
            border.color: Theme.palette.chatDivider
            transform: Translate {
                x: root.surfaceVisible ? 0 : Theme.motionDistance
                Behavior on x {
                    enabled: !frontend.reduceMotion
                    NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
                }
            }
            Behavior on opacity {
                enabled: !frontend.reduceMotion
                NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
            }
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                Item {
                    id: surfaceHeader
                    Layout.fillWidth: true
                    Layout.preferredHeight: 42

                    Flickable {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 5
                        anchors.rightMargin: 42
                        contentWidth: surfaceTabRow.width
                        contentHeight: height
                        boundsBehavior: Flickable.StopAtBounds
                        clip: true

                        Row {
                            id: surfaceTabRow
                            height: parent.height
                            spacing: 3

                            Repeater {
                                model: root.openSurfaceTabs
                                delegate: Button {
                                    id: surfaceTab
                                    objectName: "surfaceTab"
                                    required property var modelData
                                    readonly property bool selected: root.surfaceIndex === modelData.page
                                    width: Math.max(84, tabContent.implicitWidth + 18)
                                    height: 36
                                    anchors.verticalCenter: parent.verticalCenter
                                    padding: 0
                                    hoverEnabled: true
                                    transformOrigin: Item.Center
                                    scale: !frontend.reduceMotion && down ? 0.97 : 1
                                    onClicked: root.surfaceIndex = modelData.page

                                    Behavior on scale {
                                        enabled: !frontend.reduceMotion
                                        NumberAnimation {
                                            duration: Theme.pressDuration
                                            easing.type: Easing.OutCubic
                                        }
                                    }

                                    contentItem: RowLayout {
                                        id: tabContent
                                        spacing: 7
                                        VrLineIcon {
                                            Layout.preferredWidth: 17
                                            Layout.preferredHeight: 17
                                            kind: surfaceTab.modelData.kind
                                            foreground: surfaceTab.selected
                                                ? Theme.palette.text : Theme.palette.mutedText
                                        }
                                        Text {
                                            text: surfaceTab.modelData.title
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(11)
                                            font.weight: Font.DemiBold
                                        }
                                        VrLineIcon {
                                            Layout.preferredWidth: 13
                                            Layout.preferredHeight: 13
                                            kind: "close"
                                            foreground: Theme.palette.mutedText
                                            visible: surfaceTab.hovered || surfaceTab.selected
                                            TapHandler {
                                                onTapped: function(eventPoint) {
                                                    eventPoint.accepted = true
                                                    root.closeSurface(surfaceTab.modelData.page)
                                                }
                                            }
                                        }
                                    }
                                    background: Rectangle {
                                        radius: 8
                                        color: surfaceTab.selected
                                            ? Theme.palette.chatControl
                                            : surfaceTab.hovered ? Theme.palette.hover : "transparent"
                                        Rectangle {
                                            visible: surfaceTab.selected
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            height: 2
                                            color: Theme.palette.brandOrange
                                        }

                                        Behavior on color {
                                            enabled: !frontend.reduceMotion
                                            ColorAnimation { duration: Theme.fastDuration }
                                        }
                                    }
                                }
                            }

                            VrIconButton {
                                id: surfaceAddButton
                                objectName: "surfaceAddButton"
                                implicitWidth: 34
                                implicitHeight: 34
                                iconKind: "plus"
                                foreground: Theme.palette.mutedText
                                ToolTip.visible: hovered
                                ToolTip.text: "Abrir superfície"
                                onClicked: surfacePickerPopup.visible
                                    ? surfacePickerPopup.close() : surfacePickerPopup.open()
                            }
                        }
                    }

                    VrIconButton {
                        id: surfaceCollapseButton
                        objectName: "surfaceCollapseButton"
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.topMargin: 5
                        anchors.rightMargin: 6
                        implicitWidth: 32
                        implicitHeight: 32
                        iconSize: 17
                        iconKind: "panelRight"
                        foreground: Theme.palette.mutedText
                        ToolTip.visible: hovered
                        ToolTip.text: "Recolher painel direito"
                        Accessible.name: ToolTip.text
                        onClicked: root.surfaceVisible = false
                        background: Rectangle {
                            radius: 8
                            color: parent.down || parent.hovered
                                ? Theme.palette.chatControl : "transparent"
                        }
                    }

                    Popup {
                        id: surfacePickerPopup
                        objectName: "surfacePickerPopup"
                        parent: surfaceHeader
                        x: Math.max(5, Math.min(surfaceHeader.width - width - 5,
                            surfaceAddButton.x + surfaceAddButton.width - width))
                        y: surfaceHeader.height - 2
                        width: 176
                        height: surfacePickerList.contentHeight + 12
                        padding: 6
                        focus: true
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

                        contentItem: ListView {
                            id: surfacePickerList
                            clip: true
                            model: root.surfaceTabs
                            delegate: Rectangle {
                                required property var modelData
                                width: surfacePickerList.width
                                height: 36
                                radius: 6
                                color: surfaceChoiceHover.hovered
                                    ? Theme.palette.chatControl : "transparent"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 8
                                    spacing: 8
                                    VrLineIcon {
                                        Layout.preferredWidth: 16
                                        Layout.preferredHeight: 16
                                        kind: modelData.kind
                                        foreground: Theme.palette.mutedText
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.title
                                        color: Theme.palette.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(12)
                                    }
                                    Text {
                                        text: modelData.title.charAt(0)
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(10)
                                    }
                                }
                                HoverHandler { id: surfaceChoiceHover }
                                TapHandler {
                                    onTapped: {
                                        root.openSurface(modelData.page)
                                        surfacePickerPopup.close()
                                    }
                                }
                            }
                        }
                        background: Rectangle {
                            radius: 9
                            color: Theme.palette.chatComposer
                            border.width: 1
                            border.color: Theme.palette.chatBorder
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.palette.chatDivider }
                StackLayout {
                    id: surfaceStack
                    objectName: "surfaceContentStack"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: root.displayedSurfaceIndex
                    transform: Translate { id: surfaceShift; x: 0 }

                    SequentialAnimation {
                        id: surfaceSwitch
                        NumberAnimation {
                            target: surfaceStack
                            property: "opacity"
                            to: 0
                            duration: Math.round(Theme.fastDuration / 2)
                            easing.type: Easing.InQuad
                        }
                        ScriptAction { script: root.displayedSurfaceIndex = root.surfaceIndex }
                        PropertyAction {
                            target: surfaceShift
                            property: "x"
                            value: Theme.motionDistance
                        }
                        ParallelAnimation {
                            NumberAnimation {
                                target: surfaceStack
                                property: "opacity"
                                to: 1
                                duration: Theme.motionDuration
                                easing.type: Easing.OutCubic
                            }
                            NumberAnimation {
                                target: surfaceShift
                                property: "x"
                                to: 0
                                duration: Theme.motionDuration
                                easing.type: Easing.OutCubic
                            }
                        }
                    }
                    Item {
                        ScrollView {
                            id: surfaceChooser
                            anchors.fill: parent
                            anchors.margins: 14
                            clip: true
                            contentWidth: availableWidth

                            ColumnLayout {
                                width: surfaceChooser.availableWidth
                                spacing: 7
                                Text {
                                    Layout.fillWidth: true
                                    text: "Abrir uma superfície"
                                    color: Theme.palette.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(15)
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Escolha o que exibir no painel direito."
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(11)
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                GridLayout {
                                    id: surfaceChooserGrid
                                    Layout.fillWidth: true
                                    Layout.topMargin: 8
                                    columns: width >= 380 ? 2 : 1
                                    columnSpacing: 8
                                    rowSpacing: 8
                                    Repeater {
                                        model: root.surfaceTabs
                                        delegate: VrSurfaceCard {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            Layout.preferredWidth: (
                                                surfaceChooserGrid.width
                                                - surfaceChooserGrid.columnSpacing
                                                    * (surfaceChooserGrid.columns - 1)
                                            ) / surfaceChooserGrid.columns
                                            implicitHeight: 84
                                            iconKind: modelData.kind
                                            title: modelData.title
                                            description: modelData.description
                                            onClicked: root.openSurface(modelData.page)
                                        }
                                    }
                                }
                                Item { Layout.fillHeight: true }
                            }
                        }
                    }
                    ColumnLayout {
                        spacing: 6
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.margins: 8
                            VrIconButton { implicitWidth: 32; implicitHeight: 32; iconKind: "back"; foreground: Theme.palette.mutedText; enabled: browserLoader.item && browserLoader.item.canGoBack; ToolTip.visible: hovered; ToolTip.text: "Voltar"; onClicked: root.browserBack() }
                            VrIconButton { implicitWidth: 32; implicitHeight: 32; iconKind: "forward"; foreground: Theme.palette.mutedText; enabled: browserLoader.item && browserLoader.item.canGoForward; ToolTip.visible: hovered; ToolTip.text: "Avançar"; onClicked: root.browserForward() }
                            VrIconButton { implicitWidth: 32; implicitHeight: 32; iconKind: "reload"; foreground: Theme.palette.mutedText; enabled: browserLoader.item !== null; ToolTip.visible: hovered; ToolTip.text: "Recarregar"; onClicked: root.reloadBrowser() }
                            VrTextField { id: browserAddress; Layout.fillWidth: true; placeholderText: "Pesquisar ou inserir URL"; onAccepted: root.navigateBrowser(text) }
                        }
                        Loader {
                            id: browserLoader
                            objectName: "chatBrowserLoader"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            active: false
                            source: active ? "../components/VrWebSurface.qml" : ""
                            onLoaded: {
                                if (root.pendingBrowserAddress.length) {
                                    item.navigate(root.pendingBrowserAddress)
                                    root.pendingBrowserAddress = ""
                                }
                            }
                            onStatusChanged: {
                                if (status === Loader.Error)
                                    root.pendingBrowserAddress = ""
                            }
                        }
                        Connections {
                            target: browserLoader.item
                            enabled: browserLoader.item !== null
                            function onAddressChanged(value) { browserAddress.text = value }
                        }
                    }
                    ColumnLayout {
                        spacing: 0
                        Rectangle {
                            objectName: "terminalSurfaceBackground"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 44
                            color: Theme.palette.chatSidebar
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 5
                                Text {
                                    text: (Qt.platform.os === "windows" ? "PS " : "")
                                        + frontend.projectPath + ">"
                                    color: Theme.palette.text
                                    font.family: "Cascadia Mono"
                                    font.pixelSize: Theme.fontSize(12)
                                }
                                TextField {
                                    id: terminalCommandInput
                                    objectName: "terminalCommandInput"
                                    Layout.fillWidth: true
                                    readOnly: studio.terminalRunning
                                    color: Theme.palette.text
                                    selectionColor: Theme.palette.focus
                                    selectedTextColor: Theme.palette.text
                                    font.family: "Cascadia Mono"
                                    font.pixelSize: Theme.fontSize(12)
                                    leftPadding: 0
                                    rightPadding: 0
                                    placeholderText: ""
                                    background: Item {}
                                    onAccepted: {
                                        studio.runTerminalCommand(text)
                                        clear()
                                    }
                                }
                                VrButton {
                                    objectName: "terminalStopButton"
                                    visible: studio.terminalRunning
                                    enabled: studio.terminalRunning
                                    text: "Parar"
                                    variant: "danger"
                                    implicitHeight: 30
                                    onClicked: studio.stopTerminalCommand()
                                }
                            }
                        }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            TextArea {
                                width: parent.width
                                readOnly: true
                                selectByMouse: true
                                wrapMode: TextArea.WrapAnywhere
                                text: studio.terminalOutput
                                color: Theme.palette.text
                                background: Rectangle {
                                    objectName: "terminalOutputBackground"
                                    color: Theme.palette.chatSidebar
                                }
                                font.family: "Cascadia Mono"
                                font.pixelSize: Theme.fontSize(12)
                            }
                        }
                    }
                    ColumnLayout {
                        spacing: 8
                        VrTextField {
                            id: fileSearch
                            Layout.fillWidth: true
                            Layout.margins: 8
                            placeholderText: "Buscar arquivos"
                            onTextChanged: fileSearchDelay.restart()
                            onAccepted: root.surfaceFiles = chat.fileSuggestions(text)
                        }
                        ListView {
                            id: fileList
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(100, surfaceStack.height * 0.38)
                            Layout.leftMargin: 8
                            Layout.rightMargin: 8
                            clip: true
                            reuseItems: true
                            cacheBuffer: 300
                            spacing: 0
                            model: root.surfaceFiles
                            ScrollBar.vertical: VrScrollBar { }
                            delegate: Rectangle {
                                id: fileTreeRow
                                required property var modelData
                                width: ListView.view.width
                                height: root.fileTreeItemVisible(modelData) ? 30 : 0
                                visible: height > 0
                                radius: 6
                                color: root.surfaceFilePath === modelData.path
                                    ? Theme.palette.selection
                                    : fileTreeHover.hovered ? Theme.palette.chatControl : "transparent"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 6 + Math.min(8, Number(modelData.depth || 0)) * 14
                                    anchors.rightMargin: 6
                                    spacing: 5
                                    VrLineIcon {
                                        visible: modelData.isDirectory === true
                                        Layout.preferredWidth: 11
                                        Layout.preferredHeight: 11
                                        kind: root.expandedFileFolders[modelData.label]
                                            ? "chevronDown" : "chevronRight"
                                        foreground: Theme.palette.mutedText
                                    }
                                    Item {
                                        visible: modelData.isDirectory !== true
                                        Layout.preferredWidth: 11
                                        Layout.preferredHeight: 11
                                    }
                                    VrLineIcon {
                                        Layout.preferredWidth: 15
                                        Layout.preferredHeight: 15
                                        kind: modelData.isDirectory === true ? "folder" : "files"
                                        foreground: modelData.isDirectory === true
                                            ? Theme.palette.brandOrange : Theme.palette.mutedText
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.name || modelData.label
                                        color: Theme.palette.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(11)
                                        elide: Text.ElideMiddle
                                    }
                                }
                                HoverHandler { id: fileTreeHover }
                                TapHandler {
                                    onTapped: {
                                        if (modelData.isDirectory === true) {
                                            root.toggleFileFolder(modelData.label)
                                            return
                                        }
                                        root.surfaceFilePath = modelData.path
                                        root.surfaceFilePreview = chat.readFilePreview(modelData.path)
                                    }
                                }
                            }
                            VrMiddleAutoScroller {
                                objectName: "fileAutoScroller"
                                parent: fileList
                                anchors.fill: parent
                                target: fileList
                                enabled: fileList.count > 0
                                z: 30
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: 8
                            Layout.rightMargin: 8
                            Text { Layout.fillWidth: true; text: root.surfaceFilePath || "Selecione um arquivo para visualizar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); elide: Text.ElideMiddle }
                            VrButton { text: "Abrir"; enabled: root.surfaceFilePath.length > 0; onClicked: studio.openLocalPath(root.surfaceFilePath) }
                        }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.leftMargin: 8
                            Layout.rightMargin: 8
                            Layout.bottomMargin: 8
                            TextArea {
                                width: parent.width
                                readOnly: true
                                selectByMouse: true
                                wrapMode: TextArea.NoWrap
                                placeholderText: "A prévia do arquivo aparecerá aqui."
                                text: root.surfaceFilePreview
                                color: Theme.palette.text
                                background: Rectangle {
                                    objectName: "filePreviewBackground"
                                    color: Theme.palette.chatSidebar
                                }
                                font.family: "Cascadia Mono"
                                font.pixelSize: Theme.fontSize(11)
                            }
                        }
                    }
                    ColumnLayout {
                        spacing: 8
                        VrTextField {
                            id: contextSearch
                            Layout.fillWidth: true
                            Layout.margins: 8
                            placeholderText: "Pesquisar Wikis e KB"
                            onTextChanged: contextSearchDelay.restart()
                            onAccepted: root.contextItems = chat.contextSuggestions(text)
                        }
                        ListView {
                            id: contextList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.leftMargin: 8
                            Layout.rightMargin: 8
                            clip: true
                            reuseItems: true
                            cacheBuffer: 300
                            spacing: 5
                            model: root.contextItems
                            ScrollBar.vertical: VrScrollBar { }
                            delegate: Rectangle {
                                required property var modelData
                                width: ListView.view.width
                                height: 72
                                radius: 8
                                color: contextHover.hovered ? Theme.palette.chatControl : "transparent"
                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 3
                                    Text { width: parent.width; text: modelData.title + " · " + modelData.source; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold; elide: Text.ElideRight }
                                    Text { width: parent.width; text: modelData.excerpt; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); maximumLineCount: 2; elide: Text.ElideRight; wrapMode: Text.WordWrap }
                                }
                                HoverHandler { id: contextHover }
                                TapHandler { onTapped: root.insertReference(modelData.reference) }
                            }
                            VrMiddleAutoScroller {
                                objectName: "contextAutoScroller"
                                parent: contextList
                                anchors.fill: parent
                                target: contextList
                                enabled: contextList.count > 0
                                z: 30
                            }
                        }
                    }
                    ColumnLayout {
                        spacing: 8
                        Text {
                            Layout.fillWidth: true
                            Layout.margins: 10
                            text: chat.agentItems.length > 0
                                ? "Agentes · " + chat.agentItems.length
                                : "Nenhum agente nesta conversa. As tarefas delegadas aparecerão aqui."
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(11)
                            wrapMode: Text.WordWrap
                        }
                        ListView {
                            id: agentList
                            objectName: "agentList"
                            ScrollBar.vertical: VrScrollBar { }
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(contentHeight, 260)
                            Layout.leftMargin: 8
                            Layout.rightMargin: 8
                            clip: true
                            spacing: 4
                            model: chat.agentItems
                            delegate: Rectangle {
                                required property int index
                                required property var modelData
                                width: agentList.width
                                height: 58
                                radius: 8
                                color: root.selectedAgentIndex === index ? Theme.palette.selection
                                    : agentHover.hovered ? Theme.palette.chatControl : "transparent"
                                border.width: root.selectedAgentIndex === index ? 1 : 0
                                border.color: Theme.palette.chatBorder
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    Text {
                                        text: modelData.status === "concluído" ? "✓"
                                            : modelData.status === "falhou" ? "!"
                                            : modelData.status === "executando" ? "●" : "○"
                                        color: modelData.status === "concluído" ? Theme.palette.success
                                            : modelData.status === "falhou" ? Theme.palette.danger
                                            : modelData.status === "executando" ? Theme.palette.brandOrange
                                            : Theme.palette.mutedText
                                        font.pixelSize: Theme.fontSize(14)
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text { Layout.fillWidth: true; text: modelData.label; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold; elide: Text.ElideRight }
                                        Text { Layout.fillWidth: true; text: modelData.model + " · " + modelData.effort + " · " + modelData.statusLabel; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); elide: Text.ElideRight }
                                    }
                                }
                                HoverHandler { id: agentHover }
                                TapHandler { onTapped: root.selectedAgentIndex = index }
                            }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.palette.chatDivider }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.leftMargin: 10
                            Layout.rightMargin: 10
                            TextArea {
                                width: parent.width
                                readOnly: true
                                selectByMouse: true
                                wrapMode: TextArea.Wrap
                                text: root.agentDetailText()
                                color: Theme.palette.text
                                background: Item { }
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                            }
                        }
                    }
                }
            }
        }
    }

    Timer { id: searchDelay; interval: 180; onTriggered: chat.setSearch(conversationSearch.text) }
    Timer { id: composerAssistDelay; interval: 120; onTriggered: root.updateComposerSuggestions() }
    Timer { id: fileSearchDelay; interval: 160; onTriggered: root.surfaceFiles = chat.fileSuggestions(fileSearch.text) }
    Timer { id: contextSearchDelay; interval: 200; onTriggered: root.contextItems = chat.contextSuggestions(contextSearch.text) }
    Timer { id: copyFeedbackTimer; interval: 1300; onTriggered: root.copyFeedbackVisible = false }

    Connections {
        target: chat
        function onFileSuggestionsChanged() {
            root.surfaceFiles = chat.fileSuggestions(fileSearch.text)
            root.updateComposerSuggestions()
        }
    }

    Shortcut { sequence: "Ctrl+1"; onActivated: root.activateModelShortcut(0) }
    Shortcut { sequence: "Ctrl+2"; onActivated: root.activateModelShortcut(1) }
    Shortcut { sequence: "Ctrl+3"; onActivated: root.activateModelShortcut(2) }
    Shortcut { sequence: "Ctrl+4"; onActivated: root.activateModelShortcut(3) }
    Shortcut { sequence: "Ctrl+5"; onActivated: root.activateModelShortcut(4) }
    Shortcut { sequence: "Ctrl+6"; onActivated: root.activateModelShortcut(5) }
    Shortcut { sequence: "Ctrl+7"; onActivated: root.activateModelShortcut(6) }
    Shortcut { sequence: "Ctrl+8"; onActivated: root.activateModelShortcut(7) }
    Shortcut { sequence: "Ctrl+9"; onActivated: root.activateModelShortcut(8) }

    Popup {
        id: composerAssistPopup
        parent: composerCard
        x: 0
        y: -height - 8
        width: composerCard.width
        height: Math.min(250, assistList.contentHeight + 12)
        padding: 6
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: Theme.palette.chatComposer; border.width: 1; border.color: Theme.palette.chatBorder; radius: 12 }
        contentItem: ListView {
            id: assistList
            clip: true
            spacing: 2
            model: root.composerSuggestions
            delegate: Rectangle {
                required property var modelData
                width: assistList.width
                height: 44
                radius: 7
                color: assistHover.hovered ? Theme.palette.chatControl : "transparent"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 9
                    anchors.rightMargin: 9
                    Text { Layout.preferredWidth: 140; text: modelData.label; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Text { Layout.fillWidth: true; text: modelData.description || ""; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10); elide: Text.ElideRight }
                }
                HoverHandler { id: assistHover }
                TapHandler { onTapped: root.chooseComposerSuggestion(modelData) }
            }
        }
    }

    Popup {
        id: newChatProjectPopup
        objectName: "projectSelectorPopup"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(560, parent.width - 48)
        height: Math.min(parent.height - 80,
            Math.max(220, 117 + Math.min(6,
                root.filteredProjects(newChatProjectSearch.text).length) * 56))
        padding: 0
        modal: true
        dim: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: Qt.callLater(function() { newChatProjectSearch.forceActiveFocus() })

        contentItem: ColumnLayout {
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 49
                Layout.leftMargin: 7
                Layout.rightMargin: 10
                spacing: 4

                VrIconButton {
                    implicitWidth: 34
                    implicitHeight: 34
                    iconKind: "back"
                    foreground: Theme.palette.mutedText
                    ToolTip.visible: hovered
                    ToolTip.text: "Voltar"
                    onClicked: newChatProjectPopup.close()
                }
                VrTextField {
                    id: newChatProjectSearch
                    objectName: "newChatProjectSearch"
                    Layout.fillWidth: true
                    implicitHeight: 36
                    placeholderText: "Buscar projetos..."
                    background: Item { }
                    onTextChanged: newChatProjectList.currentIndex = 0
                    Keys.onPressed: event => {
                        if (event.key === Qt.Key_Down) {
                            newChatProjectList.currentIndex = Math.min(
                                newChatProjectList.count - 1,
                                newChatProjectList.currentIndex + 1)
                            event.accepted = true
                        } else if (event.key === Qt.Key_Up) {
                            newChatProjectList.currentIndex = Math.max(
                                0, newChatProjectList.currentIndex - 1)
                            event.accepted = true
                        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            if (newChatProjectList.currentIndex >= 0)
                                root.chooseNewChatProject(
                                    newChatProjectList.model[newChatProjectList.currentIndex])
                            event.accepted = true
                        } else if (event.key === Qt.Key_Backspace && !text.length) {
                            newChatProjectPopup.close()
                            event.accepted = true
                        } else if ((event.modifiers & Qt.ControlModifier)
                                && event.key >= Qt.Key_1 && event.key <= Qt.Key_9) {
                            var shortcutIndex = event.key - Qt.Key_1
                            if (shortcutIndex < newChatProjectList.count)
                                root.chooseNewChatProject(newChatProjectList.model[shortcutIndex])
                            event.accepted = true
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: Theme.palette.chatDivider
            }
            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 10
                Layout.rightMargin: 10
                Layout.topMargin: 9
                Layout.bottomMargin: 6
                text: "Projetos"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(10)
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignLeft
            }

            ListView {
                id: newChatProjectList
                objectName: "newChatProjectList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                spacing: 2
                clip: true
                currentIndex: count ? 0 : -1
                model: root.filteredProjects(newChatProjectSearch.text)

                delegate: Rectangle {
                    id: newProjectItem
                    required property int index
                    required property var modelData
                    width: newChatProjectList.width
                    height: 54
                    radius: 7
                    color: newChatProjectList.currentIndex === index
                        || newProjectHover.hovered
                        ? Theme.palette.chatControl : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 9
                        spacing: 9
                        VrLineIcon {
                            Layout.preferredWidth: 17
                            Layout.preferredHeight: 17
                            kind: "folder"
                            foreground: Theme.palette.mutedText
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                Layout.fillWidth: true
                                text: newProjectItem.modelData.label
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: Font.DemiBold
                                horizontalAlignment: Text.AlignLeft
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: newProjectItem.modelData.path.length
                                    ? "Local · " + newProjectItem.modelData.path
                                    : "Espaço gerenciado VR"
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(10)
                                horizontalAlignment: Text.AlignLeft
                                elide: Text.ElideMiddle
                            }
                        }
                        Text {
                            text: newProjectItem.modelData.shortcut
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(10)
                        }
                    }
                    HoverHandler {
                        id: newProjectHover
                        onHoveredChanged: {
                            if (hovered) newChatProjectList.currentIndex = newProjectItem.index
                        }
                    }
                    TapHandler { onTapped: root.chooseNewChatProject(newProjectItem.modelData) }
                }

                Text {
                    anchors.centerIn: parent
                    visible: newChatProjectList.count === 0
                    text: "Nenhum projeto encontrado"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 40
                color: Theme.palette.chatComposer
                border.width: 1
                border.color: Theme.palette.chatDivider
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 10
                    Text { text: "↑ ↓  Navegar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                    Text { text: "Enter  Selecionar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                    Text { text: "Backspace  Voltar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                    Item { Layout.fillWidth: true }
                    Text { text: "Esc  Fechar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(10) }
                }
            }
        }
        background: Rectangle {
            radius: 12
            color: Theme.palette.chatSidebar
            border.width: 1
            border.color: Theme.palette.chatBorder
        }
    }

    Popup {
        id: addProjectPopup
        objectName: "addProjectPopup"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(570, parent.width - 48)
        height: Math.min(430, parent.height - 70)
        padding: 0
        modal: true
        dim: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: Qt.callLater(function() {
            if (root.addProjectView === "sources") addProjectSearch.forceActiveFocus()
        })

        contentItem: StackLayout {
            currentIndex: root.addProjectView === "folder" ? 1 : 0

            ColumnLayout {
                spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 50
                Layout.leftMargin: 8
                Layout.rightMargin: 10
                spacing: 4
                VrIconButton {
                    implicitWidth: 34
                    implicitHeight: 34
                    iconKind: "back"
                    foreground: Theme.palette.mutedText
                    onClicked: addProjectPopup.close()
                }
                VrTextField {
                    id: addProjectSearch
                    objectName: "addProjectSearch"
                    Layout.fillWidth: true
                    implicitHeight: 36
                    placeholderText: "Search..."
                    background: Item { }
                    Keys.onEscapePressed: addProjectPopup.close()
                }
            }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.palette.chatDivider }
            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 18
                Layout.rightMargin: 18
                Layout.topMargin: 14
                Layout.bottomMargin: 6
                text: "Sources"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
                font.weight: Font.DemiBold
            }
            ListView {
                id: addProjectList
                objectName: "addProjectSourceList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: 10
                Layout.rightMargin: 10
                clip: true
                spacing: 2
                model: root.filteredAddProjectSources(addProjectSearch.text)
                delegate: Rectangle {
                    id: sourceRow
                    required property int index
                    required property var modelData
                    width: addProjectList.width
                    height: 48
                    radius: 7
                    color: sourceHover.hovered && modelData.enabled
                        ? Theme.palette.chatControl : "transparent"
                    opacity: modelData.enabled ? 1.0 : 0.72
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 9
                        anchors.rightMargin: 9
                        spacing: 9
                        VrLineIcon {
                            Layout.preferredWidth: 18
                            Layout.preferredHeight: 18
                            kind: modelData.icon
                            foreground: modelData.enabled
                                ? Theme.palette.text : Theme.palette.mutedText
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                Layout.fillWidth: true
                                text: modelData.title
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: modelData.key === "local" ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.description
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(10)
                                elide: Text.ElideRight
                            }
                        }
                        Rectangle {
                            visible: modelData.badge.length > 0
                            Layout.preferredWidth: badgeText.implicitWidth + 14
                            Layout.preferredHeight: 24
                            radius: 5
                            color: Theme.palette.chatComposer
                            border.width: 1
                            border.color: Theme.palette.chatBorder
                            Text {
                                id: badgeText
                                anchors.centerIn: parent
                                text: modelData.badge
                                color: Theme.palette.warning
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(9)
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                    HoverHandler { id: sourceHover }
                    MouseArea {
                        objectName: sourceRow.modelData.key === "local"
                            ? "addProjectLocalFolderButton" : ""
                        anchors.fill: parent
                        enabled: sourceRow.modelData.enabled
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        preventStealing: true
                        onClicked: {
                            root.activateProjectSource(sourceRow.modelData.key)
                        }
                    }
                }
                Text {
                    anchors.centerIn: parent
                    visible: addProjectList.count === 0
                    text: "Nenhuma fonte encontrada"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 38
                color: Theme.palette.chatComposer
                border.width: 1
                border.color: Theme.palette.chatDivider
                Text {
                    anchors.centerIn: parent
                    text: "↑↓  Navegar     Enter  Selecionar     Esc  Fechar"
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(10)
                }
            }
            }

            VrProjectFolderBrowser {
                objectName: "addProjectFolderBrowser"
                onBackRequested: {
                    root.addProjectView = "sources"
                    Qt.callLater(function() { addProjectSearch.forceActiveFocus() })
                }
                onCloseRequested: addProjectPopup.close()
                onProjectAdded: addProjectPopup.close()
            }
        }
        background: Rectangle {
            color: Theme.palette.chatBackground
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: 18
        }
    }

    Popup {
        id: conversationContextMenu
        objectName: "conversationContextMenu"
        width: 196
        height: 126
        padding: 5
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        contentItem: ColumnLayout {
            spacing: 2
            Repeater {
                model: [
                    { kind: "pin", label: chat.selectedPinned ? "Desafixar conversa" : "Fixar conversa", action: "pin" },
                    { kind: "archive", label: "Arquivar conversa", action: "archive" },
                    { kind: "trash", label: "Excluir conversa", action: "delete" }
                ]
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    radius: 7
                    color: menuHover.hovered ? Theme.palette.chatControl : "transparent"
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 9; anchors.rightMargin: 9; spacing: 8
                        VrLineIcon { Layout.preferredWidth: 16; Layout.preferredHeight: 16; kind: modelData.kind; foreground: modelData.action === "delete" ? Theme.palette.danger : Theme.palette.mutedText }
                        Text { Layout.fillWidth: true; text: modelData.label; color: modelData.action === "delete" ? Theme.palette.danger : Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    }
                    HoverHandler { id: menuHover }
                    TapHandler {
                        onTapped: {
                            conversationContextMenu.close()
                            if (modelData.action === "pin") chat.togglePinnedCurrent()
                            else if (modelData.action === "archive") chat.archiveCurrentConversation()
                            else conversationDeleteDialog.open()
                        }
                    }
                }
            }

        }
        background: Rectangle {
            radius: 10
            color: Theme.palette.chatComposer
            border.width: 1
            border.color: Theme.palette.chatBorder
        }
    }

    Dialog {
        id: extensionsDialog
        anchors.centerIn: parent
        width: 610
        height: 520
        modal: true
        title: "Skills, tools e MCP"
        standardButtons: Dialog.Close
        onOpened: chat.refreshExtensions()
        contentItem: ColumnLayout {
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; text: "Selecione recursos para a próxima mensagem. Alterar tools em um chat iniciado cria uma ramificação segura."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); wrapMode: Text.WordWrap }
                VrButton { text: chat.extensionsLoading ? "Carregando…" : "Atualizar"; enabled: !chat.extensionsLoading; onClicked: chat.refreshExtensions() }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 8
                color: Theme.palette.chatSidebar
                border.width: 1
                border.color: Theme.palette.chatBorder
                ListView {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 3
                    clip: true
                    model: chat.extensionItems
                    delegate: VrCheckBox {
                        required property int index
                        required property var modelData
                        width: ListView.view.width
                        text: (modelData.kind === "skill" ? "Skill · " : "MCP · ") + modelData.name
                        checked: modelData.selected
                        ToolTip.visible: hovered
                        ToolTip.text: modelData.description
                        onToggled: chat.toggleExtension(index, checked)
                    }
                    VrEmptyState {
                        anchors.centerIn: parent
                        visible: parent.count === 0 && !chat.extensionsLoading
                        title: "Nenhum recurso encontrado"
                        description: "O catálogo depende do provedor e do projeto selecionados."
                        actionText: "Tentar novamente"
                        onAction: chat.refreshExtensions()
                    }
                }
            }
        }
        background: Rectangle { color: Theme.palette.surface; border.width: 1; border.color: Theme.palette.border; radius: Theme.radiusPopup }
    }
    Dialog {
        id: approvalDialog
        anchors.centerIn: parent
        width: 510
        modal: true
        closePolicy: Popup.NoAutoClose
        title: "Aprovação necessária"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: 12
            Text { Layout.fillWidth: true; text: String(root.approvalPayload.reason || root.approvalPayload.description || "O agente solicitou permissão para continuar."); color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }
            RowLayout {
                Layout.fillWidth: true
                VrButton { text: "Negar"; onClicked: { chat.decideApproval(false, false); approvalDialog.close() } }
                Item { Layout.fillWidth: true }
                VrButton { text: "Aprovar uma vez"; onClicked: { chat.decideApproval(true, false); approvalDialog.close() } }
                VrButton { text: "Aprovar nesta sessão"; variant: "primary"; onClicked: { chat.decideApproval(true, true); approvalDialog.close() } }
            }
        }
        background: Rectangle { color: Theme.palette.surface; border.width: 1; border.color: Theme.palette.warning; radius: Theme.radiusPopup }
    }

    function surfaceForPage(page) {
        for (var index = 0; index < root.surfaceTabs.length; ++index) {
            if (root.surfaceTabs[index].page === page) return root.surfaceTabs[index]
        }
        return { title: "Superfície", kind: "browser", page: page }
    }

    function activateModelShortcut(index) {
        if (newChatProjectPopup.opened || approvalDialog.opened) return
        if (chat.turnRunning || index >= chat.modelItems.length) return
        chat.setModel(index)
    }

    function activateConversation(conversationId) {
        chat.saveCurrentDraft(composerInput.text)
        chat.selectConversationId(conversationId)
        messageList.followTail = true
        tailTimer.restart()
    }

    function openConversationMenu(conversationId, positionX, positionY) {
        root.activateConversation(conversationId)
        conversationContextMenu.x = Math.max(4,
            Math.min(root.width - conversationContextMenu.width - 4, positionX))
        conversationContextMenu.y = Math.max(4,
            Math.min(root.height - conversationContextMenu.height - 4, positionY))
        conversationContextMenu.open()
    }

    function openSurface(page) {
        root.surfaceVisible = true
        var nextTabs = root.openSurfaceTabs.slice(0)
        var alreadyOpen = false
        for (var index = 0; index < nextTabs.length; ++index) {
            if (nextTabs[index].page === page) {
                alreadyOpen = true
                break
            }
        }
        if (!alreadyOpen)
            nextTabs.push(root.surfaceForPage(page))
        root.openSurfaceTabs = nextTabs
        root.surfaceIndex = page
        if (page === 3) {
            root.surfaceFilePath = ""
            root.surfaceFilePreview = ""
            root.expandedFileFolders = ({})
            root.surfaceFiles = chat.fileSuggestions(fileSearch.text)
        }
        if (page === 5 && root.selectedAgentIndex < 0 && chat.agentItems.length)
            root.selectedAgentIndex = 0
    }

    Dialog {
        id: conversationDeleteDialog
        objectName: "conversationDeleteDialog"
        anchors.centerIn: parent
        width: 430
        modal: true
        title: "Excluir esta conversa?"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: Theme.spaceMd
            Text { Layout.fillWidth: true; text: "A conversa será removida da lista e enviada para a lixeira."; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; wrapMode: Text.WordWrap }
            RowLayout {
                Layout.fillWidth: true
                VrButton { text: "Cancelar"; onClicked: conversationDeleteDialog.close() }
                Item { Layout.fillWidth: true }
                VrButton {
                    text: chat.conversationDeleteRunning ? "Excluindo…" : "Excluir"
                    variant: "danger"
                    enabled: !chat.conversationDeleteRunning
                    onClicked: {
                        conversationDeleteDialog.close()
                        chat.trashCurrentConversation()
                        composerInput.clear()
                    }
                }
            }
        }
        background: Rectangle { color: Theme.palette.chatComposer; border.width: 1; border.color: Theme.palette.danger; radius: Theme.radiusPopup }
    }

    function toggleFileFolder(path) {
        var next = ({})
        for (var key in root.expandedFileFolders)
            next[key] = root.expandedFileFolders[key]
        next[path] = !next[path]
        root.expandedFileFolders = next
    }

    function fileTreeItemVisible(item) {
        if (!item) return false
        if (fileSearch.text.trim().length > 0) return true
        var parentPath = String(item.parent || "")
        while (parentPath.length > 0) {
            if (!root.expandedFileFolders[parentPath]) return false
            var separator = parentPath.lastIndexOf("/")
            parentPath = separator >= 0 ? parentPath.substring(0, separator) : ""
        }
        return true
    }

    function closeSurface(page) {
        var nextTabs = []
        var removedIndex = -1
        for (var index = 0; index < root.openSurfaceTabs.length; ++index) {
            if (root.openSurfaceTabs[index].page === page) {
                removedIndex = index
                continue
            }
            nextTabs.push(root.openSurfaceTabs[index])
        }
        root.openSurfaceTabs = nextTabs
        if (root.surfaceIndex !== page) return
        if (!nextTabs.length) {
            root.surfaceIndex = 0
            return
        }
        root.surfaceIndex = nextTabs[Math.min(Math.max(0, removedIndex), nextTabs.length - 1)].page
    }

    function filteredProjects(query) {
        var source = chat.projectItems || []
        var needle = String(query || "").trim().toLowerCase()
        var result = []
        var hasConcreteProject = false
        for (var sourceIndex = 0; sourceIndex < source.length; ++sourceIndex) {
            if (String(source[sourceIndex].path || "").length) {
                hasConcreteProject = true
                break
            }
        }
        for (var index = 0; index < source.length; ++index) {
            var item = source[index]
            var label = String(item.label || "")
            var path = String(item.path || "")
            if (hasConcreteProject && !path.length) continue
            if (needle.length && (label + " " + path).toLowerCase().indexOf(needle) < 0)
                continue
            result.push({
                label: label,
                path: path,
                sourceIndex: index,
                shortcut: result.length < 9 ? "Ctrl+" + (result.length + 1) : ""
            })
        }
        return result
    }

    function filteredAddProjectSources(query) {
        var needle = String(query || "").trim().toLowerCase()
        if (!needle.length) return root.addProjectSources
        return root.addProjectSources.filter(function(item) {
            return item.title.toLowerCase().indexOf(needle) >= 0
                || item.description.toLowerCase().indexOf(needle) >= 0
        })
    }

    function chooseNewChatProject(item) {
        if (!item || item.sourceIndex === undefined) return
        chat.setProject(Number(item.sourceIndex))
        newChatProjectPopup.close()
        composerInput.forceActiveFocus()
    }

    function openProjectSelectorMenu() {
        projectSelector.openSelectorMenu()
    }

    function clickProjectSettingsButton(index) {
        return projectSelector.clickSettingsButton(index)
    }

    function clickProjectSelectorItem(index) {
        return projectSelector.clickProjectButton(index)
    }

    function openProjectSettings(index) {
        var source = chat.projectItems || []
        if (index <= 0 || index >= source.length) return
        chat.setProject(index)
        source = chat.projectItems || []
        var item = source[index]
        if (!item || !String(item.path || "").length) return
        root.surfaceVisible = false
        root.projectSettingsIndex = index
        root.projectSettingsPath = String(item.path || "")
        root.projectSettingsName = String(item.label || "")
        root.projectSettingsIconPath = String(item.icon || "")
        root.projectSettingsVisible = true
        Qt.callLater(function() {
            projectSettingsPage.forceActiveFocus()
            projectSettingsPage.resetView()
        })
    }

    function syncOpenProjectSettings() {
        if (!root.projectSettingsVisible || !root.projectSettingsPath.length) return
        var source = chat.projectItems || []
        for (var index = 1; index < source.length; ++index) {
            if (String(source[index].path || "") !== root.projectSettingsPath) continue
            root.projectSettingsIndex = index
            root.projectSettingsName = String(source[index].label || "")
            root.projectSettingsIconPath = String(source[index].icon || "")
            return
        }
        root.projectSettingsVisible = false
    }

    function projectSettingsOriginalName() {
        var source = chat.projectItems || []
        if (root.projectSettingsIndex <= 0 || root.projectSettingsIndex >= source.length)
            return ""
        return String(source[root.projectSettingsIndex].label || "")
    }

    function currentModelLabel() {
        var models = chat.modelItems || []
        var modelIndex = Number(chat.modelIndex)
        var modelLabel = modelIndex >= 0 && modelIndex < models.length
            ? String(models[modelIndex].label || models[modelIndex].value || "Modelo atual")
            : "Modelo atual"
        var efforts = chat.effortItems || []
        var effortIndex = Number(chat.effortIndex)
        var effortLabel = effortIndex >= 0 && effortIndex < efforts.length
            ? String(efforts[effortIndex].label || "") : ""
        return effortLabel.length ? modelLabel + " · " + effortLabel : modelLabel
    }

    function relativeAge(value) {
        var stamp = new Date(String(value || ""))
        if (isNaN(stamp.getTime())) return ""
        var minutes = Math.max(0, Math.floor((Date.now() - stamp.getTime()) / 60000))
        if (minutes < 1) return "agora"
        if (minutes < 60) return minutes + "m"
        var hours = Math.floor(minutes / 60)
        if (hours < 24) return hours + "h"
        var days = Math.floor(hours / 24)
        return days < 30 ? days + "d" : Math.floor(days / 30) + "mo"
    }

    function elapsedFromEpoch(value) {
        var seconds = Math.max(0, Math.floor(root.clockNow - Number(value || root.clockNow)))
        if (seconds < 60) return seconds + "s"
        var minutes = Math.floor(seconds / 60)
        if (minutes < 60) return minutes + "m"
        return Math.floor(minutes / 60) + "h"
    }

    function openLocalFolderBrowser() {
        root.addProjectView = "folder"
        chat.beginProjectFolderBrowse()
    }

    function activateProjectSource(sourceKey) {
        if (String(sourceKey) !== "local") return false
        root.openLocalFolderBrowser()
        return true
    }

    function submitMessage() {
        if ((!composerInput.text.trim().length && !chat.attachments.length) || chat.turnRunning) return
        var value = composerInput.text
        messageList.followTail = true
        composerInput.clear()
        composerAssistPopup.close()
        chat.sendMessage(value)
    }

    function handleComposerEnter(event) {
        if (event.modifiers & Qt.ShiftModifier) {
            event.accepted = false
            return
        }
        event.accepted = true
        root.submitMessage()
    }

    function agentDetailText() {
        if (root.selectedAgentIndex < 0 || root.selectedAgentIndex >= chat.agentItems.length)
            return "Selecione um agente para ver tarefa, roteamento e saída."
        var item = chat.agentItems[root.selectedAgentIndex]
        var sections = [item.label + "\n" + item.model + " · effort " + item.effort + " · " + item.statusLabel]
        if (item.module) sections.push("Módulo: " + item.module)
        if (item.source) sections.push("Fonte: " + item.source)
        if (item.task) sections.push("Tarefa: " + item.task)
        if (item.reason) sections.push("Roteamento: " + item.reason)
        if (item.output) sections.push(item.output)
        else if (item.status === "executando") sections.push("O agente está produzindo a resposta…")
        else sections.push("Aguardando saída do agente.")
        return sections.join("\n\n")
    }

    function updateComposerSuggestions() {
        var value = composerInput.text
        var trimmed = value.trim()
        var commands = [
            {label:"/model",description:"Escolher modelo e provedor",action:"model"},
            {label:"/effort",description:"Definir esforço de raciocínio",action:"effort"},
            {label:"/permissions",description:"Definir perfil de aprovação",action:"permissions"},
            {label:"/skills",description:"Ver skills disponíveis",action:"skills"},
            {label:"/tools",description:"Ver tools e MCP",action:"tools"},
            {label:"/vr",description:"Alternar Off / VR / VR Ultra",action:"vr"},
            {label:"/pesquisa",description:"Pesquisa multiagente: /pesquisa <pergunta>",action:"pesquisa"}
        ]
        if (trimmed.length && trimmed[0] === "/" && trimmed.indexOf(" ") < 0) {
            var needle = trimmed.substring(1).toLowerCase()
            composerSuggestions = commands.filter(function(item) {
                return item.label.substring(1).toLowerCase().indexOf(needle) >= 0
            })
            composerAssistPopup.open()
            return
        }
        var at = value.lastIndexOf("@")
        if (at >= 0) {
            var query = value.substring(at + 1)
            if (query.indexOf(" ") < 0 && query.indexOf("\n") < 0) {
                var files = chat.fileSuggestions(query)
                composerSuggestions = files.map(function(item) {
                    return {label:item.label,description:"Arquivo do projeto",action:"reference",path:item.path,start:at}
                })
                if (composerSuggestions.length) composerAssistPopup.open()
                else composerAssistPopup.close()
                return
            }
        }
        composerSuggestions = []
        composerAssistPopup.close()
    }

    function chooseComposerSuggestion(item) {
        composerAssistPopup.close()
        if (item.action === "model") modelSelector.openPicker()
        else if (item.action === "effort") effortSelector.openPicker()
        else if (item.action === "permissions") approvalSelector.openPicker()
        else if (item.action === "vr") chat.cycleVrMode()
        else if (item.action === "pesquisa") {
            composerInput.text = "/pesquisa "
            composerInput.forceActiveFocus()
        }
        else if (item.action === "skills" || item.action === "tools") extensionsDialog.open()
        else if (item.action === "reference") {
            var before = composerInput.text.substring(0, item.start)
            composerInput.text = before + "@\"" + item.path + "\" "
            composerInput.cursorPosition = composerInput.length
        }
    }

    function insertReference(reference) {
        var separator = composerInput.text.length && !composerInput.text.endsWith(" ") ? " " : ""
        composerInput.text += separator + reference + " "
        composerInput.cursorPosition = composerInput.length
        composerInput.forceActiveFocus()
    }

    function greetingText() {
        var hour = new Date(root.clockNow * 1000).getHours()
        if (hour >= 5 && hour < 12) return "Bom dia! Como posso ajudar?"
        if (hour >= 12 && hour < 18) return "Boa tarde! Como posso ajudar?"
        return "Boa noite! Como posso ajudar?"
    }

    function greetingPrompt() {
        var now = new Date(root.clockNow * 1000)
        var phrases = [
            "Vamos investigar uma regra do VRMaster ou orientar um atendimento?",
            "Traga a dúvida de suporte, implantação ou operação que vamos resolver.",
            "Posso consultar a base VR, analisar o projeto ou preparar um passo a passo.",
            "Qual processo, integração ou comportamento do ERP merece atenção agora?"
        ]
        return phrases[(now.getDate() + Math.floor(now.getHours() / 6))
            % phrases.length]
    }

    function expertProfileSelected(key) {
        if (!chat.seniorProfileEnabled) return false
        if (key === "senior") return chat.vrResponseMode === "auto"
        return chat.vrResponseMode === key
    }

    function activateExpertProfile(key) {
        if (root.expertProfileSelected(key)) {
            chat.setSeniorProfileEnabled(false)
            return
        }
        chat.setSeniorProfileEnabled(true)
        chat.setVrResponseMode(key === "senior" ? "auto" : key)
    }

    function navigateBrowser(value) {
        value = String(value || "").trim()
        if (!value.length) return
        root.pendingBrowserAddress = value
        if (!browserLoader.active)
            browserLoader.active = true
        else if (browserLoader.item) {
            browserLoader.item.navigate(value)
            root.pendingBrowserAddress = ""
        }
    }

    function browserBack() {
        if (browserLoader.item) browserLoader.item.goBackPage()
    }

    function browserForward() {
        if (browserLoader.item) browserLoader.item.goForwardPage()
    }

    function reloadBrowser() {
        if (browserLoader.item) browserLoader.item.reloadPage()
    }
}
