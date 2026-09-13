pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Dialog {
    id: root
    objectName: "vrUsageLimitsDialog"
    required property var chatBridge
    property var targetItem: null

    // Local coordinates follow the composer through SplitView and window resizing.
    parent: targetItem || Overlay.overlay
    readonly property real sideInset: targetItem && targetItem.width >= 600 ? 20 : 0
    width: targetItem ? Math.max(0, targetItem.width - sideInset * 2) : Math.min(720, parent.width - 32)
    implicitHeight: header.implicitHeight + contentCol.implicitHeight + topPadding + bottomPadding
    height: Math.min(implicitHeight, targetItem ? targetItem.parent.height * 0.42 : parent.height - 32)
    x: targetItem ? sideInset : (parent.width - width) / 2
    y: targetItem ? -height - 8 : (parent.height - height) / 2
    modal: false
    dim: false
    title: ""
    header: Item {
        implicitHeight: usageHeader.implicitHeight + 12
        RowLayout {
            id: usageHeader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 12
            spacing: 6
            VrLineIcon {
                kind: "gauge"
                Layout.preferredWidth: 13
                Layout.preferredHeight: 13
                foreground: Theme.palette.mutedText
            }
            Text {
                text: "Usage limits"
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: root.accountsList.length ? root.accountsList.length + (root.accountsList.length === 1 ? " account" : " accounts") : ""
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
                elide: Text.ElideRight
            }
            VrIconButton {
                objectName: "usageLimitsClose"
                iconKind: "close"
                iconSize: 10
                implicitWidth: 20
                implicitHeight: 20
                foreground: Theme.palette.mutedText
                onClicked: root.close()
            }
        }

    }
    footer: Item { implicitHeight: 0; visible: false }
    padding: 12
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    readonly property bool compact: availableWidth < 480 * Theme.textScale

    background: Rectangle {
        color: Qt.alpha(Theme.palette.chatSidebar, Theme.glassOpacity)
        border.width: 1
        border.color: Theme.palette.chatBorder
        radius: Theme.radiusCard
    }

    readonly property var snapshot: root.chatBridge ? root.chatBridge.usageSnapshot : ({})
    readonly property string status: String(snapshot ? snapshot.status || "" : "")
    readonly property string providerName: String(snapshot ? snapshot.provider || "" : "")
    readonly property var accountsList: {
        if (snapshot && snapshot.accounts && snapshot.accounts.length > 0)
            return snapshot.accounts
        if (snapshot && snapshot.windows && snapshot.windows.length > 0)
            return [{ account: snapshot.account || "", plan: snapshot.plan || "",
                      provider: snapshot.provider || "", windows: snapshot.windows }]
        return []
    }

    function formatAccountTitle(acc) {
        var provider = acc.provider || root.providerName
        var parts = provider ? [provider.charAt(0).toUpperCase() + provider.slice(1)] : []
        if (acc.account) parts.push(String(acc.account).split("@")[0])
        // Only name a subscription when the provider actually reports one.
        if (acc.plan) {
            var plan = String(acc.plan)
            parts.push(provider.toLowerCase() === "codex"
                       ? "ChatGPT " + plan.charAt(0).toUpperCase() + plan.slice(1) + " Subscription"
                       : plan)
        }
        return parts.join(" · ")
    }

    function remainingPercent(window) {
        var value = window.remainingPercent
        return value === null || value === undefined || !isFinite(Number(value))
            ? -1 : Math.max(0, Math.min(100, Number(value)))
    }

    function pacePosition(window) {
        var reset = Number(window.resetAt)
        var duration = Number(window.windowDurationMins) * 60
        // Position uses the same remaining scale as the bar; no invented threshold.
        if (!(reset > 0) || !(duration > 0)) return -1
        return Math.max(0, Math.min(1, (reset - Date.now() / 1000) / duration))
    }

    contentItem: Flickable {
        id: scroll
        implicitHeight: contentCol.implicitHeight
        contentHeight: contentCol.implicitHeight
        contentWidth: width
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        ScrollBar.vertical: ScrollBar {
            id: usageScrollBar
            policy: ScrollBar.AsNeeded
            visible: scroll.contentHeight > scroll.height
        }

        ColumnLayout {
            id: contentCol
            width: scroll.width - (usageScrollBar.visible ? usageScrollBar.width + 6 : 0)
            spacing: 10

            Repeater {
                model: root.accountsList
                delegate: ColumnLayout {
                    id: account
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.leftMargin: root.compact ? 0 : 18
                    spacing: 5
                    Text {
                        objectName: "usageAccountTitle"
                        Layout.fillWidth: true
                        text: root.formatAccountTitle(account.modelData)
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        elide: Text.ElideRight
                    }
                    Repeater {
                        model: account.modelData.windows || []
                        delegate: GridLayout {
                            id: windowRow
                            required property var modelData
                            readonly property real remaining: root.remainingPercent(modelData)
                            readonly property real pace: root.pacePosition(modelData)
                            objectName: "usageWindowRow"
                            Layout.fillWidth: true
                            columns: root.compact ? 2 : 4
                            columnSpacing: 10
                            rowSpacing: 4
                            Text {
                                Layout.row: 0
                                Layout.column: 0
                                Layout.preferredWidth: root.compact ? -1 : 76 * Theme.textScale
                                Layout.fillWidth: root.compact
                                text: windowRow.modelData.label || "Session"
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                elide: Text.ElideRight
                            }
                            Text {
                                objectName: "usageRemaining"
                                Layout.row: 0
                                Layout.column: 1
                                Layout.preferredWidth: 60 * Theme.textScale
                                horizontalAlignment: Text.AlignRight
                                text: windowRow.remaining < 0 ? "—" : Math.round(windowRow.remaining) + "% left"
                                color: Theme.palette.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                font.weight: Font.DemiBold
                            }
                            Item {
                                objectName: "usageTrack"
                                Layout.row: root.compact ? 1 : 0
                                Layout.column: root.compact ? 0 : 2
                                Layout.columnSpan: root.compact ? 2 : 1
                                Layout.fillWidth: true
                                Layout.minimumWidth: 40
                                Layout.preferredHeight: 20
                                Rectangle {
                                    id: track
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width
                                    height: 10
                                    radius: 5
                                    color: Theme.palette.chatControl
                                    Rectangle {
                                        objectName: "usageFill"
                                        height: parent.height
                                        width: parent.width * Math.max(0, windowRow.remaining) / 100
                                        radius: parent.radius
                                        color: Theme.palette.text
                                        visible: windowRow.remaining > 0
                                    }
                                    Rectangle {
                                        visible: windowRow.pace >= 0
                                        x: Math.max(0, Math.min(track.width - width, track.width * windowRow.pace))
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 1
                                        height: 18
                                        color: Theme.palette.mutedText
                                        opacity: 0.6
                                    }
                                }
                            }
                            RowLayout {
                                Layout.row: root.compact ? 2 : 0
                                Layout.column: root.compact ? 0 : 3
                                Layout.columnSpan: root.compact ? 2 : 1
                                Layout.preferredWidth: 118 * Theme.textScale
                                Layout.maximumWidth: 118 * Theme.textScale
                                Layout.fillWidth: false
                                Layout.alignment: Qt.AlignRight
                                spacing: 7
                                visible: Boolean(windowRow.modelData.resetInText)
                                VrLineIcon {
                                    kind: "trendUp"
                                    Layout.preferredWidth: 12
                                    Layout.preferredHeight: 12
                                    foreground: Theme.palette.mutedText
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: windowRow.modelData.resetInText || ""
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(11)
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: Boolean(root.snapshot && root.snapshot.credits && root.snapshot.credits.hasCredits)
                text: "API Credits: " + String(root.snapshot && root.snapshot.credits ? root.snapshot.credits.balance ?? "0" : "0")
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
            }
            Text {
                Layout.fillWidth: true
                visible: root.accountsList.length === 0
                text: root.status === "unsupported"
                    ? "Este provedor não disponibiliza limites de uso localmente."
                    : root.status === "error" || root.status === "unavailable"
                        ? "Não foi possível consultar os limites de uso."
                        : "Carregando informações de limite de uso…"
                color: Theme.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                wrapMode: Text.WordWrap
            }
        }
    }
}
