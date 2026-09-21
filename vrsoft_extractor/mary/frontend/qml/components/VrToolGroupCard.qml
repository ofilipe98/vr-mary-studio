import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "toolGroupCard"

    property var modelData: ({})
    property bool groupExpanded: false

    readonly property var childItems: modelData.items || []
    readonly property int childCount: childItems.length || Number(modelData.memberCount || 0)
    readonly property string titleText: String(modelData.text || modelData.title || (childCount + " ações agrupadas"))
    readonly property string durationLabel: String(modelData.durationLabel || "")
    readonly property string badgeText: String(modelData.badgeText || (childCount > 0 ? (childCount + " ações") : ""))
    readonly property string stateValue: String(modelData.state || "completed")
    readonly property bool isRunning: stateValue === "running"
    readonly property bool isError: stateValue === "error" || stateValue === "failed"
    readonly property bool isSuccess: stateValue === "completed" || stateValue === "success"
    readonly property bool isWaitingApproval: stateValue === "waiting_approval"

    implicitHeight: mainColumn.implicitHeight

    function resolveIcon() {
        if (root.isError) return "close"
        if (root.isSuccess) return "check"
        if (root.isWaitingApproval) return "alert"
        var explicit = String(root.modelData.icon || "")
        if (explicit === "search") return "search"
        if (explicit === "document" || explicit === "files") return "files"
        if (explicit === "terminal" || explicit === "terminalPrompt") return "terminalPrompt"
        return "hammer"
    }

    ColumnLayout {
        id: mainColumn
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.scaledGeometry(4)

        // Group Header Box
        Rectangle {
            id: headerBox
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: root.titleText
            Accessible.description: root.groupExpanded ? "Recolher grupo" : "Expandir grupo"
            Keys.onReturnPressed: root.groupExpanded = !root.groupExpanded
            Keys.onSpacePressed: root.groupExpanded = !root.groupExpanded
            border.width: activeFocus ? 1 : 0
            border.color: Theme.palette.focus
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(28)
            radius: Theme.scaledGeometry(4)
            color: "transparent"
            clip: true

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(4)
                anchors.rightMargin: Theme.scaledGeometry(6)
                spacing: Theme.scaledGeometry(7)

                VrLineIcon {
                    Layout.preferredWidth: Theme.scaledGeometry(14)
                    Layout.preferredHeight: Theme.scaledGeometry(14)
                    kind: root.resolveIcon()
                    foreground: root.isError
                        ? Theme.palette.danger
                        : (root.isSuccess
                            ? Theme.palette.success
                            : (root.isWaitingApproval ? Theme.palette.warning : Theme.palette.mutedText))
                }

                VrShimmerText {
                    Layout.fillWidth: true
                    text: root.titleText
                    running: root.isRunning
                    color: root.isError
                        ? Theme.palette.danger
                        : (root.isRunning ? Theme.palette.text : Theme.palette.mutedText)
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                    font.weight: root.isRunning ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                    renderType: Theme.textRenderType
                }

                // Duration badge
                Text {
                    visible: root.durationLabel.length > 0
                    text: root.durationLabel
                    color: Theme.palette.mutedText
                    font.family: Theme.monospaceFontFamily
                    font.pixelSize: Theme.fontSizeMicro
                    renderType: Theme.textRenderType
                }

                // Group count badge
                Rectangle {
                    visible: root.badgeText.length > 0
                    Layout.preferredHeight: Theme.scaledGeometry(18)
                    Layout.preferredWidth: badgeLabel.implicitWidth + 10
                    radius: Theme.scaledGeometry(3)
                    color: root.isError
                        ? Qt.rgba(Theme.palette.danger.r, Theme.palette.danger.g, Theme.palette.danger.b, 0.15)
                        : (root.isSuccess
                            ? Qt.rgba(Theme.palette.success.r, Theme.palette.success.g, Theme.palette.success.b, 0.15)
                            : (root.isWaitingApproval
                                ? Qt.rgba(Theme.palette.warning.r, Theme.palette.warning.g, Theme.palette.warning.b, 0.15)
                                : Qt.rgba(Theme.palette.mutedText.r, Theme.palette.mutedText.g, Theme.palette.mutedText.b, 0.12)))

                    Text {
                        id: badgeLabel
                        anchors.centerIn: parent
                        text: root.badgeText
                        color: root.isError
                            ? Theme.palette.danger
                            : (root.isSuccess
                                ? Theme.palette.success
                                : (root.isWaitingApproval ? Theme.palette.warning : Theme.palette.mutedText))
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        font.weight: Font.Medium
                        renderType: Theme.textRenderType
                    }
                }

                VrLineIcon {
                    Layout.preferredWidth: Theme.scaledGeometry(9)
                    Layout.preferredHeight: Theme.scaledGeometry(9)
                    kind: root.groupExpanded ? "chevronDown" : "chevronRight"
                    foreground: Theme.palette.mutedText
                }
            }

            HoverHandler { cursorShape: Qt.PointingHandCursor }
            TapHandler {
                onTapped: root.groupExpanded = !root.groupExpanded
            }
        }

        // Expandable children container
        Rectangle {
            visible: root.groupExpanded && root.childItems.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: childrenColumn.implicitHeight + 8
            radius: Theme.scaledGeometry(4)
            color: Theme.palette.surfaceRaised
            border.width: 1
            border.color: Theme.palette.chatBorder
            clip: true

            ColumnLayout {
                id: childrenColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.scaledGeometry(4)
                spacing: Theme.scaledGeometry(3)

                Repeater {
                    model: root.childItems

                    Loader {
                        required property var modelData
                        Layout.fillWidth: true
                        sourceComponent: {
                            var t = String(modelData.type || modelData.itemType || "")
                            if (t === "commandExecution" || modelData.command) return subCommandComponent
                            return subToolComponent
                        }
                        onLoaded: {
                            if (item) item.modelData = Qt.binding(function() { return modelData })
                        }
                    }
                }
            }
        }
    }

    Component {
        id: subCommandComponent
        VrCommandCard {
            property var modelData: ({})
        }
    }

    Component {
        id: subToolComponent
        VrToolCard {
            property var modelData: ({})
        }
    }
}
