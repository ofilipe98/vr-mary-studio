import QtQuick
import QtQuick.Layouts
import "../theme"
import "../theme/ToolIcons.js" as ToolIcons

// Bounded group of tool calls (T3 Code "work group"): a summary row that
// discloses the member rows flat below it, with no extra card chrome.
Item {
    id: root
    objectName: "toolGroupCard"

    property var modelData: ({})
    property bool groupExpanded: false

    readonly property var childItems: modelData.items || []
    readonly property int childCount: childItems.length || Number(modelData.memberCount || 0)
    readonly property string titleText: String(modelData.text || modelData.title || (childCount + " ações agrupadas"))
    readonly property string durationLabel: String(modelData.durationLabel || "")
    readonly property string stateValue: String(modelData.state || "completed")
    readonly property bool isRunning: stateValue === "running"
    readonly property bool isError: stateValue === "error" || stateValue === "failed"
    readonly property bool isSuccess: stateValue === "completed" || stateValue === "success"
    readonly property bool isWaitingApproval: stateValue === "waiting_approval"
    readonly property bool canExpand: root.childItems.length > 0
    readonly property bool reduceMotion: typeof frontend !== "undefined" && frontend !== null
        ? frontend.reduceMotion : false

    implicitHeight: mainColumn.implicitHeight

    function resolveIcon() {
        if (root.isError) return "circleAlert"
        if (root.isWaitingApproval) return "lock"
        if (root.childItems.length > 0)
            return ToolIcons.kindFor(root.childItems[0], "hammer")
        return ToolIcons.kindFor(root.modelData, "hammer")
    }

    ColumnLayout {
        id: mainColumn
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.scaledGeometry(4)

        Rectangle {
            id: header
            objectName: "toolGroupHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(28)
            radius: Theme.scaledGeometry(6)
            color: "transparent"
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: root.titleText
            Accessible.description: root.groupExpanded ? "Recolher grupo" : "Expandir grupo"
            border.width: activeFocus ? 1 : 0
            border.color: Theme.palette.focus
            Keys.onReturnPressed: { if (root.canExpand) root.groupExpanded = !root.groupExpanded }
            Keys.onSpacePressed: { if (root.canExpand) root.groupExpanded = !root.groupExpanded }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(2)
                anchors.rightMargin: Theme.scaledGeometry(2)
                spacing: Theme.scaledGeometry(6)

                Item {
                    Layout.preferredWidth: Theme.scaledGeometry(24)
                    Layout.preferredHeight: Theme.scaledGeometry(24)
                    VrLineIcon {
                        anchors.centerIn: parent
                        width: Theme.iconSmall
                        height: Theme.iconSmall
                        kind: root.resolveIcon()
                        opacity: root.isError ? 0.75 : 0.9
                        foreground: root.isError
                            ? Theme.palette.danger
                            : (root.isWaitingApproval ? Theme.palette.warning : Theme.palette.mutedText)
                    }
                }

                VrShimmerText {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: root.titleText
                    running: root.isRunning
                    color: root.isError
                        ? Theme.palette.danger
                        : (root.isRunning ? Theme.palette.text : Theme.palette.mutedText)
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    elide: Text.ElideRight
                    renderType: Theme.textRenderType
                }

                Text {
                    visible: root.durationLabel.length > 0
                    text: root.durationLabel
                    color: Theme.palette.mutedText
                    opacity: 0.8
                    font.family: Theme.monospaceFontFamily
                    font.pixelSize: Theme.fontSizeMicro
                    renderType: Theme.textRenderType
                }

                VrLineIcon {
                    Layout.preferredWidth: Theme.iconMicro
                    Layout.preferredHeight: Theme.iconMicro
                    kind: "chevronRight"
                    foreground: Theme.palette.mutedText
                    opacity: root.canExpand ? 0.7 : 0
                    rotation: root.groupExpanded ? 90 : 0
                    Behavior on rotation {
                        enabled: !root.reduceMotion
                        NumberAnimation { duration: Theme.fastDuration; easing.type: Easing.OutCubic }
                    }
                }
            }

            HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
            TapHandler {
                onTapped: { if (root.canExpand) root.groupExpanded = !root.groupExpanded }
            }
        }

        ColumnLayout {
            id: childrenColumn
            visible: root.groupExpanded && root.childItems.length > 0
            Layout.fillWidth: true
            Layout.topMargin: Theme.scaledGeometry(4)
            spacing: Theme.scaledGeometry(4)

            Repeater {
                model: root.childItems

                Loader {
                    id: childLoader
                    required property var modelData
                    Layout.fillWidth: true
                    sourceComponent: {
                        var t = String(modelData.type || modelData.itemType || "")
                        if (t === "commandExecution" || modelData.command) return subCommandComponent
                        return subToolComponent
                    }
                    // A real binding (not an onLoaded assignment) so member rows
                    // that are reused when the group updates keep showing the
                    // current event data.
                    Binding {
                        target: childLoader.item
                        property: "modelData"
                        value: childLoader.modelData
                        when: childLoader.item !== null
                        restoreMode: Binding.RestoreNone
                    }
                }
            }
        }
    }

    Component {
        id: subCommandComponent
        VrCommandCard {}
    }

    Component {
        id: subToolComponent
        VrToolCard {}
    }
}
