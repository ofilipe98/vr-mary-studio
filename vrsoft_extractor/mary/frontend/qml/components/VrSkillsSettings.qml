pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "vrSkillsSettings"
    required property var studio
    readonly property bool compact: width < Theme.scaledGeometry(600)

    property var skillsList: []
    property string searchQuery: ""
    property string selectedProviderFilter: "all"
    property string feedbackMessage: ""
    property bool feedbackIsError: false

    function refresh() {
        if (root.studio && root.studio.chatBridge) {
            skillsList = root.studio.chatBridge.allSkills()
        }
    }

    Component.onCompleted: refresh()

    Item {
        anchors.fill: parent
        anchors.margins: Theme.scaledGeometry(24)

        ColumnLayout {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(848, parent.width)
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            spacing: Theme.scaledGeometry(16)

            // Page Header
            GridLayout {
                Layout.fillWidth: true
                columns: root.compact ? 2 : 3
                columnSpacing: Theme.spaceMd

                Text {
                    Layout.columnSpan: root.compact ? 2 : 1
                    wrapMode: Text.WordWrap
                    text: "Gerenciador de skills"
                    Layout.leftMargin: Theme.scaledGeometry(16)
                    Layout.fillWidth: true
                    color: Theme.palette.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }

                VrButton {
                    text: "Atualizar"
                    variant: "ghost"
                    implicitHeight: Theme.scaledGeometry(28)
                    onClicked: root.refresh()
                }

                VrButton {
                    objectName: "openNewSkillButton"
                    text: "+ Nova Skill"
                    variant: "primary"
                    implicitHeight: Theme.scaledGeometry(28)
                    onClicked: newSkillDialog.open()
                }
            }

        // Feedback Banner
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.scaledGeometry(36)
            radius: Theme.scaledGeometry(8)
            visible: root.feedbackMessage.length > 0
            color: root.feedbackIsError ? Qt.rgba(0.9, 0.2, 0.2, 0.15) : Qt.rgba(0.2, 0.8, 0.3, 0.15)
            border.width: 1
            border.color: root.feedbackIsError ? Theme.palette.danger : Theme.palette.success

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(10)
                Text {
                    Layout.fillWidth: true
                    text: root.feedbackMessage
                    color: root.feedbackIsError ? Theme.palette.danger : Theme.palette.success
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                    elide: Text.ElideRight
                }
                VrIconButton {
                    iconKind: "close"
                    iconSize: Theme.iconMicro
                    onClicked: root.feedbackMessage = ""
                }
            }
        }

        // Filter and Search Toolbar
        GridLayout {
            columns: root.compact ? 1 : 2
            Layout.fillWidth: true
            columnSpacing: Theme.spaceMd

            VrTextField {
                id: searchInput
                Layout.fillWidth: true
                implicitHeight: Theme.scaledGeometry(38)
                placeholderText: "Filtrar skills por nome ou descrição…"
                background: Rectangle {
                    radius: Theme.scaledGeometry(10)
                    color: Theme.palette.background
                    border.width: searchInput.activeFocus ? 2 : 1
                    border.color: searchInput.activeFocus ? Theme.palette.focus : Theme.palette.border
                }
                onTextChanged: root.searchQuery = text.trim().toLowerCase()
            }

            VrComboBox {
                id: providerFilter
                Layout.fillWidth: root.compact
                Layout.preferredWidth: Theme.scaledGeometry(150)
                model: [
                    {label: "Todos", value: "all"},
                    {label: "Codex", value: "codex"},
                    {label: "Claude", value: "claude"},
                    {label: "Antigravity", value: "antigravity"},
                    {label: "App / VR", value: "app"}
                ]
                textRole: "label"
                onActivated: index => {
                    root.selectedProviderFilter = model[index].value
                }
            }
        }

        // Skills List
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.scaledGeometry(14)
            color: Theme.palette.background
            border.width: 1
            border.color: Theme.palette.border

            ListView {
                id: skillsListView
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(8)
                spacing: Theme.scaledGeometry(6)
                clip: true
                model: {
                    var filtered = []
                    var q = root.searchQuery
                    var p = root.selectedProviderFilter
                    for (var i = 0; i < root.skillsList.length; i++) {
                        var s = root.skillsList[i]
                        if (p !== "all" && (s.provider || "").toLowerCase() !== p) continue
                        if (q.length > 0) {
                            var n = (s.name || "").toLowerCase()
                            var d = (s.description || "").toLowerCase()
                            if (n.indexOf(q) < 0 && d.indexOf(q) < 0) continue
                        }
                        filtered.push(s)
                    }
                    return filtered
                }

                delegate: Rectangle {
                    id: skillItemRow
                    required property var modelData
                    width: skillsListView.width
                    implicitHeight: itemCol.implicitHeight + 16
                    radius: Theme.scaledGeometry(10)
                    color: Theme.palette.codeSurface
                    border.width: 1
                    border.color: Theme.palette.border

                    RowLayout {
                        id: itemCol
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(12)
                        spacing: Theme.scaledGeometry(12)

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.scaledGeometry(4)

                            RowLayout {
                                spacing: Theme.scaledGeometry(8)
                                Text {
                                    text: "$" + (skillItemRow.modelData.name || "")
                                    color: Theme.palette.brandOrange
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(13)
                                    font.weight: Font.DemiBold
                                }

                                Rectangle {
                                    radius: Theme.scaledGeometry(4)
                                    color: Theme.palette.chatControl
                                    implicitWidth: provText.implicitWidth + 8
                                    implicitHeight: Theme.scaledGeometry(20)
                                    Text {
                                        id: provText
                                        anchors.centerIn: parent
                                        text: skillItemRow.modelData.provider || "app"
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeMicro
                                    }
                                }

                                Rectangle {
                                    radius: Theme.scaledGeometry(4)
                                    color: Theme.palette.chatControl
                                    implicitWidth: scopeText.implicitWidth + 8
                                    implicitHeight: Theme.scaledGeometry(20)
                                    Text {
                                        id: scopeText
                                        anchors.centerIn: parent
                                        text: skillItemRow.modelData.scope || "project"
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeMicro
                                    }
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: skillItemRow.modelData.description || "Sem descrição informada."
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeCompact
                                elide: Text.ElideRight
                            }

                            Text {
                                Layout.fillWidth: true
                                text: skillItemRow.modelData.path || ""
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeMicro
                                elide: Text.ElideMiddle
                            }
                        }

                        VrButton {
                            text: "Editar"
                            variant: "ghost"
                            onClicked: {
                                editSkillDialog.targetSkill = skillItemRow.modelData
                                editSkillInstructions.text = skillItemRow.modelData.instructions || ""
                                editSkillDesc.text = skillItemRow.modelData.description || ""
                                editSkillDialog.open()
                            }
                        }
                    }
                }

                VrEmptyState {
                    anchors.centerIn: parent
                    visible: parent.count === 0
                    title: "Nenhuma Skill Encontrada"
                    description: "Crie uma nova skill com '+ Nova Skill' ou selecione outro filtro."
                }
            }
        }
    }
}

    // Dialog: Nova Skill
    Dialog {
        id: newSkillDialog
        objectName: "newSkillDialog"
        anchors.centerIn: Overlay.overlay
        width: Math.min(540, root.width - 32)
        height: Math.min(560, root.height - 32)
        modal: true
        standardButtons: Dialog.NoButton
        padding: Theme.scaledGeometry(20)
        topPadding: Theme.scaledGeometry(12)
        bottomPadding: Theme.scaledGeometry(16)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        onClosed: {
            newSkillName.clear()
            newSkillDescription.clear()
            newSkillInstructions.clear()
        }

        header: Item {
            implicitHeight: Theme.scaledGeometry(48)
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(20)
                anchors.rightMargin: Theme.scaledGeometry(16)
                anchors.topMargin: Theme.scaledGeometry(12)
                spacing: Theme.scaledGeometry(8)

                Text {
                    Layout.fillWidth: true
                    text: "Criar Nova Skill"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(15)
                    font.weight: Font.DemiBold
                }

                VrIconButton {
                    iconKind: "close"
                    iconSize: Theme.iconMicro
                    implicitWidth: Theme.scaledGeometry(28)
                    implicitHeight: Theme.scaledGeometry(28)
                    foreground: Theme.palette.mutedText
                    onClicked: newSkillDialog.close()
                }
            }
        }

        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.border
            radius: Theme.radiusPopup
        }

        contentItem: ColumnLayout {
            spacing: Theme.scaledGeometry(12)

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.scaledGeometry(10)

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.scaledGeometry(4)

                    Text {
                        text: "Nome da Skill (sem espaços):"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeCaption
                        font.weight: Font.Medium
                    }

                    VrTextField {
                        id: newSkillName
                        Layout.fillWidth: true
                        placeholderText: "ex: code-reviewer, db-optimizer"
                    }
                }

                ColumnLayout {
                    Layout.preferredWidth: Theme.scaledGeometry(140)
                    spacing: Theme.scaledGeometry(4)

                    Text {
                        text: "Provedor:"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeCaption
                        font.weight: Font.Medium
                    }

                    VrComboBox {
                        id: newSkillProvider
                        Layout.fillWidth: true
                        model: [
                            {label: "Codex", value: "codex"},
                            {label: "Claude", value: "claude"},
                            {label: "Antigravity", value: "antigravity"},
                            {label: "App / VR", value: "app"}
                        ]
                        textRole: "label"
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.scaledGeometry(4)

                Text {
                    text: "Descrição resumida:"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                    font.weight: Font.Medium
                }

                VrTextField {
                    id: newSkillDescription
                    Layout.fillWidth: true
                    placeholderText: "Para que serve a skill e quando deve ser ativada"
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.scaledGeometry(4)

                Text {
                    text: "Instruções / SKILL.md (Markdown):"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                    font.weight: Font.Medium
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: Theme.radiusControl
                    color: Theme.palette.surfaceRaised
                    border.width: 1
                    border.color: Theme.palette.border
                    clip: true

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(4)
                        clip: true

                        VrTextArea {
                            id: newSkillInstructions
                            background: Item {}
                            placeholderText: "Instruções detalhadas em Markdown que guiam o LLM..."
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.scaledGeometry(4)
                spacing: Theme.scaledGeometry(8)

                Item { Layout.fillWidth: true }

                VrButton {
                    text: "Cancelar"
                    variant: "ghost"
                    onClicked: newSkillDialog.close()
                }

                VrButton {
                    text: "Salvar Skill"
                    variant: "primary"
                    enabled: newSkillName.text.trim().length > 0
                    onClicked: {
                        var prov = newSkillProvider.model[newSkillProvider.currentIndex].value
                        var res = root.studio.chatBridge.createSkill(
                            prov,
                            newSkillName.text.trim(),
                            newSkillDescription.text.trim(),
                            newSkillInstructions.text,
                            "project"
                        )
                        if (res.success) {
                            root.feedbackMessage = "Skill '$" + newSkillName.text.trim() + "' criada com sucesso!"
                            root.feedbackIsError = false
                            newSkillDialog.close()
                            root.refresh()
                        } else {
                            root.feedbackMessage = "Erro ao criar skill: " + res.error
                            root.feedbackIsError = true
                        }
                    }
                }
            }
        }
    }

    // Dialog: Editar Skill
    Dialog {
        id: editSkillDialog
        objectName: "editSkillDialog"
        property var targetSkill: ({})
        anchors.centerIn: Overlay.overlay
        width: Math.min(540, root.width - 32)
        height: Math.min(560, root.height - 32)
        modal: true
        standardButtons: Dialog.NoButton
        padding: Theme.scaledGeometry(20)
        topPadding: Theme.scaledGeometry(12)
        bottomPadding: Theme.scaledGeometry(16)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        header: Item {
            implicitHeight: Theme.scaledGeometry(48)
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(20)
                anchors.rightMargin: Theme.scaledGeometry(16)
                anchors.topMargin: Theme.scaledGeometry(12)
                spacing: Theme.scaledGeometry(8)

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.scaledGeometry(8)

                    Text {
                        text: "Editar Skill"
                        color: Theme.palette.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(15)
                        font.weight: Font.DemiBold
                    }

                    Text {
                        text: "$" + (editSkillDialog.targetSkill ? (editSkillDialog.targetSkill.name || "") : "")
                        color: Theme.palette.brandOrange
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                        font.weight: Font.Bold
                    }
                }

                VrIconButton {
                    iconKind: "close"
                    iconSize: Theme.iconMicro
                    implicitWidth: Theme.scaledGeometry(28)
                    implicitHeight: Theme.scaledGeometry(28)
                    foreground: Theme.palette.mutedText
                    onClicked: editSkillDialog.close()
                }
            }
        }

        background: Rectangle {
            color: Theme.palette.surface
            border.width: 1
            border.color: Theme.palette.border
            radius: Theme.radiusPopup
        }

        contentItem: ColumnLayout {
            spacing: Theme.scaledGeometry(12)

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.scaledGeometry(4)

                Text {
                    text: "Descrição resumida:"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                    font.weight: Font.Medium
                }

                VrTextField {
                    id: editSkillDesc
                    Layout.fillWidth: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.scaledGeometry(4)

                Text {
                    text: "Instruções (Markdown):"
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                    font.weight: Font.Medium
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: Theme.radiusControl
                    color: Theme.palette.surfaceRaised
                    border.width: 1
                    border.color: Theme.palette.border
                    clip: true

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: Theme.scaledGeometry(4)
                        clip: true

                        VrTextArea {
                            id: editSkillInstructions
                            background: Item {}
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.scaledGeometry(4)
                spacing: Theme.scaledGeometry(8)

                Item { Layout.fillWidth: true }

                VrButton {
                    text: "Cancelar"
                    variant: "ghost"
                    onClicked: editSkillDialog.close()
                }

                VrButton {
                    text: "Salvar Alterações"
                    variant: "primary"
                    onClicked: {
                        var res = root.studio.chatBridge.updateSkill(
                            editSkillDialog.targetSkill.id,
                            editSkillInstructions.text,
                            editSkillDesc.text.trim()
                        )
                        if (res.success) {
                            root.feedbackMessage = "Skill atualizada com sucesso!"
                            root.feedbackIsError = false
                            editSkillDialog.close()
                            root.refresh()
                        } else {
                            root.feedbackMessage = "Erro ao atualizar skill: " + res.error
                            root.feedbackIsError = true
                        }
                    }
                }
            }
        }
    }
}
