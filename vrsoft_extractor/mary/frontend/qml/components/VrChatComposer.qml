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
        anchors.bottomMargin: Theme.scaledGeometry(8)
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
    // T3 Code resting semantics: the composer reads the live edge from the
    // list's followTail intent, not from transient geometry. While the page
    // streams, followTail stays armed and the composer stays expanded; a turn
    // in progress never rests it by itself. Scrolling away rests it, and
    // reaching the end restores it without stopping the turn.
    readonly property bool isAtBottom: {
        var list = composerCard.page ? composerCard.page.messageListHandle : null
        if (!list || list.count === 0) return true
        if (list.contentHeight <= list.height) return true
        return list.followTail
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
        && !isAtBottom
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
        if (hasImageAttachments) h += Theme.scaledGeometry(72)
        if (hasFileAttachments) h += Theme.scaledGeometry(34)
        return h
    }
    // Distância do topo do cartão até o campo de texto, sem ler AnchorLines
    // (attachmentList.bottom.y é indefinido e zerava a margem, sobrepondo o texto aos thumbnails).
    // Thumbnails: top 16 + altura 64 = 80; faixa de arquivos: 16 (sem thumbs)
    // ou 8 + 30 de altura, com 6 de respiro antes do texto.
    readonly property real composerTopMargin: {
        if (composerCard.isCompact) return Theme.scaledGeometry(6)
        if (hasImageAttachments && hasFileAttachments) return Theme.scaledGeometry(124)
        if (hasImageAttachments) return Theme.scaledGeometry(86)
        if (hasFileAttachments) return Theme.scaledGeometry(52)
        return Theme.spaceLg
    }
    readonly property real skillsAreaHeight: hasSkills ? Theme.scaledGeometry(34) : 0
    readonly property real chipAreaHeight: attachmentsAreaHeight + skillsAreaHeight

    // T3 Code editor: `min-h-17.5` (70px) expanded, `min-h-8` (32px) resting.
    readonly property real normalScrollHeight: Math.min(composerCard.page.chatMainHandle.height * 0.28, Math.max(Theme.scaledGeometry(70),
        composerInput.contentHeight + composerInput.topPadding + composerInput.bottomPadding))
    // Expandido: card único com a linha de controles integrada na base.
    // pt-4 (16) + editor + pb-2 (8) + controles + pb-4 (16).
    readonly property real normalHeight: normalScrollHeight + (chipAreaHeight > 0 ? chipAreaHeight + Theme.spaceSm : 0) + Theme.compactControlHeight + Theme.scaledGeometry(40)
    // Compacto: faixa do campo + bandeja de controles separada logo abaixo.
    readonly property real compactSurfaceHeight: Theme.scaledGeometry(46)
    readonly property real compactHeight: compactSurfaceHeight + Theme.compactControlHeight - Theme.spaceXs
    // T3 Code context strip: `--chat-composer-drawer-inset: 1.375rem` and
    // `rounded-b-2xl` for the inset bottom band.
    readonly property real compactInset: Theme.scaledGeometry(22)
    readonly property int compactStripRadius: Theme.radiusLg
    // Retraído, o campo reserva a largura de anexo + enviar para o texto
    // nunca correr sob as ações primárias compactas.
    readonly property real compactActionsReserve: composerCard.isCompact
        ? Theme.scaledGeometry(82)
        : Math.max(Theme.scaledGeometry(86), composerSurface.width - vrModeButton.x + Theme.spaceSm)

    objectName: "chatComposerCard"
    z: 20
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: composerCard.page.messageListHandle.count > 0 ? parent.bottom : undefined
    anchors.bottomMargin: composerCard.page.messageListHandle.count > 0 ? (composerCard.page.expertStripHeight + 36) : 0
    y: composerCard.page.messageListHandle.count > 0 ? 0
        : Math.max(composerCard.page.chatHeaderHandle.height + composerCard.page.landingHandle.height + composerCard.page.usagePanelHeight + 32,
            (parent.height - height) / 2)
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
        // T3 Code lifts the resting composer on any composer interaction,
        // including a click while a turn is still streaming.
        enabled: composerCard.isCompact
        onTapped: {
            composerInput.forceActiveFocus()
        }
    }

    // Backdrop retraído: uma única silhueta contínua no formato do T3 Code —
    // card arredondado com a faixa de controles encaixada na base — para que
    // o campo e a bandeja compartilhem borda e nenhum conteúdo da timeline
    // apareça pelos cantos transparentes entre os dois.
    Canvas {
        id: composerRestingSurface
        objectName: "chatComposerRestingSurface"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: composerCard.compactHeight
        visible: composerCard.isCompact
        z: 0
        antialiasing: true
        readonly property int topRadius: composerCard.compactInset
        readonly property int stripInset: composerCard.compactInset
        readonly property int stripTop: composerCard.compactSurfaceHeight
        readonly property int stripRadius: composerCard.compactStripRadius
        readonly property color fillColor: Theme.palette.chatComposer
        readonly property color outlineColor: composerCard.page.composerDropActive
            ? (composerCard.vrActive ? Theme.vrAccent : Theme.palette.brandOrange)
            : (composerInput.activeFocus
                ? (Theme.palette.appearance === "light" ? Qt.alpha(Theme.palette.border, 0.85) : Qt.rgba(255, 255, 255, 0.20))
                : (Theme.palette.appearance === "light" ? Qt.alpha(Theme.palette.border, 0.6) : Qt.rgba(255, 255, 255, 0.08)))
        onFillColorChanged: requestPaint()
        onOutlineColorChanged: requestPaint()
        onTopRadiusChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onVisibleChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var w = width
            var h = height
            if (w <= 0 || h <= 0) return
            var strip = Math.max(0, Math.min(stripTop, h))
            var top = Math.max(0, Math.min(topRadius, w / 2, strip / 2))
            var inset = top
            var sr = Math.max(0, Math.min(stripRadius, h - strip, (w - inset * 2) / 2))

            // Fator de aproximação bezier cúbica para cantos arredondados (T3 Code shape parity)
            var kTop = top * 0.4477
            var kInset = inset * 0.4477
            var kSr = sr * 0.4477

            ctx.beginPath()
            ctx.moveTo(0, top)
            // Canto superior esquerdo
            ctx.bezierCurveTo(0, kTop, kTop, 0, top, 0)
            // Borda superior
            ctx.lineTo(w - top, 0)
            // Canto superior direito
            ctx.bezierCurveTo(w - kTop, 0, w, kTop, w, top)
            // Borda lateral direita do card superior
            ctx.lineTo(w, strip - inset)
            // Transição suave para o recuo da bandeja de controles (bezier cúbica T3 Code)
            ctx.bezierCurveTo(w, strip - kInset, w - kInset, strip, w - inset, strip)
            // Borda lateral direita da bandeja de controles
            ctx.lineTo(w - inset, h - sr)
            // Canto inferior direito da bandeja
            if (sr > 0)
                ctx.bezierCurveTo(w - inset, h - kSr, w - inset - kSr, h, w - inset - sr, h)
            // Borda inferior da bandeja
            ctx.lineTo(inset + sr, h)
            // Canto inferior esquerdo da bandeja
            if (sr > 0)
                ctx.bezierCurveTo(inset + kSr, h, inset, h - kSr, inset, h - sr)
            // Borda lateral esquerda da bandeja de controles
            ctx.lineTo(inset, strip)
            // Transição suave saindo da bandeja para o card superior (bezier cúbica T3 Code)
            ctx.bezierCurveTo(inset * 0.4477, strip, 0, strip - kInset, 0, strip - inset)
            // Borda lateral esquerda do card superior
            ctx.lineTo(0, top)
            ctx.closePath()

            ctx.fillStyle = fillColor
            ctx.fill()

            // Linha sutil da costura entre o card superior e a bandeja
            ctx.beginPath()
            ctx.moveTo(inset, strip)
            ctx.lineTo(w - inset, strip)
            ctx.strokeStyle = Theme.palette.appearance === "light"
                ? Qt.alpha(Theme.palette.border, 0.4)
                : Qt.rgba(255, 255, 255, 0.05)
            ctx.lineWidth = 1
            ctx.stroke()

            // Destaque superior interno sutil no tema escuro (rim-light)
            if (Theme.palette.appearance !== "light") {
                ctx.beginPath()
                ctx.moveTo(top, 1)
                ctx.lineTo(w - top, 1)
                ctx.strokeStyle = Qt.rgba(255, 255, 255, 0.04)
                ctx.lineWidth = 1
                ctx.stroke()
            }

            // Contorno externo contínuo
            ctx.strokeStyle = outlineColor
            ctx.lineWidth = 1
            ctx.stroke()
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
        radius: Theme.composerRadius
        clip: true
        color: composerCard.isCompact ? "transparent" : Theme.palette.chatComposer
        border.width: composerCard.isCompact ? 0 : 1
        border.color: composerCard.page.composerDropActive
            ? (composerCard.vrActive ? Theme.vrAccent : Theme.palette.brandOrange)
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
            anchors.leftMargin: Theme.scaledGeometry(14)
            anchors.rightMargin: Theme.scaledGeometry(14)
            anchors.topMargin: Theme.spaceLg
            height: visible ? Theme.scaledGeometry(64) : 0
            orientation: ListView.Horizontal
            spacing: Theme.scaledGeometry(10)
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
                width: isImage ? Theme.scaledGeometry(64) : 0
                height: isImage ? Theme.scaledGeometry(64) : 0

                Rectangle {
                    id: imageThumbnailCard
                    objectName: "chatAttachmentThumbnail"
                    anchors.fill: parent
                    radius: Theme.scaledGeometry(8)
                    color: Theme.palette.chatControl
                    border.width: 1
                    border.color: Theme.palette.chatBorder
                    clip: true

                    Image {
                        id: thumbImage
                        anchors.fill: parent
                        // Non-image attachments get a chip instead; without this
                        // gate the decoder logs spurious format errors.
                        source: thumbDelegate.isImage ? thumbDelegate.imageSource : ""
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
                        radius: Theme.scaledGeometry(8)
                        visible: false
                    }

                    Rectangle {
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: Theme.scaledGeometry(3)
                        width: Theme.scaledGeometry(16)
                        height: Theme.scaledGeometry(16)
                        radius: Theme.scaledGeometry(8)
                        color: Qt.rgba(0, 0, 0, 0.65)
                        VrIconButton {
                            anchors.centerIn: parent
                            width: Theme.scaledGeometry(16)
                            height: Theme.scaledGeometry(16)
                            iconKind: "close"
                            iconSize: Theme.iconMicro
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
            anchors.leftMargin: Theme.scaledGeometry(14)
            anchors.rightMargin: Theme.scaledGeometry(14)
            anchors.topMargin: attachmentThumbnailsList.visible ? 8 : 10
            height: visible ? Theme.scaledGeometry(30) : 0
            orientation: ListView.Horizontal
            spacing: Theme.scaledGeometry(6)
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
                height: isImageChip ? 0 : Theme.scaledGeometry(26)
                radius: Theme.scaledGeometry(8)
                color: Theme.palette.chatControl
                border.width: 1
                border.color: Theme.palette.chatBorder
                Row {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.scaledGeometry(8)
                    anchors.rightMargin: Theme.scaledGeometry(4)
                    spacing: Theme.scaledGeometry(5)
                    VrLineIcon {
                        width: Theme.iconCompact
                        height: Theme.iconCompact
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
                        width: Theme.scaledGeometry(22)
                        height: Theme.scaledGeometry(22)
                        anchors.verticalCenter: parent.verticalCenter
                        iconKind: "close"
                        iconSize: Theme.iconMicro
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
            anchors.leftMargin: Theme.spaceLg
            anchors.rightMargin: composerCard.isCompact ? composerCard.compactActionsReserve : Theme.spaceLg
            anchors.top: parent.top
            anchors.topMargin: composerCard.composerTopMargin
            height: composerCard.isCompact ? Theme.scaledGeometry(34) : Math.min(composerCard.page.chatMainHandle.height * 0.28, Math.max(Theme.scaledGeometry(70),
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
            anchors.leftMargin: Theme.scaledGeometry(14)
            anchors.rightMargin: Theme.scaledGeometry(14)
            anchors.topMargin: 2
            height: visible ? Theme.scaledGeometry(30) : 0
            orientation: ListView.Horizontal
            spacing: Theme.scaledGeometry(6)
            clip: true
            model: composerCard.page.chatBridge.activeSkills
            delegate: Rectangle {
                id: skillChip
                required property int index
                required property var modelData
                width: Math.min(220, skillLabel.implicitWidth + 34)
                height: Theme.scaledGeometry(26)
                radius: Theme.scaledGeometry(8)
                color: Theme.palette.chatControl
                border.width: 1
                border.color: Theme.palette.chatBorder
                Row {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.scaledGeometry(8)
                    anchors.rightMargin: Theme.scaledGeometry(4)
                    spacing: Theme.scaledGeometry(4)
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
                        width: Theme.scaledGeometry(22)
                        height: Theme.scaledGeometry(22)
                        anchors.verticalCenter: parent.verticalCenter
                        iconKind: "close"
                        iconSize: Theme.iconMicro
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
            anchors.rightMargin: Theme.scaledGeometry(6)
            anchors.verticalCenter: sendButton.verticalCenter
            width: Theme.scaledGeometry(32)
            height: Theme.scaledGeometry(32)
            implicitWidth: Theme.scaledGeometry(32)
            implicitHeight: Theme.scaledGeometry(32)
            iconKind: "attachment"
            iconSize: Theme.iconMedium
            foreground: attachButton.hovered ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8")
            enabled: !composerCard.page.chatBridge.turnRunning
            Accessible.name: "Anexar arquivos"
            onClicked: composerCard.page.chatBridge.chooseAttachments()
        }

        VrIconButton {
            id: sendButton
            objectName: "chatSendButton"
            anchors.right: parent.right
            anchors.rightMargin: Theme.scaledGeometry(composerCard.isCompact ? 10 : 16)
            anchors.bottom: parent.bottom
            anchors.bottomMargin: composerCard.isCompact
                ? Math.round((composerCard.compactSurfaceHeight - height) / 2)
                : Theme.spaceLg
            width: Theme.scaledGeometry(32)
            height: Theme.scaledGeometry(32)
            implicitWidth: Theme.scaledGeometry(32)
            implicitHeight: Theme.scaledGeometry(32)
            round: true
            enabled: composerCard.page.chatBridge.turnRunning || composerInput.text.trim().length > 0 || composerCard.page.chatBridge.attachments.length > 0 || (composerCard.page.chatBridge.activeSkills && composerCard.page.chatBridge.activeSkills.length > 0)
            Accessible.name: composerCard.page.chatBridge.turnRunning ? "Interromper geração" : "Enviar mensagem"
            iconSource: Qt.resolvedUrl(composerCard.page.chatBridge.turnRunning
                ? "../../../assets/chat-stop.svg"
                : "../../../assets/chat-send.svg")
            foreground: "#FFFFFF"
            background: Rectangle {
                radius: Theme.scaledGeometry(16)
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
            visible: !composerCard.isCompact
            property string variant: composerCard.page.chatBridge.vrMode !== "off" ? "primary" : "ghost"
            implicitWidth: vrModeContent.implicitWidth + 14
            implicitHeight: Theme.scaledGeometry(28)
            leftPadding: Theme.scaledGeometry(6)
            rightPadding: Theme.scaledGeometry(6)
            hoverEnabled: true
            focusPolicy: Qt.StrongFocus
            anchors.right: attachButton.left
            anchors.rightMargin: Theme.spaceSm
            anchors.verticalCenter: attachButton.verticalCenter
            contentItem: Row {
                id: vrModeContent
                spacing: Theme.scaledGeometry(4)
                anchors.centerIn: parent
                Text {
                    text: composerCard.page.chatBridge.vrMode === "ultra" ? "VR Ultra" : "VR"
                    color: composerCard.page.chatBridge.vrMode !== "off"
                        ? Theme.vrAccent
                        : (vrModeButton.hovered ? (Theme.palette.headingText || "#FFFFFF") : (Theme.palette.subtleText || "#8f9ca8"))
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeControl
                    font.weight: composerCard.page.chatBridge.vrMode !== "off" ? Font.Medium : Font.Normal
                    renderType: Theme.textRenderType
                    verticalAlignment: Text.AlignVCenter
                }
            }
            background: Rectangle {
                radius: Theme.scaledGeometry(6)
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
        x: composerCard.isCompact ? composerCard.compactInset : Theme.spaceXs
        y: composerCard.isCompact
            ? composerCard.compactSurfaceHeight - Theme.spaceXs
            : composerCard.normalHeight - height - Theme.spaceLg
        width: composerCard.isCompact
            ? composerCard.width - 2 * composerCard.compactInset
            : Math.max(0, vrModeButton.x - 2 * Theme.spaceXs)
        height: Theme.compactControlHeight
        // Retraído, o fundo e o contorno pertencem à silhueta única do card.
        radius: composerCard.isCompact ? composerCard.compactStripRadius : 0
        color: "transparent"
        border.width: 0
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
                    Layout.preferredHeight: Theme.scaledGeometry(14)
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
                    Layout.preferredHeight: Theme.scaledGeometry(14)
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
            }
        }
    }
}
