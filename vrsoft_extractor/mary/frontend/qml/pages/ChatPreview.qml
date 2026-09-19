pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models
import "../components"
import "../theme"

Item {
    id: root
    property alias chatHeaderHandle: chatHeader
    property alias chatMainHandle: chatMain
    property alias composerAssistDelayHandle: composerAssistDelay
    property alias landingHandle: landing
    property alias messageListHandle: messageList
    readonly property real usagePanelHeight: usageLimitsDialog.visible ? usageLimitsDialog.height + 8 : 0
    readonly property var approvalSelector: composerCard.approvalSelectorItem
    readonly property var composerInput: composerCard.composerInputItem
    readonly property var effortSelector: composerCard.effortSelectorItem
    readonly property var modelSelector: composerCard.modelSelectorItem
    objectName: "chatPage"
    required property var chatBridge
    required property var studioBridge
    required property var frontendBridge
    component ProjectMenuEntry: MenuItem {
        id: entry
        property string iconPath: ""
        property string iconKind: ""
        property string iconEmoji: ""
        property string iconColor: ""
        property string iconText: ""
        property bool isAll: false
        property string subtitle: ""
        implicitHeight: subtitle.length ? 44 : 36
        contentItem: RowLayout {
            spacing: 9
            VrProjectIcon {
                Layout.preferredWidth: 24
                Layout.preferredHeight: 24
                boxSize: 24
                iconSize: 14
                projectLabel: entry.text
                iconPath: entry.iconPath
                iconKind: entry.iconKind
                iconEmoji: entry.iconEmoji
                iconColor: entry.iconColor
                iconText: entry.iconText
                isAll: entry.isAll
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 0
                Text {
                    Layout.fillWidth: true
                    text: entry.text
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.Medium
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
                Text {
                    visible: entry.subtitle.length > 0
                    Layout.fillWidth: true
                    text: entry.subtitle
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                    elide: Text.ElideMiddle
                    maximumLineCount: 1
                }
            }
        }
        background: Rectangle {
            radius: 7
            color: entry.highlighted ? Theme.palette.chatControl : "transparent"
        }
    }
    // Atalhos estilo T3 Code (pills do rodapé do seletor de projetos).
    component KbdHint: Rectangle {
        property string label: ""
        implicitWidth: Math.max(22, hintText.implicitWidth + 10)
        implicitHeight: 20
        radius: 5
        color: Theme.palette.chatControl
        border.width: 1
        border.color: Theme.palette.chatBorder
        Text {
            id: hintText
            anchors.centerIn: parent
            text: parent.label
            color: Theme.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeMicro
            font.weight: Font.DemiBold
        }
    }
    property bool conversationSidebarVisible: width >= 1000
    property bool surfaceVisible: false
    property int surfaceIndex: 0
    property int displayedSurfaceIndex: 0
    property var openSurfaceTabs: []
    property bool activityExpanded: false
    property bool taskBarExpanded: false
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
    property int composerAssistIndex: 0
    property var surfaceFiles: []
    property var expandedFileFolders: ({})
    property string surfaceFilePath: ""
    property string surfaceFilePreview: ""
    property var contextItems: []
    property int selectedAgentIndex: -1
    property string pendingBrowserAddress: ""
    property string conversationMenuConversationId: ""
    property bool composerDropActive: false
    property real clockNow: Date.now() / 1000
    property var expertProfiles: [
        { key: "senior", label: "Sênior", icon: "expertSenior" },
        { key: "training", label: "Treinamento", icon: "expertTraining" },
        { key: "support", label: "Suporte", icon: "expertSupport" },
        { key: "implementation", label: "Implantação", icon: "expertImplementation" }
    ]
    property real expertReveal: root.chatBridge.vrMode !== "off" ? 1.0 : 0.0
    readonly property real expertStripHeight: 42 * expertReveal
    property string addProjectView: "sources"
    property bool projectSettingsVisible: false
    property int projectSettingsIndex: -1
    property string projectSettingsName: ""
    property string projectSettingsPath: ""
    property string projectSettingsIconPath: ""
    property string projectSettingsIconKind: ""
    property string projectSettingsIconEmoji: ""
    property string projectSettingsIconColor: ""
    property string projectSettingsIconText: ""
    property real conversationSidebarWidth: conversationSidebarVisible ? (width < 760 ? 220 : 260) : 0
    readonly property real sidebarBorderX: conversationSidebarVisible && conversationSidebar.visible
        ? (conversationSidebar.width + 3)
        : 0
    readonly property real sidebarBorderOffset: conversationSidebarVisible && conversationSidebar.visible
        ? (conversationSidebar.width + 4)
        : 0
    readonly property real surfaceBorderOffset: surfaceVisible && surfacePanel.visible
        ? (surfacePanel.width + 4)
        : 0
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
        enabled: !root.frontendBridge.reduceMotion
        NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
    }
    Behavior on surfacePanelWidth {
        enabled: !root.frontendBridge.reduceMotion
        NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
    }
    Behavior on expertReveal {
        enabled: !root.frontendBridge.reduceMotion
        NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
    }

    onSurfaceIndexChanged: {
        if (root.frontendBridge.reduceMotion || !root.surfaceVisible) {
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
        target: root.chatBridge
        function onApprovalRequested(payload) {
            root.approvalPayload = payload
            if (payload.request_id !== undefined) {
                // Approvals take precedence over the task drawer: keep only
                // the compact summary so the blocking surface stays visible.
                root.taskBarExpanded = false
                approvalDialog.open()
            } else approvalDialog.close()
        }
        function onStateChanged() {
            if (root.chatBridge.turnRunning && !root.previousTurnRunning) {
                root.taskBarExpanded = false
                root.activityExpanded = false
            }
            root.previousTurnRunning = root.chatBridge.turnRunning
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
            if (!root.frontendBridge.browserAgentAccess || !root.frontendBridge.browserAutoShowPreview)
                return
            root.openSurface(1)
            root.navigateBrowser(address)
        }
        function onProjectsChanged() {
            root.syncOpenProjectSettings()
        }
    }

    Connections {
        target: root.studioBridge
        function onProvidersChanged() {
            var providers = root.studioBridge.providerItems
            for (var i = 0; i < providers.length; ++i)
                if (providers[i].runtimeState === "installing") return
            root.chatBridge.refreshModels()
        }
    }

    Component.onCompleted: {
        root.previousTurnRunning = root.chatBridge.turnRunning
        // Finish constructing delegates before refreshModels emits stateChanged.
        Qt.callLater(root.chatBridge.refreshModels)
    }

    Timer {
        interval: 1000
        running: root.visible && root.chatBridge.turnRunning
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
            id: chatSplitHandle
            implicitWidth: 7
            color: "transparent"

            // Left slice matches sidebar background
            Rectangle {
                anchors.left: parent.left
                anchors.right: chatCenterLine.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                color: Theme.palette.chatSidebar
            }

            // Right slice matches content background
            Rectangle {
                anchors.left: chatCenterLine.right
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                color: Theme.palette.chatBackground
            }

            // Crisp 1px hairline divider
            Rectangle {
                id: chatCenterLine
                objectName: "chatCenterLine"
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
                    enabled: !root.frontendBridge.reduceMotion
                    ColorAnimation { duration: Theme.fastDuration }
                }
                Behavior on opacity {
                    enabled: !root.frontendBridge.reduceMotion
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
                    enabled: !root.frontendBridge.reduceMotion
                    NumberAnimation { duration: Theme.fastDuration }
                }
            }
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
                    enabled: !root.frontendBridge.reduceMotion
                    NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
                }
            }
            Behavior on opacity {
                enabled: !root.frontendBridge.reduceMotion
                NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
            }
            Rectangle { anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right; width: 1; color: Theme.palette.chatBorder; visible: root.width < 760 }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6

                Item {
                    id: searchBarContainer
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    Layout.minimumHeight: 32
                    Layout.maximumHeight: 32
                    Layout.fillHeight: false

                    RowLayout {
                        anchors.fill: parent
                        spacing: 6

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumWidth: 0

                            VrTextField {
                                id: conversationSearch
                                objectName: "conversationSearch"
                                anchors.fill: parent
                                leftPadding: 30
                                rightPadding: 6
                                placeholderText: "Pesquisar"
                                ToolTip.visible: hovered && !activeFocus
                                ToolTip.delay: 600
                                ToolTip.text: "Pesquisar conversas"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(14)
                                font.weight: Font.Medium
                                renderType: Theme.textRenderType
                                color: Theme.palette.text
                                background: Rectangle {
                                    radius: Theme.radiusSmall
                                    color: conversationSearch.activeFocus
                                        ? Theme.palette.chatControl
                                        : (conversationSearch.hovered
                                            ? Qt.rgba(255, 255, 255, 0.04)
                                            : "transparent")
                                    border.width: 1
                                    border.color: conversationSearch.activeFocus
                                        ? Theme.palette.focus
                                        : (conversationSearch.hovered
                                            ? Qt.rgba(255, 255, 255, 0.08)
                                            : "transparent")

                                    Behavior on color {
                                        ColorAnimation { duration: Theme.fastDuration }
                                    }
                                    Behavior on border.color {
                                        ColorAnimation { duration: Theme.fastDuration }
                                    }
                                }
                                onTextChanged: searchDelay.restart()
                            }
                            VrLineIcon {
                                anchors.left: parent.left
                                anchors.leftMargin: 7
                                anchors.verticalCenter: parent.verticalCenter
                                width: 16
                                height: 16
                                kind: "search"
                                foreground: conversationSearch.activeFocus
                                    ? Theme.palette.text : Theme.palette.mutedText
                            }
                        }

                        // Grouped actions for folder / chat (transparent, like T3)
                        Rectangle {
                            id: folderActionsCapsule
                            Layout.preferredHeight: 32
                            Layout.alignment: Qt.AlignVCenter
                            implicitWidth: folderActionsRow.implicitWidth + 4
                            radius: 8
                            color: "transparent"
                            border.width: 0

                            RowLayout {
                                id: folderActionsRow
                                anchors.centerIn: parent
                                spacing: 4

                                VrProjectSelector {
                                    id: projectSelector
                                    objectName: "projectSelector"
                                    compact: true
                                    anchorItem: searchBarContainer
                                    model: root.chatBridge.projectItems
                                    currentIndex: root.chatBridge.currentProjectIndex
                                    popupObjectName: "projectSelectorMenu"
                                    onActivated: index => {
                                        root.projectSettingsVisible = false
                                        root.chatBridge.setProject(index)
                                    }
                                    onSettingsRequested: index => root.openProjectSettings(index)
                                    onNewProjectRequested: {
                                        root.addProjectView = "sources"
                                        addProjectSearch.clear()
                                        addProjectPopup.open()
                                    }
                                }

                                VrIconButton {
                                    id: addProjectButton
                                    objectName: "addProjectButton"
                                    implicitWidth: 32
                                    implicitHeight: 32
                                    iconSize: 16
                                    iconKind: "folderPlus"
                                    focusPolicy: Qt.NoFocus
                                    foreground: hovered ? Theme.palette.text : Theme.palette.mutedText
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Criar novo projeto"
                                    Accessible.name: "Criar novo projeto"
                                    onClicked: {
                                        root.addProjectView = "sources"
                                        addProjectSearch.clear()
                                        addProjectPopup.open()
                                    }
                                }

                                VrIconButton {
                                    id: newChatButton
                                    objectName: "newChatButton"
                                    implicitWidth: 32
                                    implicitHeight: 32
                                    iconSize: 16
                                    iconKind: "newChat"
                                    focusPolicy: Qt.NoFocus
                                    foreground: hovered ? Theme.palette.text : Theme.palette.mutedText
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Nova conversa"
                                    Accessible.name: "Nova conversa"
                                    onClicked: {
                                        root.projectSettingsVisible = false
                                        conversationSearch.clear()
                                        root.chatBridge.saveCurrentDraft(composerInput.text)
                                        root.chatBridge.startNewChat()
                                        composerInput.clear()
                                        Qt.callLater(function() {
                                            newChatProjectPopup.open()
                                        })
                                    }
                                }
                            }
                        }
                    }
                }

                ListView {
                    id: conversationList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.topMargin: 2
                    clip: true
                    reuseItems: true
                    cacheBuffer: 240
                    spacing: 4
                    model: root.chatBridge.conversations
                    currentIndex: root.chatBridge.selectedIndex
                    ScrollBar.vertical: VrScrollBar { }
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
                        required property string vrMode
                        required property bool vrEnabled
                        required property string taskStep
                        required property int taskCompleted
                        required property int taskTotal
                        width: conversationList.width
                        height: 78
                        radius: 8
                        color: root.chatBridge.selectedIndex === index ? Theme.palette.selection
                            : itemHover.hovered ? Theme.palette.chatControl : "transparent"
                        border.width: 1
                        border.color: root.chatBridge.selectedIndex === index
                            ? Qt.rgba(255, 255, 255, 0.08)
                            : (itemHover.hovered ? Qt.rgba(255, 255, 255, 0.04) : "transparent")
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
                                    Layout.preferredWidth: 16
                                    Layout.preferredHeight: 16
                                    kind: conversationItem.editing ? "edit" : "folder"
                                    foreground: conversationItem.editing
                                        ? "#F3C74E" : Theme.palette.mutedText
                                }
                                Text {
                                    id: conversationProjectLabel
                                    text: conversationItem.projectLabel
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: Font.Medium
                                    renderType: Theme.textRenderType
                                    elide: Text.ElideRight
                                    maximumLineCount: 1
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 30
                                    Layout.preferredWidth: Math.max(30, conversationItem.width - (conversationVrBadge.visible ? conversationVrBadge.implicitWidth + 10 : 0) - 118)
                                    ToolTip.visible: projectLabelHover.hovered
                                    ToolTip.delay: 500
                                    ToolTip.text: conversationItem.projectLabel
                                    HoverHandler { id: projectLabelHover }
                                }
                                Rectangle {
                                    id: conversationVrBadge
                                    objectName: "conversationVrBadge"
                                    visible: conversationItem.vrEnabled && conversationItem.vrMode !== "off"
                                    Layout.alignment: Qt.AlignVCenter
                                    implicitHeight: 16
                                    implicitWidth: conversationVrBadgeText.implicitWidth + 8
                                    radius: 4
                                    color: Theme.palette.accessibleOrange

                                    Text {
                                        id: conversationVrBadgeText
                                        anchors.centerIn: parent
                                        text: conversationItem.vrMode === "ultra" ? "VR Ultra" : "VR"
                                        color: "#FFFFFF"
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeMicro
                                        font.weight: Font.DemiBold
                                    }

                                    ToolTip.visible: conversationVrBadgeHover.hovered
                                    ToolTip.text: conversationItem.vrMode === "ultra" ? "VR Ultra ativo" : "VR ativo"
                                    ToolTip.delay: 300

                                    HoverHandler {
                                        id: conversationVrBadgeHover
                                    }
                                }
                                Item {
                                    Layout.fillWidth: true
                                }
                                VrLineIcon {
                                    visible: conversationItem.pinned && !conversationItem.running
                                    Layout.preferredWidth: 16
                                    Layout.preferredHeight: 16
                                    kind: "pin"
                                    foreground: Theme.palette.brandOrange
                                }
                                Item {
                                    visible: conversationItem.running
                                    Layout.preferredWidth: 16
                                    Layout.preferredHeight: 16
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
                                            running: conversationItem.running && !root.frontendBridge.reduceMotion
                                            loops: Animation.Infinite
                                            from: 0; to: 360; duration: 1100
                                        }
                                    }
                                }
                                Text {
                                    visible: !conversationItem.editing
                                    text: conversationItem.running
                                        ? "Trabalhando " + root.elapsedFromEpoch(conversationItem.startedAtEpoch)
                                        : root.relativeAge(conversationItem.updatedAt)
                                    color: conversationItem.running ? "#18A8E8" : Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: conversationItem.running ? Font.DemiBold : Font.Medium
                                    renderType: Theme.textRenderType
                                }
                                VrIconButton {
                                    id: discardDraftButton
                                    objectName: "discardDraftButton"
                                    visible: conversationItem.editing
                                    Layout.preferredWidth: 18
                                    Layout.preferredHeight: 18
                                    implicitWidth: 18
                                    implicitHeight: 18
                                    iconKind: "close"
                                    iconSize: 10
                                    round: true
                                    focusPolicy: Qt.NoFocus
                                    foreground: hovered ? Theme.palette.text : Theme.palette.mutedText
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Descartar rascunho"
                                    ToolTip.delay: 300
                                    Accessible.name: "Descartar rascunho"
                                    onClicked: {
                                        if (conversationItem.conversationId === root.chatBridge.selectedConversationId) {
                                            composerInput.clear()
                                        }
                                        root.chatBridge.discardDraft(conversationItem.conversationId)
                                    }
                                }
                            }
                            Text {
                                objectName: "conversationTitle"
                                Layout.fillWidth: true
                                text: conversationItem.title
                                color: Theme.palette.headingText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(14)
                                font.weight: Font.Medium
                                renderType: Theme.textRenderType
                                elide: Text.ElideRight
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 5
                                Text {
                                    Layout.fillWidth: true
                                    text: (conversationItem.running && conversationItem.taskTotal > 0 && conversationItem.taskStep.length > 0)
                                        ? conversationItem.taskCompleted + "/" + conversationItem.taskTotal + " · " + conversationItem.taskStep
                                        : conversationItem.modelName
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: Font.Medium
                                    renderType: Theme.textRenderType
                                    elide: Text.ElideRight
                                    maximumLineCount: 1
                                    ToolTip.visible: taskHover.hovered && (conversationItem.running && conversationItem.taskTotal > 0 && conversationItem.taskStep.length > 0)
                                    ToolTip.delay: 500
                                    ToolTip.text: conversationItem.taskCompleted + "/" + conversationItem.taskTotal + " · " + conversationItem.taskStep
                                    HoverHandler { id: taskHover }
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
                                    Layout.preferredWidth: 16
                                    Layout.preferredHeight: 16
                                    provider: conversationItem.provider.toLowerCase()
                                }
                            }
                        }
                        HoverHandler { id: itemHover }
                        TapHandler {
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onTapped: function(eventPoint, button) {
                                if (discardDraftButton.visible) {
                                    var p = discardDraftButton.mapFromItem(conversationItem, eventPoint.position.x, eventPoint.position.y)
                                    if (p.x >= 0 && p.x <= discardDraftButton.width && p.y >= 0 && p.y <= discardDraftButton.height) {
                                        return
                                    }
                                }
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
                        visible: !root.chatBridge.hasConversations
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
                    onClicked: root.frontendBridge.setCurrentPage(7)
                }
            }
        }

        Item {
            id: chatMain
            SplitView.minimumWidth: 320
            SplitView.fillWidth: true

            Item {
                id: chatHeader
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 0
                visible: false
                property bool sidebarVisible: root.conversationSidebarVisible
                property bool panelVisible: root.surfaceVisible
                property bool hasMessages: messageList.count > 0
                property string title: root.chatBridge.selectedTitle
                property string projectLabel: root.chatBridge.currentProjectIndex > 0 && root.chatBridge.currentProjectIndex < root.chatBridge.projectItems.length
                    ? root.chatBridge.projectItems[root.chatBridge.currentProjectIndex].label : "Projeto"
                property int agentCount: root.chatBridge.agentItems.length
                signal toggleSidebar()
                signal copyConversation()
                signal showAgents()
                signal showPanel()
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
                // Active scroll anchor for collapsible message transitions
                // (Mostrar mais, Mostrar menos, streaming termination).
                // 0: none, 1: message completely above, 2: viewport inside message
                property int anchorMode: 0
                property Item anchorItem: null
                property real anchorOffset: 0
                property real lastAnchorContentHeight: 0
                readonly property bool hasAnchor: anchorMode !== 0
                function beginManualScroll() {
                    wheelAnimation.stop()
                    followTail = false
                    holdingReader = false
                    readerTimer.stop()
                    tailTimer.stop()
                    clearAnchor()
                }
                function clearAnchor() {
                    anchorMode = 0
                    anchorItem = null
                    anchorOffset = 0
                }
                function preserveReader() {
                    if (hasAnchor || followTail || moving || dragging || wheelAnimation.running || messageScrollBar.pressed) return
                    if (!holdingReader) readerY = contentY
                    holdingReader = true
                    readerTimer.restart()
                    Qt.callLater(restoreReader)
                }
                function restoreReader() {
                    if (hasAnchor)
                        return
                    if (holdingReader && !followTail && !moving && !wheelAnimation.running && !messageScrollBar.pressed)
                        contentY = readerY
                }
                function anchorMessage(item) {
                    if (followTail || !item)
                        return
                    // If this item is already actively anchored, keep the existing
                    // geometric anchor across rapid toggles so transient heights
                    // do not cause drift or incorrect re-classification.
                    if (anchorItem === item && hasAnchor)
                        return

                    holdingReader = false
                    readerTimer.stop()

                    var itemTop = item.y
                    var itemBottom = itemTop + item.height
                    var vTop = contentY

                    if (itemBottom <= vTop) {
                        // Caso A: Mensagem totalmente acima do viewport
                        // anchorOffset is the distance from message bottom to viewport top
                        anchorMode = 1
                        anchorItem = item
                        anchorOffset = vTop - itemBottom
                    } else if (itemTop < vTop && itemBottom > vTop) {
                        // Caso B: Viewport comeca dentro da mensagem
                        // anchorOffset is relative position inside message
                        anchorMode = 2
                        anchorItem = item
                        anchorOffset = vTop - itemTop
                    } else {
                        // Caso C: Mensagem comeca dentro ou abaixo do viewport
                        anchorMode = 0
                        anchorItem = null
                        anchorOffset = 0
                    }
                }
                function isAnchorAnimating() {
                    try {
                        return Boolean(anchorItem && anchorItem.isCollapsibleAnimating)
                    } catch (e) {
                        return false
                    }
                }
                function applyAnchorAdjustment() {
                    if (!hasAnchor || !anchorItem)
                        return
                    var maxY = Math.max(0, contentHeight - height)
                    var targetY = contentY
                    if (anchorMode === 1) {
                        targetY = anchorItem.y + anchorItem.height + anchorOffset
                    } else if (anchorMode === 2) {
                        var maxOffset = Math.max(0, anchorItem.height - 20)
                        var targetOffset = Math.min(anchorOffset, maxOffset)
                        targetY = anchorItem.y + targetOffset
                    }
                    contentY = Math.max(0, Math.min(maxY, targetY))
                    if (!isAnchorAnimating()) {
                        clearAnchor()
                    }
                }
                function finishAnchor(item) {
                    if (anchorItem === item || !item) {
                        if (hasAnchor)
                            applyAnchorAdjustment()
                        clearAnchor()
                    }
                }
                function compensateToggle(item, heightDelta) {
                    if (heightDelta === 0 || followTail)
                        return
                    if (!hasAnchor && item)
                        anchorMessage(item)
                }
                Timer {
                    id: readerTimer
                    interval: 120
                    onTriggered: { messageList.restoreReader(); messageList.holdingReader = false }
                }
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: chatHeader.bottom
                anchors.bottom: parent.bottom
                anchors.leftMargin: chatMain.width < 600 ? 14 : 24
                anchors.rightMargin: chatMain.width < 600 ? 14 : 24
                anchors.topMargin: 20
                anchors.bottomMargin: 0
                visible: count > 0
                clip: true
                // Keep actual message geometry stable across the entire history.
                // ListView estimates unseen heights from visible delegates, which
                // changes the scroll range drastically for long chat responses.
                Column {
                    id: messageColumn
                    objectName: "messageColumn"
                    width: messageList.width
                    spacing: Theme.messageGap
                    Repeater {
                        id: messageRepeater
                        objectName: "messageRepeater"
                        model: root.chatBridge.messages
                        delegate: Item {
                            id: messageItem
                            objectName: "messageItem"
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
                            readonly property bool isCollapsibleAnimating: presentation.item && presentation.item.animating ? true : false
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
                                    property bool cardExpanded: false
                                    items: messageItem.messageKey ? messageItem.activityData : root.chatBridge.traceItems
                                    reasoningText: messageItem.messageKey ? "" : root.chatBridge.reasoningText
                                    statusText: messageItem.messageKey ? (messageItem.isStreaming ? "Trabalhando…" : "Concluído") : root.chatBridge.statusText
                                    elapsedLabel: root.chatBridge.activityElapsedLabel
                                    taskStep: messageItem.messageKey ? "" : String(root.chatBridge.taskProgress.step || "")
                                    running: messageItem.messageKey ? messageItem.isStreaming : root.chatBridge.turnRunning
                                    expanded: cardExpanded || (running && root.activityExpanded)
                                    onToggleRequested: cardExpanded = !cardExpanded
                                }
                            }
                            Component {
                                id: userComponent
                                VrUserMessage {
                                    content: messageItem.displayContent
                                    messageKey: messageItem.messageKey
                                    onLayoutChanging: {
                                        if (!messageList.hasAnchor)
                                            messageList.preserveReader()
                                    }
                                    onCopyRequested: root.chatBridge.copyMessage(messageItem.index)
                                    onAnchorRequested: messageList.anchorMessage(messageItem)
                                    onTransitionFinished: messageList.finishAnchor(messageItem)
                                    onToggled: (expanded, heightDelta) => {
                                        messageList.compensateToggle(messageItem, heightDelta)
                                    }
                                }
                            }
                            Component {
                                id: assistantComponent
                                VrAssistantMessage {
                                    onLayoutChanging: {
                                        if (!messageList.hasAnchor)
                                            messageList.preserveReader()
                                    }
                                    markdown: messageItem.displayContent
                                    messageKey: messageItem.messageKey
                                    streaming: messageItem.isStreaming || (root.chatBridge.turnRunning && messageItem.index === messageList.count - 1 && !messageItem.messageKey)
                                    onCopyRequested: root.chatBridge.copyMessage(messageItem.index)
                                    onAnchorRequested: messageList.anchorMessage(messageItem)
                                    onTransitionFinished: messageList.finishAnchor(messageItem)
                                    onToggled: (expanded, heightDelta) => {
                                        messageList.compensateToggle(messageItem, heightDelta)
                                    }
                                }
                            }
                        }
                    }
                    Item {
                        id: messageBottomSpacer
                        width: parent.width
                        height: composerCard.normalHeight + root.expertStripHeight + (taskBar.visible ? taskBar.height + 24 : 48)
                    }
                }
                // Follow only while pinned; dragging/scrolling back detaches the reader.
                onMovementStarted: {
                    if (composerCard.composerInputItem && composerCard.composerInputItem.activeFocus) {
                        root.forceActiveFocus()
                    }
                    beginManualScroll()
                }
                onMovementEnded: followTail = atYEnd
                onContentYChanged: {
                    if (holdingReader && !followTail && contentY !== readerY)
                        Qt.callLater(restoreReader)
                    if (!hasAnchor && !followTail && (atYEnd || (contentHeight - height - contentY) <= 4)) {
                        followTail = true
                    }
                }
                onContentHeightChanged: {
                    if (followTail && !moving) tailTimer.restart()
                    else if (hasAnchor) applyAnchorAdjustment()
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
                    onFinished: {
                        if (messageList.atYEnd || (messageList.contentHeight - messageList.height - messageList.contentY) <= 4) {
                            messageList.followTail = true
                            messageList.positionViewAtEnd()
                        }
                    }
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
                        if (composerCard.composerInputItem && composerCard.composerInputItem.activeFocus) {
                            root.forceActiveFocus()
                        }
                        var start = !precise && wheelAnimation.running ? wheelAnimation.to : messageList.contentY
                        messageList.beginManualScroll()
                        messageList.cancelFlick()
                        var top = messageList.originY
                        var bottom = top + Math.max(0, messageList.contentHeight - messageList.height)
                        var destination = Math.max(top, Math.min(bottom, start - delta))
                        if (destination >= bottom - 4) {
                            messageList.followTail = true
                        }
                        if (precise) {
                            messageList.contentY = destination
                            if (destination < bottom - 4) messageList.followTail = false
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
                        if (pressed) {
                            if (composerCard.composerInputItem && composerCard.composerInputItem.activeFocus) {
                                root.forceActiveFocus()
                            }
                            messageList.beginManualScroll()
                        } else {
                            messageList.followTail = messageList.atYEnd
                        }
                    }
                }
            }


            Column {
                id: landing
                objectName: "chatLanding"
                visible: messageList.count === 0
                anchors.horizontalCenter: parent.horizontalCenter
                y: composerCard.y - root.usagePanelHeight - height - 24
                width: Math.min(parent.width - 48, 720)
                spacing: 8
                RowLayout {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(implicitWidth, parent.width)
                    spacing: 6
                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: landingProjectButton.projectLabel.length
                            ? "Como posso ajudar no projeto" : "Como posso ajudar no"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(22)
                        wrapMode: Text.WordWrap
                    }
                    VrButton {
                        id: landingProjectButton
                        objectName: "landingProjectButton"
                        Layout.maximumWidth: landing.width * 0.55
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: implicitWidth
                        implicitWidth: contentItem.implicitWidth
                        implicitHeight: contentItem.implicitHeight
                        padding: 0
                        leftPadding: 0
                        rightPadding: 0
                        variant: "ghost"
                        showFocusRing: false
                        property string projectLabel: root.chatBridge.currentProjectIndex > 0
                            && root.chatBridge.currentProjectIndex < root.chatBridge.projectItems.length
                            ? root.chatBridge.projectItems[root.chatBridge.currentProjectIndex].label : ""
                        // O clique que fecha o menu via CloseOnPressOutside chega ao botão
                        // depois do fechamento; sem este debounce o onClicked reabriria
                        // o menu e o segundo clique nunca fecharia.
                        property double menuClosedAt: 0
                        property bool menuJustToggleClosed: false
                        text: projectLabel.length ? "Como posso ajudar no projeto " + projectLabel + "?"
                            : "Como posso ajudar no seu projeto?"
                        Accessible.name: text
                        Accessible.description: "Selecionar a pasta do projeto"
                        contentItem: Text {
                            text: landingProjectButton.projectLabel.length ? "<u>"
                                + landingProjectButton.projectLabel.replace(/&/g, "&amp;")
                                    .replace(/</g, "&lt;").replace(/>/g, "&gt;") + "</u>?"
                                : "<u>seu projeto</u>?"
                            textFormat: Text.RichText
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(22)
                            horizontalAlignment: Text.AlignLeft
                            wrapMode: Text.WordWrap
                        }
                        onClicked: {
                            if (landingProjectMenu.opened) {
                                landingProjectMenu.close()
                                menuJustToggleClosed = true
                            } else if (menuJustToggleClosed) {
                                menuJustToggleClosed = false
                                landingProjectMenu.open()
                            } else if (Date.now() - menuClosedAt > 250) {
                                landingProjectMenu.open()
                            }
                        }
                        Menu {
                            id: landingProjectMenu
                            objectName: "landingProjectMenu"
                            onClosed: landingProjectButton.menuClosedAt = Date.now()
                            x: 0
                            y: parent.height + 6
                            width: Math.min(260, Overlay.overlay.width - 16)
                            margins: 8
                            padding: 5
                            background: Rectangle {
                                radius: 12
                                color: Theme.palette.chatSidebar
                                border.color: Theme.palette.chatBorder
                                border.width: 1
                            }
                            Instantiator {
                                model: root.filteredProjects("")
                                delegate: ProjectMenuEntry {
                                    required property var modelData
                                    text: modelData.label
                                    subtitle: ""
                                    iconPath: modelData.icon
                                    iconKind: modelData.iconKind
                                    iconEmoji: modelData.iconEmoji
                                    iconColor: modelData.iconColor
                                    iconText: modelData.iconText
                                    isAll: String(modelData.path || "").length === 0
                                    onTriggered: root.chatBridge.setProject(Number(modelData.sourceIndex))
                                }
                                onObjectAdded: (index, object) => landingProjectMenu.insertItem(index, object)
                                onObjectRemoved: (index, object) => landingProjectMenu.removeItem(object)
                            }
                            MenuSeparator { }
                            ProjectMenuEntry {
                                objectName: "landingNewProject"
                                text: "New project"
                                subtitle: ""
                                iconPath: ""
                                iconKind: "folderPlus"
                                iconEmoji: ""
                                iconColor: ""
                                isAll: false
                                onTriggered: {
                                    root.addProjectView = "sources"
                                    addProjectSearch.clear()
                                    addProjectPopup.open()
                                }
                            }
                        }
                    }
                }
                Text {
                    objectName: "landingSupportingText"
                    width: parent.width
                    text: root.greetingPrompt()
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }
            }

            VrResearchResume {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: composerCard.top
                anchors.bottomMargin: 10
                z: 20
                research: root.chatBridge.resumableResearch || ({})
                onResumeRequested: function(grantBudget) { root.chatBridge.resumeResearch(grantBudget) }
            }

            VrTaskBar {
                id: taskBar
                visible: root.chatBridge.taskPlanVisible
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: composerCard.top
                anchors.bottomMargin: -1
                width: Math.max(0, composerCard.width - 44)
                maximumListHeight: Math.min(384, root.height * 0.4)
                z: approvalDialog.opened ? 10 : 20
                steps: root.chatBridge.taskSteps
                progress: root.chatBridge.taskProgress
                running: root.chatBridge.turnRunning
                expanded: root.taskBarExpanded && !approvalDialog.opened
                onToggleRequested: {
                    if (approvalDialog.opened)
                        return
                    root.taskBarExpanded = !root.taskBarExpanded
                }
            }

            Rectangle {
                id: scrollToEndPill
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Rolar para o final"
                function jump() {
                    messageList.followTail = true
                    messageList.positionViewAtEnd()
                }
                Keys.onReturnPressed: scrollToEndPill.jump()
                Keys.onSpacePressed: scrollToEndPill.jump()
                objectName: "scrollToEndPill"
                property bool shouldShow: messageList.visible
                    && messageList.count > 0
                    && !messageList.followTail
                    && (messageList.contentHeight - messageList.height - messageList.contentY > 4)
                visible: opacity > 0.001
                opacity: shouldShow ? 1.0 : 0.0
                scale: shouldShow ? 1.0 : 0.88
                Behavior on opacity {
                    enabled: !root.frontendBridge.reduceMotion
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
                Behavior on scale {
                    enabled: !root.frontendBridge.reduceMotion
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: composerCard.top
                anchors.bottomMargin: taskBar.visible ? taskBar.height + 16 : 10
                z: 25
                radius: 13
                width: pillRow.implicitWidth + 22
                height: 26
                color: pillHover.hovered ? Theme.palette.chatControl : Theme.palette.chatComposer
                border.width: 1
                border.color: Theme.palette.chatBorder

                Row {
                    id: pillRow
                    anchors.centerIn: parent
                    spacing: 6
                    VrLineIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 12
                        height: 12
                        kind: "chevronDown"
                        foreground: Theme.palette.mutedText
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Rolar para o final"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                    }
                }

                HoverHandler { id: pillHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    cursorShape: Qt.PointingHandCursor
                    onTapped: scrollToEndPill.jump()
                }
            }

            VrChatComposer { id: composerCard; page: root }

            Item {
                id: expertProfileStrip
                objectName: "expertProfileStrip"
                z: 20
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
                                    font.pixelSize: Theme.fontSizeCaption
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

            // Bottom bar beneath compact composer containing ONLY the marked fields: Model & Permission selectors
            Item {
                id: compactBottomBar
                objectName: "compactBottomBar"
                visible: opacity > 0.001
                anchors.horizontalCenter: composerCard.horizontalCenter
                anchors.top: composerCard.bottom
                anchors.topMargin: 4
                width: composerCard.width
                height: 30
                z: 15
                opacity: composerCard.isCompact && root.expertReveal <= 0.001 && messageList.count > 0 ? 1.0 : 0.0
                scale: composerCard.isCompact ? 1.0 : 0.94
                Behavior on opacity {
                    enabled: !root.frontendBridge.reduceMotion
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
                Behavior on scale {
                    enabled: !root.frontendBridge.reduceMotion
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }

                RowLayout {
                    id: compactButtonsRow
                    anchors.centerIn: parent
                    spacing: 6

                    VrModelPicker {
                        id: compactModelPicker
                        objectName: "compactModelPicker"
                        compact: true
                        model: root.chatBridge.modelItems
                        currentIndex: root.chatBridge.modelIndex
                        loading: root.chatBridge.modelCatalogLoading
                        enabled: !root.chatBridge.turnRunning
                        popupAbove: true
                        onActivated: index => root.chatBridge.setModel(index)
                        onFavoriteToggled: index => root.chatBridge.toggleModelFavorite(index)
                    }

                    VrPermissionPicker {
                        id: compactPermissionPicker
                        objectName: "compactPermissionPicker"
                        compact: true
                        model: root.chatBridge.approvalItems
                        currentIndex: root.chatBridge.approvalIndex
                        onActivated: index => root.chatBridge.setApproval(index)
                    }
                }
            }

            // One continuous gradient stroke: no overlapping dashes or seam at the loop.
            Rectangle {
                id: ultraGlowOuter
                visible: root.chatBridge.vrMode === "ultra"
                anchors.centerIn: composerCard
                width: composerCard.width + 6
                height: composerCard.height + 6
                radius: composerCard.radius + 3
                color: "transparent"
                border.width: 3
                border.color: Qt.alpha(Theme.palette.accessibleOrange, 0.12)
            }
            Canvas {
                id: ultraArc
                objectName: "chatUltraBorder"
                visible: root.chatBridge.vrMode === "ultra"
                anchors.centerIn: composerCard
                width: composerCard.width + 8
                height: composerCard.height + 8
                property real sweep: 0
                property real strokeWidth: root.chatBridge.turnRunning ? 2 : 1.6
                onStrokeWidthChanged: requestPaint()
                onSweepChanged: requestPaint()
                onVisibleChanged: requestPaint()
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()

                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    // Leave room for antialiasing outside the rounded composer edge.
                    var inset = 3.5
                    var left = inset, top = inset
                    var right = width - inset, bottom = height - inset
                    var r = Math.min(composerCard.radius + 0.5, (bottom - top) / 2)
                    var angle = sweep * Math.PI * 2
                    var dx = Math.cos(angle) * width / 2
                    var dy = Math.sin(angle) * height / 2
                    var gradient = ctx.createLinearGradient(width / 2 - dx, height / 2 - dy,
                                                            width / 2 + dx, height / 2 + dy)
                    gradient.addColorStop(0, "#F04424")
                    gradient.addColorStop(0.35, "#F57616")
                    gradient.addColorStop(0.7, "#EFB825")
                    gradient.addColorStop(1, "#F7D85C")
                    ctx.beginPath()
                    ctx.moveTo(left + r, top)
                    ctx.lineTo(right - r, top)
                    ctx.arcTo(right, top, right, top + r, r)
                    ctx.lineTo(right, bottom - r)
                    ctx.arcTo(right, bottom, right - r, bottom, r)
                    ctx.lineTo(left + r, bottom)
                    ctx.arcTo(left, bottom, left, bottom - r, r)
                    ctx.lineTo(left, top + r)
                    ctx.arcTo(left, top, left + r, top, r)
                    ctx.closePath()
                    ctx.strokeStyle = gradient
                    ctx.lineWidth = strokeWidth
                    ctx.stroke()
                }
                NumberAnimation on sweep {
                    running: ultraArc.visible && root.visible && (!root.frontendBridge || !root.frontendBridge.reduceMotion)
                    loops: Animation.Infinite
                    from: 0
                    to: 1
                    duration: root.chatBridge.turnRunning ? 3600 : 6000
                    easing.type: Easing.Linear
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
                projectIconKind: root.projectSettingsIconKind
                projectIconEmoji: root.projectSettingsIconEmoji
                projectIconColor: root.projectSettingsIconColor
                projectIconText: root.projectSettingsIconText
                threadCount: root.chatBridge.conversationCount
                onCloseRequested: root.projectSettingsVisible = false
                onSaveRequested: name => {
                    if (root.chatBridge.renameProject(root.projectSettingsIndex, name))
                        root.projectSettingsName = name
                }
                onIconRequested: root.chatBridge.chooseProjectIcon(root.projectSettingsIndex)
                onIconCustomized: (kind, color, emoji, text) => {
                    if (root.chatBridge.applyProjectIcon(root.projectSettingsIndex, kind, color, emoji, text)) {
                        root.projectSettingsIconKind = kind
                        root.projectSettingsIconColor = color
                        root.projectSettingsIconEmoji = emoji
                        root.projectSettingsIconText = text
                    }
                }
                onIconCleared: {
                    if (root.chatBridge.clearProjectIcon(root.projectSettingsIndex)) {
                        root.projectSettingsIconPath = ""
                        root.projectSettingsIconKind = ""
                        root.projectSettingsIconEmoji = ""
                        root.projectSettingsIconColor = ""
                        root.projectSettingsIconText = ""
                    }
                }
                onOpenFolderRequested: root.chatBridge.openProjectFolder(root.projectSettingsIndex)
                onCopyPathRequested: root.chatBridge.copyProjectPath(root.projectSettingsIndex)
                onRemoveRequested: {
                    if (root.chatBridge.removeProject(root.projectSettingsIndex))
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
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 1
                color: Theme.palette.chatBorder
                visible: root.width < 1000
            }
            transform: Translate {
                x: root.surfaceVisible ? 0 : Theme.motionDistance
                Behavior on x {
                    enabled: !root.frontendBridge.reduceMotion
                    NumberAnimation { duration: Theme.motionDuration; easing.type: Easing.OutCubic }
                }
            }
            Behavior on opacity {
                enabled: !root.frontendBridge.reduceMotion
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
                                    scale: !root.frontendBridge.reduceMotion && down ? 0.97 : 1
                                    onClicked: root.surfaceIndex = modelData.page

                                    Behavior on scale {
                                        enabled: !root.frontendBridge.reduceMotion
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
                                            font.pixelSize: Theme.fontSizeCompact
                                            font.weight: Font.DemiBold
                                        }
                                        VrLineIcon {
                                            Layout.preferredWidth: 14
                                            Layout.preferredHeight: 14
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
                                            enabled: !root.frontendBridge.reduceMotion
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
                                id: surfaceChoice
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
                                        kind: surfaceChoice.modelData.kind
                                        foreground: Theme.palette.mutedText
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: surfaceChoice.modelData.title
                                        color: Theme.palette.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSize(12)
                                    }
                                    Text {
                                        text: surfaceChoice.modelData.title.charAt(0)
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeMicro
                                    }
                                }
                                HoverHandler { id: surfaceChoiceHover }
                                TapHandler {
                                    onTapped: {
                                        root.openSurface(surfaceChoice.modelData.page)
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
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; Layout.preferredHeight: 1; color: Theme.palette.chatDivider }
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
                                    font.pixelSize: Theme.fontSizeCaption
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
                                        + root.frontendBridge.projectPath + ">"
                                    color: Theme.palette.text
                                    font.family: "Cascadia Mono"
                                    font.pixelSize: Theme.fontSize(12)
                                }
                                TextField {
                                    id: terminalCommandInput
                                    objectName: "terminalCommandInput"
                                    Layout.fillWidth: true
                                    readOnly: root.studioBridge.terminalRunning
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
                                        root.studioBridge.runTerminalCommand(text)
                                        clear()
                                    }
                                }
                                VrButton {
                                    objectName: "terminalStopButton"
                                    visible: root.studioBridge.terminalRunning
                                    enabled: root.studioBridge.terminalRunning
                                    text: "Parar"
                                    variant: "danger"
                                    implicitHeight: 30
                                    onClicked: root.studioBridge.stopTerminalCommand()
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
                                text: root.studioBridge.terminalOutput
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
                            onAccepted: root.surfaceFiles = root.chatBridge.fileSuggestions(text)
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
                                height: root.fileTreeItemVisible(fileTreeRow.modelData) ? 30 : 0
                                visible: height > 0
                                radius: 6
                                color: root.surfaceFilePath === fileTreeRow.modelData.path
                                    ? Theme.palette.selection
                                    : fileTreeHover.hovered ? Theme.palette.chatControl : "transparent"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 6 + Math.min(8, Number(fileTreeRow.modelData.depth || 0)) * 14
                                    anchors.rightMargin: 6
                                    spacing: 5
                                    VrLineIcon {
                                        visible: fileTreeRow.modelData.isDirectory === true
                                        Layout.preferredWidth: 12
                                        Layout.preferredHeight: 12
                                        kind: root.expandedFileFolders[fileTreeRow.modelData.label]
                                            ? "chevronDown" : "chevronRight"
                                        foreground: Theme.palette.mutedText
                                    }
                                    Item {
                                        visible: fileTreeRow.modelData.isDirectory !== true
                                        Layout.preferredWidth: 11
                                        Layout.preferredHeight: 11
                                    }
                                    VrLineIcon {
                                        Layout.preferredWidth: 15
                                        Layout.preferredHeight: 15
                                        kind: fileTreeRow.modelData.isDirectory === true ? "folder" : "files"
                                        foreground: fileTreeRow.modelData.isDirectory === true
                                            ? Theme.palette.brandOrange : Theme.palette.mutedText
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: fileTreeRow.modelData.name || fileTreeRow.modelData.label
                                        color: Theme.palette.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeCaption
                                        elide: Text.ElideMiddle
                                    }
                                }
                                HoverHandler { id: fileTreeHover }
                                TapHandler {
                                    onTapped: {
                                        if (fileTreeRow.modelData.isDirectory === true) {
                                            root.toggleFileFolder(fileTreeRow.modelData.label)
                                            return
                                        }
                                        root.surfaceFilePath = fileTreeRow.modelData.path
                                        root.surfaceFilePreview = root.chatBridge.readFilePreview(fileTreeRow.modelData.path)
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
                            Text { Layout.fillWidth: true; text: root.surfaceFilePath || "Selecione um arquivo para visualizar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; elide: Text.ElideMiddle }
                            VrButton { text: "Abrir"; enabled: root.surfaceFilePath.length > 0; onClicked: root.studioBridge.openLocalPath(root.surfaceFilePath) }
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
                                font.pixelSize: Theme.monospaceFontSize(12)
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
                            onAccepted: root.contextItems = root.chatBridge.contextSuggestions(text)
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
                        id: contextChoice
                                required property var modelData
                                width: ListView.view.width
                                height: 72
                                radius: 8
                                color: contextHover.hovered ? Theme.palette.chatControl : "transparent"
                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 3
                                    Text { width: parent.width; text: contextChoice.modelData.title + " · " + contextChoice.modelData.source; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold; elide: Text.ElideRight }
                                    Text { width: parent.width; text: contextChoice.modelData.excerpt; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption; lineHeight: Theme.denseLineHeight; maximumLineCount: 2; elide: Text.ElideRight; wrapMode: Text.WordWrap }
                                }
                                HoverHandler { id: contextHover }
                                TapHandler { onTapped: root.insertReference(contextChoice.modelData.reference) }
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
                            text: root.chatBridge.agentItems.length > 0
                                ? "Agentes · " + root.chatBridge.agentItems.length
                                : "Nenhum agente nesta conversa. As tarefas delegadas aparecerão aqui."
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            lineHeight: Theme.bodyLineHeight
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
                            model: root.chatBridge.agentItems
                            delegate: Rectangle {
                        id: agentChoice
                                required property int index
                                required property var modelData
                                width: agentList.width
                                height: 58
                                radius: 8
                                color: root.selectedAgentIndex === agentChoice.index ? Theme.palette.selection
                                    : agentHover.hovered ? Theme.palette.chatControl : "transparent"
                                border.width: root.selectedAgentIndex === agentChoice.index ? 1 : 0
                                border.color: Theme.palette.chatBorder
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    Text {
                                        text: agentChoice.modelData.status === "concluído" ? "✓"
                                            : agentChoice.modelData.status === "falhou" ? "!"
                                            : agentChoice.modelData.status === "executando" ? "●" : "○"
                                        color: agentChoice.modelData.status === "concluído" ? Theme.palette.success
                                            : agentChoice.modelData.status === "falhou" ? Theme.palette.danger
                                            : agentChoice.modelData.status === "executando" ? Theme.palette.brandOrange
                                            : Theme.palette.mutedText
                                        font.pixelSize: Theme.fontSize(14)
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text { Layout.fillWidth: true; text: agentChoice.modelData.label; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold; elide: Text.ElideRight }
                                        Text { Layout.fillWidth: true; text: agentChoice.modelData.model + " · " + agentChoice.modelData.effort + " · " + agentChoice.modelData.statusLabel; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro; elide: Text.ElideRight }
                                    }
                                }
                                HoverHandler { id: agentHover }
                                TapHandler { onTapped: root.selectedAgentIndex = agentChoice.index }
                            }
                        }
                        Rectangle { Layout.fillWidth: true; implicitHeight: 1; Layout.preferredHeight: 1; color: Theme.palette.chatDivider }
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

    Timer { id: searchDelay; interval: 180; onTriggered: root.chatBridge.setSearch(conversationSearch.text) }
    Timer { id: composerAssistDelay; interval: 120; onTriggered: root.updateComposerSuggestions() }
    Timer { id: fileSearchDelay; interval: 160; onTriggered: root.surfaceFiles = root.chatBridge.fileSuggestions(fileSearch.text) }
    Timer { id: contextSearchDelay; interval: 200; onTriggered: root.contextItems = root.chatBridge.contextSuggestions(contextSearch.text) }
    Timer { id: copyFeedbackTimer; interval: 1300; onTriggered: root.copyFeedbackVisible = false }

    Connections {
        target: root.chatBridge
        function onFileSuggestionsChanged() {
            root.surfaceFiles = root.chatBridge.fileSuggestions(fileSearch.text)
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
            currentIndex: root.composerAssistIndex
            highlightMoveDuration: 0
            delegate: Rectangle {
                id: assistItem
                required property int index
                required property var modelData
                width: assistList.width
                height: 44
                radius: 7
                color: (assistItem.index === root.composerAssistIndex || assistHover.hovered) ? Theme.palette.chatControl : "transparent"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 9
                    anchors.rightMargin: 9
                    Text {
                        Layout.preferredWidth: 140
                        text: assistItem.modelData.label
                        color: assistItem.modelData.action === "skill" ? Theme.palette.brandOrange : Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: assistItem.modelData.description || ""
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeCaption
                        elide: Text.ElideRight
                    }
                }
                HoverHandler {
                    id: assistHover
                    onHoveredChanged: if (hovered) root.composerAssistIndex = assistItem.index
                }
                TapHandler { onTapped: root.chooseComposerSuggestion(assistItem.modelData) }
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
            Math.max(264, 163 + Math.min(6,
                root.filteredProjects(newChatProjectSearch.text).length) * 56))
        padding: 0
        modal: true
        dim: true
        Overlay.modal: Rectangle { color: Qt.alpha(Theme.palette.background, 0.85) }
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
                font.pixelSize: Theme.fontSizeCaption
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
                        ? (Theme.palette.appearance === "light" ? Theme.palette.selection : "#24384c")
                        : (newProjectHover.hovered ? Theme.palette.chatControl : "transparent")

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 9
                        spacing: 9
                        VrProjectIcon {
                            Layout.preferredWidth: 30
                            Layout.preferredHeight: 30
                            boxSize: 30
                            iconSize: 17
                            projectLabel: String(newProjectItem.modelData.label || "")
                            iconPath: String(newProjectItem.modelData.icon || "")
                            iconKind: String(newProjectItem.modelData.iconKind || "")
                            iconEmoji: String(newProjectItem.modelData.iconEmoji || "")
                            iconColor: String(newProjectItem.modelData.iconColor || "")
                            iconText: String(newProjectItem.modelData.iconText || "")
                            isAll: String(newProjectItem.modelData.path || "").length === 0
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
                                font.pixelSize: Theme.fontSizeCaption
                                horizontalAlignment: Text.AlignLeft
                                elide: Text.ElideMiddle
                            }
                        }
                        Text {
                            text: newProjectItem.modelData.shortcut
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeCaption
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
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                Layout.topMargin: 4
                Layout.bottomMargin: 2
                radius: 7
                color: newChatNewHover.hovered ? Theme.palette.chatControl : "transparent"
                border.width: 1
                border.color: Theme.palette.chatBorder
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 9
                    VrLineIcon {
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 16
                        kind: "folderPlus"
                        foreground: Theme.palette.brandOrange
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "New project"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.DemiBold
                    }
                }
                HoverHandler { id: newChatNewHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    onTapped: {
                        newChatProjectPopup.close()
                        root.addProjectView = "sources"
                        addProjectSearch.clear()
                        addProjectPopup.open()
                    }
                }
                Accessible.role: Accessible.Button
                Accessible.name: "New project"
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 38
                radius: 12
                color: Theme.palette.chatComposer
                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 12
                    color: Theme.palette.chatComposer
                }
                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: Theme.palette.chatDivider
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 6
                    KbdHint { label: "↑" }
                    KbdHint { label: "↓" }
                    Text { text: "Navegar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro; font.weight: Theme.weightMedium; Layout.rightMargin: 6 }
                    KbdHint { label: "Enter" }
                    Text { text: "Selecionar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro; font.weight: Theme.weightMedium; Layout.rightMargin: 6 }
                    KbdHint { label: "Backspace" }
                    Text { text: "Voltar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro; font.weight: Theme.weightMedium }
                    Item { Layout.fillWidth: true }
                    KbdHint { label: "Esc" }
                    Text { text: "Fechar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro; font.weight: Theme.weightMedium }
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
        Overlay.modal: Rectangle { color: Qt.alpha(Theme.palette.background, 0.85) }
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
                font.pixelSize: Theme.fontSizeCaption
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
                    color: sourceHover.hovered && sourceRow.modelData.enabled
                        ? Theme.palette.chatControl : "transparent"
                    opacity: sourceRow.modelData.enabled ? 1.0 : 0.72
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 9
                        anchors.rightMargin: 9
                        spacing: 9
                        VrLineIcon {
                            Layout.preferredWidth: 18
                            Layout.preferredHeight: 18
                            kind: sourceRow.modelData.icon
                            foreground: sourceRow.modelData.enabled
                                ? Theme.palette.text : Theme.palette.mutedText
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                Layout.fillWidth: true
                                text: sourceRow.modelData.title
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(13)
                                font.weight: sourceRow.modelData.key === "local" ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: sourceRow.modelData.description
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeCaption
                                elide: Text.ElideRight
                            }
                        }
                        Rectangle {
                            visible: sourceRow.modelData.badge.length > 0
                            Layout.preferredWidth: badgeText.implicitWidth + 14
                            Layout.preferredHeight: 24
                            radius: 5
                            color: Theme.palette.chatComposer
                            border.width: 1
                            border.color: Theme.palette.chatBorder
                            Text {
                                id: badgeText
                                anchors.centerIn: parent
                                text: sourceRow.modelData.badge
                                color: Theme.palette.warning
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeMicro
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
                radius: 18
                color: Theme.palette.chatComposer
                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 18
                    color: Theme.palette.chatComposer
                }
                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: Theme.palette.chatDivider
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 6
                    KbdHint { label: "↑" }
                    KbdHint { label: "↓" }
                    Text { text: "Navegar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro; font.weight: Theme.weightMedium; Layout.rightMargin: 6 }
                    KbdHint { label: "Enter" }
                    Text { text: "Selecionar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro; font.weight: Theme.weightMedium }
                    Item { Layout.fillWidth: true }
                    KbdHint { label: "Esc" }
                    Text { text: "Fechar"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeMicro; font.weight: Theme.weightMedium }
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
                    { kind: "pin", label: root.chatBridge.selectedPinned ? "Desafixar conversa" : "Fixar conversa", action: "pin" },
                    { kind: "archive", label: "Arquivar conversa", action: "archive" },
                    { kind: "trash", label: "Excluir conversa", action: "delete" }
                ]
                delegate: Rectangle {
                        id: conversationAction
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    radius: 7
                    color: menuHover.hovered ? Theme.palette.chatControl : "transparent"
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 9; anchors.rightMargin: 9; spacing: 8
                        VrLineIcon { Layout.preferredWidth: 16; Layout.preferredHeight: 16; kind: conversationAction.modelData.kind; foreground: conversationAction.modelData.action === "delete" ? Theme.palette.danger : Theme.palette.mutedText }
                        Text { Layout.fillWidth: true; text: conversationAction.modelData.label; color: conversationAction.modelData.action === "delete" ? Theme.palette.danger : Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    }
                    HoverHandler { id: menuHover }
                    TapHandler {
                        onTapped: {
                            var targetId = String(root.conversationMenuConversationId || "")
                            conversationContextMenu.close()
                            if (conversationAction.modelData.action === "pin") {
                                if (targetId) root.chatBridge.togglePinnedConversation(targetId)
                                else root.chatBridge.togglePinnedCurrent()
                            } else if (conversationAction.modelData.action === "archive") {
                                if (targetId) root.chatBridge.archiveConversation(targetId)
                                else root.chatBridge.archiveCurrentConversation()
                            } else conversationDeleteDialog.open()
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

    VrUsageLimitsDialog {
        id: usageLimitsDialog
        chatBridge: root.chatBridge
        targetItem: composerCard
    }

    Connections {
        target: root.chatBridge
        function onShowUsageLimitsRequested() {
            usageLimitsDialog.open()
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
        onOpened: root.chatBridge.refreshExtensions()
        contentItem: ColumnLayout {
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; text: "Selecione recursos para a próxima mensagem. Alterar tools em um chat iniciado cria uma ramificação segura."; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); wrapMode: Text.WordWrap }
                VrButton { text: root.chatBridge.extensionsLoading ? "Carregando…" : "Atualizar"; enabled: !root.chatBridge.extensionsLoading; onClicked: root.chatBridge.refreshExtensions() }
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
                    model: root.chatBridge.extensionItems
                    delegate: VrCheckBox {
                        required property int index
                        required property var modelData
                        width: ListView.view.width
                        text: (modelData.kind === "skill" ? "Skill · " : "MCP · ") + modelData.name
                        checked: modelData.selected
                        ToolTip.visible: hovered
                        ToolTip.text: modelData.description
                        onToggled: root.chatBridge.toggleExtension(index, checked)
                    }
                    VrEmptyState {
                        anchors.centerIn: parent
                        visible: parent.count === 0 && !root.chatBridge.extensionsLoading
                        title: "Nenhum recurso encontrado"
                        description: "O catálogo depende do provedor e do projeto selecionados."
                        actionText: "Tentar novamente"
                        onAction: root.chatBridge.refreshExtensions()
                    }
                }
            }
        }
        background: Rectangle { color: Theme.palette.surface; border.width: 1; border.color: Theme.palette.border; radius: Theme.radiusPopup }
    }
    Dialog {
        id: approvalDialog
        objectName: "chatApprovalDialog"
        anchors.centerIn: parent
        width: Math.min(510, parent.width - 32)
        modal: true
        closePolicy: Popup.NoAutoClose
        title: "Aprovação necessária"
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: 12
            Text { Layout.fillWidth: true; text: String(root.approvalPayload.reason || root.approvalPayload.description || "O agente solicitou permissão para continuar."); color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize; lineHeight: Theme.bodyLineHeight; wrapMode: Text.WordWrap }
            RowLayout {
                Layout.fillWidth: true
                VrButton { text: "Negar"; onClicked: { approvalDialog.close(); root.chatBridge.decideApproval(false, false) } }
                Item { Layout.fillWidth: true }
                VrButton { objectName: "chatApproveOnce"; text: "Aprovar uma vez"; onClicked: { approvalDialog.close(); root.chatBridge.decideApproval(true, false) } }
                VrButton { text: "Aprovar nesta sessão"; variant: "primary"; onClicked: { approvalDialog.close(); root.chatBridge.decideApproval(true, true) } }
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
        if (root.chatBridge.turnRunning || index >= root.chatBridge.modelItems.length) return
        root.chatBridge.setModel(index)
    }

    function activateConversation(conversationId) {
        root.chatBridge.saveCurrentDraft(composerInput.text)
        root.chatBridge.selectConversationId(conversationId)
        messageList.followTail = true
        tailTimer.restart()
    }

    function openConversationMenu(conversationId, positionX, positionY) {
        root.conversationMenuConversationId = String(conversationId || "")
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
            root.surfaceFiles = root.chatBridge.fileSuggestions(fileSearch.text)
        }
        if (page === 5 && root.selectedAgentIndex < 0 && root.chatBridge.agentItems.length)
            root.selectedAgentIndex = 0
    }

    Dialog {
        id: conversationDeleteDialog
        objectName: "conversationDeleteDialog"
        anchors.centerIn: parent
        width: Math.min(440, parent.width - 32)
        modal: true
        dim: true
        padding: 0
        topPadding: 0
        bottomPadding: 0
        leftPadding: 0
        rightPadding: 0
        header: null
        footer: null
        standardButtons: Dialog.NoButton
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.chatBorder
            radius: 14
        }
        contentItem: ColumnLayout {
            spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 20
                Layout.leftMargin: 20
                Layout.rightMargin: 16
                Layout.bottomMargin: 14
                spacing: 14
                Rectangle {
                    width: 40
                    height: 40
                    radius: 20
                    color: Qt.alpha(Theme.palette.danger, 0.12)
                    Layout.alignment: Qt.AlignTop
                    VrLineIcon {
                        anchors.centerIn: parent
                        width: 18
                        height: 18
                        kind: "trash"
                        foreground: Theme.palette.danger
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 4
                    Text {
                        text: "Excluir esta conversa?"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(15)
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "A conversa será removida da lista e enviada para a lixeira."
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        wrapMode: Text.WordWrap
                    }
                }
                VrIconButton {
                    Layout.alignment: Qt.AlignTop
                    iconKind: "close"
                    iconSize: 10
                    implicitWidth: 26
                    implicitHeight: 26
                    foreground: Theme.palette.mutedText
                    onClicked: conversationDeleteDialog.close()
                }
            }
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Theme.palette.chatBorder
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                Layout.bottomMargin: 14
                Layout.leftMargin: 20
                Layout.rightMargin: 20
                spacing: 10
                Item { Layout.fillWidth: true }
                VrButton {
                    text: "Cancelar"
                    onClicked: conversationDeleteDialog.close()
                }
                VrButton {
                    objectName: "confirmDeleteButton"
                    text: root.chatBridge.conversationDeleteRunning ? "Excluindo…" : "Excluir"
                    variant: "danger"
                    enabled: !root.chatBridge.conversationDeleteRunning
                    onClicked: {
                        var targetId = String(root.conversationMenuConversationId || "")
                        var wasSelected = !targetId || targetId === root.chatBridge.selectedConversationId
                        conversationDeleteDialog.close()
                        if (targetId)
                            root.chatBridge.trashConversation(targetId)
                        else
                            root.chatBridge.trashCurrentConversation()
                        if (wasSelected)
                            composerInput.clear()
                    }
                }
            }
        }
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
        var source = root.chatBridge.projectItems || []
        var needle = String(query || "").trim().toLowerCase()
        if (needle.normalize) needle = needle.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
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
            if (needle.length) {
                var hay = (label + " " + path).toLowerCase()
                if (hay.normalize) hay = hay.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                if (hay.indexOf(needle) < 0) continue
            }
            result.push({
                label: label,
                path: path,
                icon: String(item.icon || ""),
                iconKind: String(item.iconKind || item.icon_kind || ""),
                iconEmoji: String(item.iconEmoji || item.icon_emoji || ""),
                iconColor: String(item.iconColor || item.icon_color || ""),
                iconText: String(item.iconText || item.icon_text || ""),
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
        root.chatBridge.setProject(Number(item.sourceIndex))
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
        var source = root.chatBridge.projectItems || []
        if (index <= 0 || index >= source.length) return
        root.chatBridge.setProject(index)
        source = root.chatBridge.projectItems || []
        var item = source[index]
        if (!item || !String(item.path || "").length) return
        root.surfaceVisible = false
        root.projectSettingsIndex = index
        root.projectSettingsPath = String(item.path || "")
        root.projectSettingsName = String(item.label || "")
        root.projectSettingsIconPath = String(item.icon || "")
        root.projectSettingsIconKind = String(item.iconKind || item.icon_kind || "")
        root.projectSettingsIconEmoji = String(item.iconEmoji || item.icon_emoji || "")
        root.projectSettingsIconColor = String(item.iconColor || item.icon_color || "")
        root.projectSettingsIconText = String(item.iconText || item.icon_text || "")
        root.projectSettingsVisible = true
        Qt.callLater(function() {
            projectSettingsPage.forceActiveFocus()
            projectSettingsPage.resetView()
        })
    }

    function syncOpenProjectSettings() {
        if (!root.projectSettingsVisible || !root.projectSettingsPath.length) return
        var source = root.chatBridge.projectItems || []
        for (var index = 1; index < source.length; ++index) {
            if (String(source[index].path || "") !== root.projectSettingsPath) continue
            root.projectSettingsIndex = index
            root.projectSettingsName = String(source[index].label || "")
            root.projectSettingsIconPath = String(source[index].icon || "")
            root.projectSettingsIconKind = String(source[index].iconKind || source[index].icon_kind || "")
            root.projectSettingsIconEmoji = String(source[index].iconEmoji || source[index].icon_emoji || "")
            root.projectSettingsIconColor = String(source[index].iconColor || source[index].icon_color || "")
            root.projectSettingsIconText = String(source[index].iconText || source[index].icon_text || "")
            return
        }
        root.projectSettingsVisible = false
    }

    function projectSettingsOriginalName() {
        var source = root.chatBridge.projectItems || []
        if (root.projectSettingsIndex <= 0 || root.projectSettingsIndex >= source.length)
            return ""
        return String(source[root.projectSettingsIndex].label || "")
    }

    function currentModelLabel() {
        var models = root.chatBridge.modelItems || []
        var modelIndex = Number(root.chatBridge.modelIndex)
        var modelLabel = modelIndex >= 0 && modelIndex < models.length
            ? String(models[modelIndex].label || models[modelIndex].value || "Modelo atual")
            : "Modelo atual"
        var efforts = root.chatBridge.effortItems || []
        var effortIndex = Number(root.chatBridge.effortIndex)
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
        root.chatBridge.beginProjectFolderBrowse()
    }

    function activateProjectSource(sourceKey) {
        if (String(sourceKey) !== "local") return false
        root.openLocalFolderBrowser()
        return true
    }

    function submitMessage() {
        if ((!composerInput.text.trim().length && !root.chatBridge.attachments.length) || root.chatBridge.turnRunning) return
        var value = composerInput.text
        messageList.followTail = true
        composerInput.clear()
        composerAssistPopup.close()
        root.chatBridge.sendMessage(value)
    }

    function handleComposerTab(event) {
        if (composerAssistPopup.visible && composerSuggestions.length > 0) {
            event.accepted = true
            var idx = Math.max(0, Math.min(composerAssistIndex, composerSuggestions.length - 1))
            chooseComposerSuggestion(composerSuggestions[idx])
            return true
        }
        return false
    }

    function handleComposerUp(event) {
        if (composerAssistPopup.visible && composerSuggestions.length > 0) {
            event.accepted = true
            composerAssistIndex = (composerAssistIndex - 1 + composerSuggestions.length) % composerSuggestions.length
            assistList.currentIndex = composerAssistIndex
            assistList.positionViewAtIndex(composerAssistIndex, ListView.Contain)
            return true
        }
        return false
    }

    function handleComposerDown(event) {
        if (composerAssistPopup.visible && composerSuggestions.length > 0) {
            event.accepted = true
            composerAssistIndex = (composerAssistIndex + 1) % composerSuggestions.length
            assistList.currentIndex = composerAssistIndex
            assistList.positionViewAtIndex(composerAssistIndex, ListView.Contain)
            return true
        }
        return false
    }

    function handleComposerEscape(event) {
        if (composerAssistPopup.visible) {
            event.accepted = true
            composerAssistPopup.close()
            return true
        }
        return false
    }

    function handleComposerEnter(event) {
        if (event.modifiers & Qt.ShiftModifier) {
            event.accepted = false
            return
        }
        if (composerAssistPopup.visible && composerSuggestions.length > 0) {
            event.accepted = true
            var idx = Math.max(0, Math.min(composerAssistIndex, composerSuggestions.length - 1))
            chooseComposerSuggestion(composerSuggestions[idx])
            return
        }
        event.accepted = true
        root.submitMessage()
    }

    function agentDetailText() {
        if (root.selectedAgentIndex < 0 || root.selectedAgentIndex >= root.chatBridge.agentItems.length)
            return "Selecione um agente para ver tarefa, roteamento e saída."
        var item = root.chatBridge.agentItems[root.selectedAgentIndex]
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
            ...(root.chatBridge.supportsReasoning ? [{label:"/effort",description:"Definir esforço de raciocínio",action:"effort"}] : []),
            {label:"/permissions",description:"Definir perfil de aprovação",action:"permissions"},
            {label:"/skills",description:"Gerenciar skills disponíveis",action:"skills"},
            {label:"/usage-limits",description:"Ver limites de uso e quotas do provedor",action:"usage-limits"},
            {label:"/tools",description:"Ver tools e MCP",action:"tools"},
            {label:"/vr",description:"Alternar Off / VR / VR Ultra",action:"vr"},
            {label:"/pesquisa",description:"Pesquisa multiagente: /pesquisa <pergunta>",action:"pesquisa"}
        ]
        if (trimmed.length && trimmed[0] === "/" && trimmed.indexOf(" ") < 0) {
            var needle = trimmed.substring(1).toLowerCase()
            var matches = commands.filter(function(item) {
                return item.label.substring(1).toLowerCase().indexOf(needle) >= 0
            })
            if (root.chatBridge.showSkillsInSlashMenu) {
                var skills = root.chatBridge.skillSuggestions(needle)
                for (var i = 0; i < skills.length; i++) {
                    var s = skills[i]
                    matches.push({
                        label: "/" + s.name,
                        description: s.shortDescription || s.description || "Skill",
                        action: "skill",
                        skill: s,
                        start: 0
                    })
                }
            }
            composerSuggestions = matches
            if (composerSuggestions.length) {
                root.composerAssistIndex = 0
                composerAssistPopup.open()
            } else {
                composerAssistPopup.close()
            }
            return
        }
        var dollar = value.lastIndexOf("$")
        if (dollar >= 0) {
            var querySkill = value.substring(dollar + 1)
            if (querySkill.indexOf(" ") < 0 && querySkill.indexOf("\n") < 0) {
                var skillsFound = root.chatBridge.skillSuggestions(querySkill)
                composerSuggestions = skillsFound.map(function(item) {
                    return {
                        label: "$" + item.name,
                        description: item.shortDescription || item.description || "Skill",
                        action: "skill",
                        skill: item,
                        start: dollar
                    }
                })
                if (composerSuggestions.length) {
                    root.composerAssistIndex = 0
                    composerAssistPopup.open()
                } else {
                    composerAssistPopup.close()
                }
                return
            }
        }
        var at = value.lastIndexOf("@")
        if (at >= 0) {
            var query = value.substring(at + 1)
            if (query.indexOf(" ") < 0 && query.indexOf("\n") < 0) {
                var files = root.chatBridge.fileSuggestions(query)
                composerSuggestions = files.map(function(item) {
                    return {label:item.label,description:"Arquivo do projeto",action:"reference",path:item.path,start:at}
                })
                if (composerSuggestions.length) {
                    root.composerAssistIndex = 0
                    composerAssistPopup.open()
                } else {
                    composerAssistPopup.close()
                }
                return
            }
        }
        composerSuggestions = []
        composerAssistPopup.close()
    }

    function chooseComposerSuggestion(item) {
        composerAssistPopup.close()
        if (item.action === "usage-limits") {
            composerInput.clear()
            root.chatBridge.openUsageLimits()
            composerInput.forceActiveFocus()
        }
        else if (item.action === "skill") {
            root.chatBridge.addActiveSkill(item.skill)
            var start = item.start !== undefined ? item.start : 0
            var before = composerInput.text.substring(0, start)
            composerInput.text = before.trim() ? before.trim() + " " : ""
            composerInput.cursorPosition = composerInput.length
            composerInput.forceActiveFocus()
        }
        else if (item.action === "model") modelSelector.openPicker()
        else if (item.action === "effort" && root.chatBridge.supportsReasoning) effortSelector.openPicker()
        else if (item.action === "permissions") approvalSelector.openPicker()
        else if (item.action === "vr") root.chatBridge.cycleVrMode()
        else if (item.action === "pesquisa") {
            composerInput.text = "/pesquisa "
            composerInput.cursorPosition = composerInput.length
            composerInput.forceActiveFocus()
        }
        else if (item.action === "skills" || item.action === "tools") extensionsDialog.open()
        else if (item.action === "reference") {
            var before = composerInput.text.substring(0, item.start)
            composerInput.text = before + "@\"" + item.path + "\" "
            composerInput.cursorPosition = composerInput.length
            composerInput.forceActiveFocus()
        }
    }

    function insertReference(reference) {
        var separator = composerInput.text.length && !composerInput.text.endsWith(" ") ? " " : ""
        composerInput.text += separator + reference + " "
        composerInput.cursorPosition = composerInput.length
        composerInput.forceActiveFocus()
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
        if (!root.chatBridge.seniorProfileEnabled) return false
        if (key === "senior") return root.chatBridge.vrResponseMode === "auto"
        return root.chatBridge.vrResponseMode === key
    }

    function activateExpertProfile(key) {
        if (root.expertProfileSelected(key)) {
            root.chatBridge.setSeniorProfileEnabled(false)
            return
        }
        root.chatBridge.setSeniorProfileEnabled(true)
        root.chatBridge.setVrResponseMode(key === "senior" ? "auto" : key)
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
