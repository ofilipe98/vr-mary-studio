pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: composerCard
    required property var page
    property alias approvalSelectorItem: approvalSelector
    property alias composerInputItem: composerInput
    property alias effortSelectorItem: effortSelector
    property alias modelSelectorItem: modelSelector
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
    readonly property int attachmentsCount: composerCard.page.chatBridge.attachments ? composerCard.page.chatBridge.attachments.length : 0
    readonly property bool hasSkills: composerCard.page.chatBridge.activeSkills && composerCard.page.chatBridge.activeSkills.length > 0
    readonly property real attachmentsAreaHeight: {
        var h = 0
        if (hasImageAttachments) h += 68
        if (attachmentsCount > 0) h += 34
        return h
    }
    readonly property real skillsAreaHeight: hasSkills ? 34 : 0
    readonly property real chipAreaHeight: attachmentsAreaHeight + skillsAreaHeight

    objectName: "chatComposerCard"
    anchors.horizontalCenter: parent.horizontalCenter
    y: composerCard.page.messageListHandle.count > 0 ? parent.height - height - composerCard.page.expertStripHeight - 24
        : Math.max(composerCard.page.chatHeaderHandle.height + composerCard.page.landingHandle.height + composerCard.page.usagePanelHeight + 32,
            (parent.height + composerCard.page.chatHeaderHandle.height + composerCard.page.landingHandle.height + composerCard.page.usagePanelHeight + 24 - height - composerCard.page.expertStripHeight) / 2)
    width: Math.min(Theme.contentWidth, parent.width - (parent.width < 600 ? 28 : 48))
    height: composerScroll.height + (chipAreaHeight > 0 ? chipAreaHeight + 8 : 0) + 54
    radius: Theme.composerRadius
    color: Qt.alpha(Theme.palette.chatComposer, Theme.glassOpacity)
    border.width: 1
    border.color: composerCard.page.composerDropActive
        ? Theme.palette.brandOrange
        : composerInput.activeFocus
            ? Theme.palette.focus : Theme.palette.chatBorder

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
        visible: composerCard.hasImageAttachments
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
                p = p.replace(/\\/g, "/")
                return p.startsWith("/") ? ("file://" + p) : ("file:///" + p)
            }
            visible: isImage
            width: isImage ? 60 : 0
            height: isImage ? 60 : 0

            Rectangle {
                id: imageThumbnailCard
                objectName: "chatAttachmentThumbnail"
                anchors.fill: parent
                radius: 8
                color: "#ffffff"
                border.width: 1
                border.color: thumbHover.hovered ? Theme.palette.brandOrange : Theme.palette.chatBorder

                VrLineIcon {
                    anchors.centerIn: parent
                    width: 22
                    height: 22
                    kind: "image"
                    foreground: Theme.palette.mutedText
                }

                Image {
                    id: thumbImage
                    anchors.fill: parent
                    anchors.margins: 2
                    source: thumbDelegate.imageSource
                    fillMode: Image.PreserveAspectCrop
                    smooth: true
                    mipmap: true
                    asynchronous: true
                    cache: true
                }

                Rectangle {
                    id: removeBadge
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 3
                    width: 18
                    height: 18
                    radius: 9
                    color: removeHover.hovered ? Theme.palette.brandOrange : Qt.rgba(0.12, 0.15, 0.18, 0.78)
                    z: 10

                    VrLineIcon {
                        anchors.centerIn: parent
                        width: 8
                        height: 8
                        kind: "close"
                        strokeWidth: 2
                        foreground: "#ffffff"
                    }

                    MouseArea {
                        id: removeHover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: composerCard.page.chatBridge.removeAttachment(thumbDelegate.index)
                    }
                }

                HoverHandler {
                    id: thumbHover
                }

                ToolTip.visible: thumbHover.hovered && !removeHover.hovered
                ToolTip.text: thumbDelegate.modelData ? (thumbDelegate.modelData.name || "") : ""
                ToolTip.delay: 300
            }
        }
    }

    // Attachment chips row (pill chips with file size, matching Image 2: [icon filename sizeKB x])
    ListView {
        id: attachmentList
        objectName: "chatAttachmentList"
        visible: composerCard.attachmentsCount > 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: composerCard.hasImageAttachments ? attachmentThumbnailsList.bottom : parent.top
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: composerCard.hasImageAttachments ? 8 : 12
        height: visible ? 26 : 0
        orientation: ListView.Horizontal
        spacing: 6
        clip: true
        model: composerCard.page.chatBridge.attachments
        delegate: Rectangle {
            id: attachmentChip
            required property int index
            required property var modelData
            readonly property bool isImage: {
                var p = String((modelData && (modelData.path || modelData.name)) || "").toLowerCase()
                return p.endsWith(".png") || p.endsWith(".jpg") || p.endsWith(".jpeg") ||
                       p.endsWith(".webp") || p.endsWith(".gif") || p.endsWith(".bmp") ||
                       p.endsWith(".svg") || p.endsWith(".ico")
            }
            readonly property string sizeText: composerCard.page.chatBridge.attachmentSizeLabel(modelData ? (modelData.path || "") : "")
            width: Math.min(260, Math.max(64, chipRow.implicitWidth + 14))
            height: 26
            radius: 8
            color: Theme.palette.chatControl
            border.width: 1
            border.color: Theme.palette.chatBorder

            Row {
                id: chipRow
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 4
                spacing: 5

                VrLineIcon {
                    width: 12
                    height: 12
                    anchors.verticalCenter: parent.verticalCenter
                    kind: attachmentChip.isImage ? "image" : "files"
                    foreground: Theme.palette.mutedText
                }

                Text {
                    id: attachmentLabel
                    width: Math.min(implicitWidth, attachmentChip.width - (sizeLabel.visible ? sizeLabel.implicitWidth + 46 : 42))
                    anchors.verticalCenter: parent.verticalCenter
                    text: attachmentChip.modelData ? (attachmentChip.modelData.name || "") : ""
                    elide: Text.ElideMiddle
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(10)
                }

                Text {
                    id: sizeLabel
                    visible: attachmentChip.sizeText.length > 0
                    anchors.verticalCenter: parent.verticalCenter
                    text: attachmentChip.sizeText
                    color: Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(10)
                }

                VrIconButton {
                    width: 18
                    height: 18
                    anchors.verticalCenter: parent.verticalCenter
                    iconKind: "close"
                    iconSize: 10
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
        anchors.top: attachmentList.visible ? attachmentList.bottom : (attachmentThumbnailsList.visible ? attachmentThumbnailsList.bottom : parent.top)
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: (attachmentList.visible || attachmentThumbnailsList.visible) ? 6 : 8
        height: Math.min(composerCard.page.chatMainHandle.height * 0.28, Math.max(54,
            contentHeight + topPadding + bottomPadding))
        clip: true
        ScrollBar.vertical: VrScrollBar {
            id: composerScrollBar
            objectName: "chatComposerScrollBar"
        }

        VrTextArea {
            id: composerInput
            objectName: "chatComposerInput"
            font.family: Theme.promptFontFamily
            font.pixelSize: Theme.promptFontSize(14)
            placeholderText: composerCard.page.chatMainHandle.width < 600 ? "Pergunte algo…" : "Pergunte algo…  @ arquivos · $ skills · / comandos"
            readOnly: composerCard.page.chatBridge.turnRunning
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
        visible: composerCard.hasSkills
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
                    font.pixelSize: Theme.fontSize(11)
                    font.weight: Font.DemiBold
                }
                VrIconButton {
                    width: 22
                    height: 22
                    anchors.verticalCenter: parent.verticalCenter
                    iconKind: "close"
                    iconSize: 11
                    foreground: Theme.palette.mutedText
                    onClicked: composerCard.page.chatBridge.removeActiveSkill(skillChip.index)
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
            Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.palette.chatBorder
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
        Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.palette.chatBorder }
        VrPermissionPicker {
            id: approvalSelector
            objectName: "chatPermissionPicker"
            model: composerCard.page.chatBridge.approvalItems
            currentIndex: composerCard.page.chatBridge.approvalIndex
            onActivated: index => composerCard.page.chatBridge.setApproval(index)
        }
        Item { Layout.fillWidth: true }
        VrIconButton {
            id: attachButton
            objectName: "chatAttachButton"
            implicitWidth: 32
            implicitHeight: 32
            iconKind: "attachment"
            iconSize: 17
            foreground: Theme.palette.mutedText
            enabled: !composerCard.page.chatBridge.turnRunning
            ToolTip.visible: hovered
            ToolTip.text: "Anexar arquivos"
            Accessible.name: "Anexar arquivos"
            onClicked: composerCard.page.chatBridge.chooseAttachments()
        }
        VrButton {
            id: vrModeButton
            objectName: "vrModeButton"
            implicitWidth: composerCard.page.chatBridge.vrMode === "ultra" ? 104 : 58
            implicitHeight: 32
            leftPadding: 7; rightPadding: 7
            text: composerCard.page.chatBridge.vrMode === "ultra" ? "VR Ultra" : "VR"
            variant: composerCard.page.chatBridge.vrMode !== "off" ? "primary" : "ghost"
            background: Rectangle {
                radius: 10
                color: composerCard.page.chatBridge.vrMode !== "off"
                    ? Theme.palette.accessibleOrange
                    : parent.hovered ? Theme.palette.chatControl : "transparent"
                border.width: parent.activeFocus ? 1 : 0
                border.color: parent.activeFocus ? Theme.palette.focus : "transparent"
            }
            onClicked: composerCard.page.chatBridge.cycleVrMode()
        }
        VrContextButton {
            id: contextUsageButton
            objectName: "contextUsageButton"
            implicitWidth: 30; implicitHeight: 30
            visible: composerCard.page.chatBridge.hasContextWindow
            fraction: composerCard.page.chatBridge.contextUsageFraction
            usageLabel: composerCard.page.chatBridge.contextUsageCompactLabel
            totalLabel: composerCard.page.chatBridge.totalProcessedLabel
            note: composerCard.page.chatBridge.contextUsageNote
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
            enabled: composerCard.page.chatBridge.turnRunning || composerInput.text.trim().length > 0 || composerCard.page.chatBridge.attachments.length > 0 || (composerCard.page.chatBridge.activeSkills && composerCard.page.chatBridge.activeSkills.length > 0)
            ToolTip.visible: hovered || activeFocus
            ToolTip.text: composerCard.page.chatBridge.turnRunning ? "Interromper geração" : "Enviar · Enter (Shift+Enter para nova linha)"
            Accessible.name: composerCard.page.chatBridge.turnRunning ? "Interromper geração" : "Enviar mensagem"
            iconSource: Qt.resolvedUrl(composerCard.page.chatBridge.turnRunning
                ? "../../../assets/chat-stop.svg"
                : "../../../assets/chat-send.svg")
            foreground: "#FFFFFF"
            background: Rectangle {
                radius: height / 2
                color: composerCard.page.chatBridge.turnRunning
                    ? (parent.down
                        ? Qt.darker(Theme.palette.danger, 1.18)
                        : parent.hovered
                            ? Qt.darker(Theme.palette.danger, 1.08)
                            : Theme.palette.danger)
                    : (parent.down
                        ? Theme.palette.brandOrange
                        : parent.hovered
                            ? Qt.darker(Theme.palette.accessibleOrange, 1.08)
                            : Theme.palette.accessibleOrange)
                border.width: parent.activeFocus ? 2 : 0
                border.color: Theme.palette.focus
            }
            onClicked: composerCard.page.chatBridge.turnRunning ? composerCard.page.chatBridge.stopTurn() : composerCard.page.submitMessage()
        }
}
