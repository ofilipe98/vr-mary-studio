pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import "../theme"

Item {
    id: composerCard
    required property var page
    property string submissionError: ""
    Text {
        objectName: "chatSubmissionError"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.top
        anchors.bottomMargin: 8
        visible: composerCard.submissionError.length > 0
        text: composerCard.submissionError
        color: Theme.palette.danger
        font.pixelSize: Theme.fontSize(12)
        wrapMode: Text.Wrap
    }
    property alias approvalSelectorItem: approvalSelector
    property alias composerInputItem: composerInput
    property alias effortSelectorItem: effortSelector
    property alias modelSelectorItem: modelSelector
    // Compatibilidade: consumidores externos ainda leem radius/color do componente.
    readonly property alias color: composerSurface.color
    readonly property alias radius: composerSurface.radius
    readonly property bool isAtBottom: {
        var list = composerCard.page ? composerCard.page.messageListHandle : null
        if (!list || list.count === 0) return true
        if (list.contentHeight <= list.height) return true
        if (list.atYEnd) return true
        var dist = list.contentHeight - list.height - list.contentY
        return dist <= 4
    }
    readonly property bool isScrolledUp: {
        var list = composerCard.page ? composerCard.page.messageListHandle : null
        if (!list || list.count === 0) return false
        return !isAtBottom
    }
    readonly property bool hasComposerContent: (composerInput.text && composerInput.text.length > 0) || hasChips
    property bool isCompact: composerCard.page && composerCard.page.messageListHandle && composerCard.page.messageListHandle.count > 0
        && !composerInput.activeFocus
        && !hasComposerContent
        && (!isAtBottom || composerCard.page.chatBridge.turnRunning)
    readonly property bool hasChips: (composerCard.page.chatBridge.attachments.length > 0) || (composerCard.page.chatBridge.activeSkills && composerCard.page.chatBridge.activeSkills.length > 0)
    readonly property bool hasImageAttachments: {
        var list = composerCard.page.chatBridge.attachments || []
        for (var i = 0; i < list.length; ++i) {
            var item = list[i]
            var p = String((item && (item.path || item.name)) || "").toLowerCase()
            if (p.endsWith(".png") || p.endsWith(".jpg") || p.endsWith(".jpeg") ||
                p.endsWith(".webp") || p.endsWith(".gif") || p.endsWith(".bmp") ||
                p.endsWith(".svg") || p.endsWith(".ico")) return true
        }
        return false
    }
    readonly property bool hasFileAttachments: {
        var list = composerCard.page.chatBridge.attachments || []
        for (var i = 0; i < list.length; ++i) {
            var item = list[i]
            var p = String((item && (item.path || item.name)) || "").toLowerCase()
            if (!(p.endsWith(".png") || p.endsWith(".jpg") || p.endsWith(".jpeg") ||
                p.endsWith(".webp") || p.endsWith(".gif") || p.endsWith(".bmp") ||
                p.endsWith(".svg") || p.endsWith(".ico"))) return true
        }
        return false
    }
    readonly property int attachmentsCount: composerCard.page.chatBridge.attachments ? composerCard.page.chatBridge.attachments.length : 0
    readonly property bool hasSkills: composerCard.page.chatBridge.activeSkills && composerCard.page.chatBridge.activeSkills.length > 0
    readonly property real attachmentsAreaHeight: {
        var h = 0
        if (hasImageAttachments) h += 68
        if (hasFileAttachments) h += 34
        return h
    }
    // Distância do topo do cartão até o campo de texto, sem ler AnchorLines
    // (attachmentList.bottom.y é indefinido e zerava a margem, sobrepondo o texto aos thumbnails).
    // Thumbnails: top 12 + altura 60 = 72; faixa de arquivos: 10 (sem thumbs) ou 8 + 30 de altura.
    readonly property real composerTopMargin: {
        if (composerCard.isCompact) return 6
        if (hasImageAttachments && hasFileAttachments) return 116
        if (hasImageAttachments) return 78
        if (hasFileAttachments) return 46
        return 12
    }
    readonly property real skillsAreaHeight: hasSkills ? 34 : 0
    readonly property real chipAreaHeight: attachmentsAreaHeight + skillsAreaHeight

    readonly property real normalScrollHeight: Math.min(composerCard.page.chatMainHandle.height * 0.28, Math.max(54,
        composerInput.contentHeight + composerInput.topPadding + composerInput.bottomPadding))
    // Expandido: card único com a linha de controles integrada na base.
    readonly property real normalHeight: normalScrollHeight + (chipAreaHeight > 0 ? chipAreaHeight + 8 : 0) + Theme.compactControlHeight + 22
    // Compacto: faixa do campo + bandeja de controles separada logo abaixo.
    readonly property real compactSurfaceHeight: 46
    readonly property real compactHeight: compactSurfaceHeight + Theme.compactControlHeight - Theme.spaceXs

    objectName: "chatComposerCard"
    z: 20
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: composerCard.page.messageListHandle.count > 0 ? parent.bottom : undefined
    anchors.bottomMargin: composerCard.page.messageListHandle.count > 0 ? (composerCard.page.expertStripHeight + 36) : 0
    y: composerCard.page.messageListHandle.count > 0 ? 0
        : Math.max(composerCard.page.chatHeaderHandle.height + composerCard.page.landingHandle.height + composerCard.page.usagePanelHeight + 32,
            (parent.height + composerCard.page.chatHeaderHandle.height + composerCard.page.landingHandle.height + composerCard.page.usagePanelHeight + 24 - height - composerCard.page.expertStripHeight) / 2)
    width: Math.min(Theme.contentWidth, parent.width - (parent.width < 600 ? 28 : 48))
    height: isCompact ? compactHeight : normalHeight
    readonly property bool vrActive: Boolean(composerCard.page && composerCard.page.chatBridge && composerCard.page.chatBridge.vrMode !== "off")

    Behavior on height {
        enabled: !composerCard.page.frontendBridge.reduceMotion
        NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
    }
    Behavior on y {
        enabled: !composerCard.page.frontendBridge.reduceMotion && anchors.bottom === undefined
        NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
    }

    TapHandler {
        enabled: composerCard.isCompact && !composerCard.page.chatBridge.turnRunning
        onTapped: {
            composerInput.forceActiveFocus()
        }
    }

    // Card principal de digitação: fundo, borda, raio e recorte do composer.
    Rectangle {
        id: composerSurface
        objectName: "chatComposerSurface"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: composerCard.isCompact
            ? composerCard.compactSurfaceHeight
            : composerCard.normalHeight
        radius: 16
        clip: true
        color: Theme.palette.chatComposer
        border.width: 1
        border.color: composerCard.page.composerDropActive
            ? (composerCard.vrActive ? Theme.vrAccent : Theme.palette.brandOrange)
            : (composerCard.vrActive && !composerCard.isCompact)
                ? (composerInput.activeFocus ? Theme.vrAccent : Qt.alpha(Theme.vrAccent, 0.45))
                : (composerInput.activeFocus
                    ? (Theme.palette.appearance === "light" ? Qt.alpha(Theme.palette.border, 0.85) : Qt.rgba(255, 255, 255, 0.20))
                    : (Theme.palette.appearance === "light" ? Qt.alpha(Theme.palette.border, 0.6) : Qt.rgba(255, 255, 255, 0.08)))
        z: 1

        Behavior on border.color {
            enabled: !composerCard.page.frontendBridge.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }

        Behavior on height {
            enabled: !composerCard.page.frontendBridge.reduceMotion
            NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
        }

        DropArea {
            id: composerDropArea
            objectName: "chatComposerDropArea"
            anchors.fill: parent
            z: 100
            onEntered: function(drag) {
                composerCard.page.composerDropActive = drag.hasUrls
                drag.accepted = drag.hasUrls
            }
            onExited: composerCard.page.composerDropActive = false
            onDropped: function(drop) {
                composerCard.page.composerDropActive = false
                if (drop.hasUrls) {
                    composerCard.page.chatBridge.addDroppedAttachments(drop.urls)
                    drop.acceptProposedAction()
                }
            }
        }

        // Top thumbnail preview row for image attachments (matching Image 2)
        ListView {
            id: attachmentThumbnailsList
            objectName: "chatAttachmentThumbnailsList"
            visible: composerCard.hasImageAttachments && !composerCard.isCompact
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            anchors.topMargin: 12
            height: visible ? 60 : 0
            orientation: ListView.Horizontal
            spacing: 10
            clip: true
            model: composerCard.page.chatBridge.attachments
            delegate: Item {
                id: thumbDelegate
                required property int index
                required property var modelData
                readonly property bool isImage: {
                    var p = String((modelData && (modelData.path || modelData.name)) || "").toLowerCase()
                    return p.endsWith(".png") || p.endsWith(".jpg") || p.endsWith(".jpeg") ||
                           p.endsWith(".webp") || p.endsWith(".gif") || p.endsWith(".bmp") ||
                           p.endsWith(".svg") || p.endsWith(".ico")
                }
                readonly property string imageSource: {
                    var p = String((modelData && modelData.path) || "")
                    if (!p.length) return ""
                    if (p.startsWith("file:///")) return p
                    if (p.indexOf(":") === 1) return "file:///" + p.replace(/\\/g, "/")
                    return "file://" + p.replace(/\\/g, "/")
                }
                visible: isImage
                width: isImage ? 60 : 0
                height: isImage ? 60 : 0

                Rectangle {
                    id: imageThumbnailCard
                    objectName: "chatAttachmentThumbnail"
                    anchors.fill: parent
                    radius: 8
                    color: Theme.palette.chatControl
                    border.width: 1
                    border.color: Theme.palette.chatBorder
                    clip: true

                    Image {
                        id: thumbImage
                        anchors.fill: parent
                        source: thumbDelegate.imageSource
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: true
                        // Item.clip é retangular e não respeita o radius do card,
                        // por isso a imagem vazava com cantos quadrados.
                        layer.enabled: true
                        layer.effect: MultiEffect {
                            maskEnabled: true
                            maskSource: thumbMask
                        }
                    }

                    Rectangle {
                        id: thumbMask
                        anchors.fill: parent
                        radius: 8
                        visible: false
                    }

                    Rectangle {
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: 3
                        width: 16
                        height: 16
                        radius: 8
                        color: Qt.rgba(0, 0, 0, 0.65)
                        VrIconButton {
                            anchors.centerIn: parent
                            width: 16
                            height: 16
                            iconKind: "close"
                            iconSize: 8
                            foreground: "#FFFFFF"
                            onClicked: composerCard.page.chatBridge.removeAttachment(thumbDelegate.index)
                        }
                    }
                }
            }
        }

        // Attachment chips row (below thumbnails, above text input; only non-image files)
        ListView {
            id: attachmentList
            objectName: "chatAttachmentList"
            visible: composerCard.hasFileAttachments && !composerCard.isCompact
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: attachmentThumbnailsList.visible ? attachmentThumbnailsList.bottom : parent.top
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            anchors.topMargin: attachmentThumbnailsList.visible ? 8 : 10
            height: visible ? 30 : 0
            orientation: ListView.Horizontal
            spacing: 6
            clip: true
            model: composerCard.page.chatBridge.attachments
            delegate: Rectangle {
                id: attachmentChip
                required property int index
                required property var modelData
                readonly property bool isImageChip: {
                    var p = String((modelData && (modelData.path || modelData.name)) || "").toLowerCase()
                    return p.endsWith(".png") || p.endsWith(".jpg") || p.endsWith(".jpeg") ||
                           p.endsWith(".webp") || p.endsWith(".gif") || p.endsWith(".bmp") ||
                           p.endsWith(".svg") || p.endsWith(".ico")
                }
                visible: !isImageChip
                width: isImageChip ? 0 : Math.min(220, chipText.implicitWidth + 38)
                height: isImageChip ? 0 : 26
                radius: 8
                color: Theme.palette.chatControl
                border.width: 1
                border.color: Theme.palette.chatBorder
                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 4
                    spacing: 5
                    VrLineIcon {
                        width: 14
                        height: 14
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "file"
                        foreground: Theme.palette.brandOrange
                    }
                    Text {
                        id: chipText
                        width: parent.parent.width - 36
                        anchors.verticalCenter: parent.verticalCenter
                        text: attachmentChip.modelData.name || attachmentChip.modelData.path || ""
                        elide: Text.ElideMiddle
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                    }
                    VrIconButton {
                        width: 22
                        height: 22
                        anchors.verticalCenter: parent.verticalCenter
                        iconKind: "close"
                        iconSize: 12
                        foreground: Theme.palette.mutedText
                        onClicked: composerCard.page.chatBridge.removeAttachment(attachmentChip.index)
                    }
                }
            }
        }

        // ScrollView containing text input (placed below attachments)
        ScrollView {
            id: composerScroll
            objectName: "chatComposerScroll"
            property alias text: composerInput.text
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 16
            anchors.rightMargin: composerCard.isCompact ? 86 : 16
            anchors.top: parent.top
            anchors.topMargin: composerCard.composerTopMargin
            height: composerCard.isCompact ? 34 : Math.min(composerCard.page.chatMainHandle.height * 0.28, Math.max(54,
                contentHeight + topPadding + bottomPadding))
            clip: true

            Behavior on height {
                enabled: !composerCard.page.frontendBridge.reduceMotion
                NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
            }
            Behavior on anchors.topMargin {
                enabled: !composerCard.page.frontendBridge.reduceMotion
                NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
            }
            Behavior on anchors.rightMargin {
                enabled: !composerCard.page.frontendBridge.reduceMotion
                NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
            }
            ScrollBar.vertical: VrScrollBar {
                id: composerScrollBar
                objectName: "chatComposerScrollBar"
                parent: composerScroll
                x: composerScroll.mirrored ? 0 : composerScroll.width - width
                y: composerScroll.topPadding
                height: composerScroll.availableHeight
            }

            VrTextArea {
                id: composerInput
                objectName: "chatComposerInput"
                font.family: Theme.promptFontFamily
                font.pixelSize: Theme.promptFontSize(14)
                renderType: Theme.textRenderType
                leftPadding: 0
                rightPadding: 0
                topPadding: 2
                bottomPadding: 2
                placeholderText: composerCard.page.chatMainHandle.width < 600 ? "Pergunte algo…" : "Pergunte algo…  @ arquivos · $ skills · / comandos"
                placeholderTextColor: Theme.palette.subtleText || "#7d8b99"
                readOnly: composerCard.page.chatBridge.turnRunning
                verticalAlignment: composerCard.isCompact ? TextEdit.AlignVCenter : TextEdit.AlignTop
                background: Item { }
                onTextChanged: composerCard.page.composerAssistDelayHandle.restart()

                Keys.priority: Keys.BeforeItem
                Keys.onPressed: event => {
                    if (event.matches(StandardKey.Paste) && composerCard.page.chatBridge.pasteClipboardAttachment())
                        event.accepted = true
                }
                Keys.onTabPressed: event => composerCard.page.handleComposerTab(event)
                Keys.onBacktabPressed: event => composerCard.page.handleComposerTab(event)
                Keys.onUpPressed: event => composerCard.page.handleComposerUp(event)
                Keys.onDownPressed: event => composerCard.page.handleComposerDown(event)
                Keys.onEscapePressed: event => composerCard.page.handleComposerEscape(event)
                Keys.onReturnPressed: event => composerCard.page.handleComposerEnter(event)
                Keys.onEnterPressed: event => composerCard.page.handleComposerEnter(event)
            }
        }

        ListView {
            id: skillChipList
            objectName: "chatSkillChipList"
            visible: composerCard.hasSkills && !composerCard.isCompact
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: composerScroll.bottom
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            anchors.topMargin: 2
            height: visible ? 30 : 0
            orientation: ListView.Horizontal
            spacing: 6
            clip: true
            model: composerCard.page.chatBridge.activeSkills
            delegate: Rectangle {
                id: skillChip
                required property int index
                required property var modelData
                width: Math.min(220, skillLabel.implicitWidth + 34)
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
                        id: skillLabel
                        width: parent.parent.width - 30
                        anchors.verticalCenter: parent.verticalCenter
                        text: "$" + (skillChip.modelData.name || skillChip.modelData.label || "")
                        elide: Text.ElideMiddle
                        color: Theme.palette.brandOrange
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.weight: Font.DemiBold
                    }
                    VrIconButton {
                        width: 22
                        height: 22
                        anchors.verticalCenter: parent.verticalCenter
                        iconKind: "close"
                        iconSize: 12
                        foreground: Theme.palette.mutedText
                        onClicked: composerCard.page.chatBridge.removeActiveSkill(skillChip.index)
                    }
                }
            }
        }

        VrIconButton {
            id: attachButton
            objectName: "chatAttachButton"
            anchors.right: sendButton.left
            anchors.rightMargin: 8
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 8
            width: 32
            height: 32
            implicitWidth: 32
            implicitHeight: 32
            iconKind: "attachment"
            iconSize: 18
            foreground: attachButton.hovered ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8")
            enabled: !composerCard.page.chatBridge.turnRunning
            Accessible.name: "Anexar arquivos"
            onClicked: composerCard.page.chatBridge.chooseAttachments()
        }

        VrIconButton {
            id: sendButton
            objectName: "chatSendButton"
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 8
            width: 32
            height: 32
            implicitWidth: 32
            implicitHeight: 32
            round: true
            enabled: composerCard.page.chatBridge.turnRunning || composerInput.text.trim().length > 0 || composerCard.page.chatBridge.attachments.length > 0 || (composerCard.page.chatBridge.activeSkills && composerCard.page.chatBridge.activeSkills.length > 0)
            Accessible.name: composerCard.page.chatBridge.turnRunning ? "Interromper geração" : "Enviar mensagem"
            iconSource: Qt.resolvedUrl(composerCard.page.chatBridge.turnRunning
                ? "../../../assets/chat-stop.svg"
                : "../../../assets/chat-send.svg")
            foreground: "#FFFFFF"
            background: Rectangle {
                radius: 16
                color: composerCard.page.chatBridge.turnRunning
                    ? (parent.down
                        ? Qt.darker(Theme.palette.danger, 1.18)
                        : parent.hovered
                            ? Qt.darker(Theme.palette.danger, 1.08)
                            : Theme.palette.danger)
                    : (parent.down
                        ? Theme.palette.brandOrange
                        : parent.hovered
                            ? Qt.lighter(Theme.palette.accessibleOrange, 1.12)
                            : Theme.palette.accessibleOrange)
                border.width: parent.activeFocus ? 2 : 0
                border.color: Theme.palette.focus
            }
            onClicked: composerCard.page.chatBridge.turnRunning ? composerCard.page.chatBridge.stopTurn() : composerCard.page.submitMessage()
        }

        Button {
            id: vrModeButton
            objectName: "vrModeButton"
            property string variant: composerCard.page.chatBridge.vrMode !== "off" ? "primary" : "ghost"
            implicitWidth: vrModeContent.implicitWidth + 14
            implicitHeight: 28
            leftPadding: 6
            rightPadding: 6
            hoverEnabled: true
            focusPolicy: Qt.StrongFocus
            anchors.right: attachButton.left
            anchors.rightMargin: Theme.spaceSm
            anchors.verticalCenter: attachButton.verticalCenter
            contentItem: Row {
                id: vrModeContent
                spacing: 4
                anchors.centerIn: parent
                Text {
                    text: composerCard.page.chatBridge.vrMode === "ultra" ? "VR Ultra" : "VR"
                    color: composerCard.page.chatBridge.vrMode !== "off"
                        ? Theme.vrAccent
                        : (vrModeButton.hovered ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8"))
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12.5)
                    font.weight: composerCard.page.chatBridge.vrMode !== "off" ? Font.Medium : Font.Normal
                    renderType: Theme.textRenderType
                    verticalAlignment: Text.AlignVCenter
                }
            }
            background: Rectangle {
                radius: 6
                color: vrModeButton.down || vrModeButton.hovered
                    ? Qt.rgba(255, 255, 255, 0.07) : "transparent"
            }
            onClicked: composerCard.page.chatBridge.cycleVrMode()
        }
    }

    // Linha de controles: integrada à base do card no modo expandido; no modo
    // compacto vira uma bandeja própria, mais estreita, encaixada logo abaixo.
    Rectangle {
        id: composerControlsBox
        objectName: "chatComposerControlsBox"
        // Retraído: bandeja mais estreita, ancorada nas laterais do composer e
        // sobreposta ao campo logo acima, de modo que só os cantos inferiores
        // arredondados apareçam — sem uma segunda curva solta no meio.
        readonly property real compactInset: Theme.spaceLg
        x: composerCard.isCompact ? compactInset : Theme.spaceXs
        y: composerCard.isCompact
            ? composerCard.compactSurfaceHeight - Theme.spaceXs
            : composerCard.normalHeight - height - 8
        width: composerCard.isCompact
            ? composerCard.width - 2 * compactInset
            : Math.max(0, vrModeButton.x - 2 * Theme.spaceXs)
        height: Theme.compactControlHeight
        radius: composerCard.isCompact ? Theme.radiusControl : 0
        color: composerCard.isCompact ? Theme.palette.chatComposer : "transparent"
        border.width: composerCard.isCompact ? 1 : 0
        border.color: Theme.palette.appearance === "light"
            ? Qt.alpha(Theme.palette.border, 0.6)
            : Qt.rgba(255, 255, 255, 0.08)
        z: composerCard.isCompact ? 0 : 2
        clip: composerCard.isCompact

        Behavior on y {
            enabled: !composerCard.page.frontendBridge.reduceMotion
            NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
        }

        Flickable {
            id: composerControls
            anchors.fill: parent
            anchors.leftMargin: Theme.spaceMd
            anchors.rightMargin: Theme.spaceMd
            contentWidth: controlsRow.width
            contentHeight: height
            clip: true
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            RowLayout {
                id: controlsRow
                width: Math.max(implicitWidth, composerControls.width)
                height: Theme.compactControlHeight
                spacing: Theme.spaceSm

                VrModelPicker {
                    id: modelSelector
                    objectName: "chatModelPicker"
                    model: composerCard.page.chatBridge.modelItems
                    currentIndex: composerCard.page.chatBridge.modelIndex
                    loading: composerCard.page.chatBridge.modelCatalogLoading
                    enabled: !composerCard.page.chatBridge.turnRunning
                    onActivated: index => composerCard.page.chatBridge.setModel(index)
                    onFavoriteToggled: index => composerCard.page.chatBridge.toggleModelFavorite(index)
                }

                Rectangle {
                    visible: effortSelector.visible
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 14
                    Layout.alignment: Qt.AlignVCenter
                    color: Theme.palette.chatDivider
                    opacity: 0.7
                }

                VrReasoningPicker {
                    id: effortSelector
                    objectName: "chatReasoningPicker"
                    visible: composerCard.page.chatBridge.supportsReasoning
                    effortModel: composerCard.page.chatBridge.effortItems
                    tierModel: composerCard.page.chatBridge.serviceTierItems
                    currentEffortIndex: composerCard.page.chatBridge.effortIndex
                    currentTierIndex: composerCard.page.chatBridge.serviceTierIndex
                    onEffortActivated: index => composerCard.page.chatBridge.setEffort(index)
                    onTierActivated: index => composerCard.page.chatBridge.setServiceTier(index)
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 14
                    Layout.alignment: Qt.AlignVCenter
                    color: Theme.palette.chatDivider
                    opacity: 0.7
                }

                VrPermissionPicker {
                    id: approvalSelector
                    objectName: "chatPermissionPicker"
                    model: composerCard.page.chatBridge.approvalItems
                    currentIndex: composerCard.page.chatBridge.approvalIndex
                    onActivated: index => composerCard.page.chatBridge.setApproval(index)
                }

                Item { Layout.fillWidth: true }

                VrContextButton {
                    id: contextUsageButton
                    objectName: "contextUsageButton"
                    implicitWidth: 28
                    implicitHeight: 28
                    visible: composerCard.page.chatBridge.hasContextWindow
                    fraction: composerCard.page.chatBridge.contextUsageFraction
                    usageLabel: composerCard.page.chatBridge.contextUsageCompactLabel
                    totalLabel: composerCard.page.chatBridge.totalProcessedLabel
                    note: composerCard.page.chatBridge.contextUsageNote
                }
            }
        }
    }
}
