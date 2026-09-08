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
    objectName: "chatComposerCard"
    anchors.horizontalCenter: parent.horizontalCenter
    y: composerCard.page.messageListHandle.count > 0 ? parent.height - height - composerCard.page.expertStripHeight - 24
        : Math.max(composerCard.page.chatHeaderHandle.height + composerCard.page.landingHandle.height + composerCard.page.usagePanelHeight + 32,
            (parent.height + composerCard.page.chatHeaderHandle.height + composerCard.page.landingHandle.height + composerCard.page.usagePanelHeight + 24 - height - composerCard.page.expertStripHeight) / 2)
    width: Math.min(Theme.contentWidth, parent.width - (parent.width < 600 ? 28 : 48))
    height: composerInput.height + (hasChips ? 88 : 54)
    radius: Theme.composerRadius
    color: Theme.palette.chatComposer
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

    VrTextArea {
        id: composerInput
        objectName: "chatComposerInput"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 8
        height: Math.min(composerCard.page.chatMainHandle.height * 0.28, Math.max(54,
            contentHeight + topPadding + bottomPadding))
        clip: true
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

    ListView {
        id: attachmentList
        objectName: "chatAttachmentList"
        visible: composerCard.page.chatBridge.attachments.length > 0
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
        model: composerCard.page.chatBridge.attachments
        delegate: Rectangle {
            id: attachmentChip
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
                    text: attachmentChip.modelData.name
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
                    onClicked: composerCard.page.chatBridge.removeAttachment(attachmentChip.index)
                }
            }
        }
    }

    ListView {
        id: skillChipList
        objectName: "chatSkillChipList"
        visible: composerCard.page.chatBridge.activeSkills && composerCard.page.chatBridge.activeSkills.length > 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: attachmentList.visible ? attachmentList.bottom : composerInput.bottom
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
                        : Theme.palette.danger)
                    : (parent.down
                        ? Theme.palette.brandOrange
                        : Theme.palette.accessibleOrange)
            }
            onClicked: composerCard.page.chatBridge.turnRunning ? composerCard.page.chatBridge.stopTurn() : composerCard.page.submitMessage()
        }
}
