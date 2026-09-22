pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../settings/appearance"

Item {
    id: root
    objectName: "providerSettings"
    property string selectedProvider: "antigravity"
    property bool refreshing: false
    property bool openingLogin: false
    property string refreshFeedback: ""
    property bool copied: false
    readonly property bool narrow: width < Theme.scaledGeometry(720)
    readonly property var selected: {
        var items = studio.providerItems
        for (var i = 0; i < items.length; ++i)
            if (items[i].id === selectedProvider) return items[i]
        return items.length ? items[0] : ({})
    }
    readonly property bool google: selected.id === "antigravity"
    readonly property string account: String(selected.accountStatus || "")
    readonly property string attemptState: String(selected.attemptState || "idle")
    readonly property string accountState: String(selected.accountState || "unknown")
    readonly property string providerReadiness: String(selected.providerReadiness || "unknown")
    readonly property string authUrl: String(selected.authUrl || "")
    readonly property string expiresAt: String(selected.expiresAt || "")
    readonly property bool isWaiting: Boolean(selected.isWaiting)
    readonly property bool isVerifying: Boolean(selected.isVerifying)
    readonly property bool isStarting: Boolean(selected.isStarting)
    readonly property bool hasCallback: isWaiting && authUrl.length > 0
    readonly property bool validating: account.indexOf("Validando") === 0 || Boolean(selected.isValidating || selected.checking)
    readonly property bool authenticated: accountState === "authenticated" || account.indexOf("Conta Google validada") === 0
    readonly property bool loginPending: isWaiting || isStarting || isVerifying || account.indexOf("Conclua o login") === 0
    readonly property bool authError: google && (attemptState === "failed" || account.indexOf("Não foi possível") === 0 || accountState === "unauthenticated")
    onIsWaitingChanged: { if (!isWaiting) manualCallbackField.text = "" }
    onSelectedProviderChanged: manualCallbackField.text = ""
    readonly property bool runtimeBusy: selected.runtimeState === "updating" || selected.runtimeState === "installing"

    function providerLabel(p) {
        return ({codex: "OpenAI Codex", claude: "Anthropic Claude Code", opencode: "OpenCode", antigravity: "Google Antigravity"})[p.id] || p.name || "Provider"
    }
    function status(p) {
        if (p.runtimeState === "updating") return {text: "Atualizando runtime…", tone: "muted", busy: true}
        if (p.runtimeState === "installing") return {text: "Instalando runtime…", tone: "muted", busy: true}
        if (p.runtimeState === "error") return {text: "Falha na instalação", tone: "danger"}
        if (!p.enabled) return {text: "Desativado", tone: "muted"}
        if (!p.available) return {text: "Não instalado", tone: "warning"}
        if (p.id !== "antigravity") return {text: "CLI instalado", tone: "success"}
        var a = String(p.accountStatus || "")
        if (p.isVerifying) {
            var vText = a.indexOf("modelos") !== -1 ? "Carregando modelos…" : (a.indexOf("confirmação") !== -1 ? "Aguardando confirmação…" : "Verificando…")
            return {text: vText, tone: "muted", busy: true}
        }
        if (p.isValidating || p.checking || a.indexOf("Validando") === 0) return {text: "Validando conta…", tone: "muted", busy: true}
        if (p.isWaiting) return {text: "Aguardando navegador…", tone: "warning"}
        if (p.isStarting) return {text: "Iniciando…", tone: "warning", busy: true}
        // Provider readiness outranks the bare account state: an
        // authenticated account with a degraded provider is not ready.
        if (p.providerReadiness === "degraded") {
            if (p.accountState === "authenticated") {
                return {text: "Conta autenticada · falha ao carregar modelos", tone: "warning"}
            }
            return {text: "Falha na validação", tone: "danger"}
        }
        if (p.providerReadiness === "failed") {
            if (p.accountState === "unauthenticated") {
                return {text: "Login necessário", tone: "warning"}
            }
            if (p.accountState === "authenticated") {
                return {text: "Conta autenticada · falha ao carregar modelos", tone: "warning"}
            }
            return {text: "Falha na validação", tone: "danger"}
        }
        if (p.attemptState === "failed") {
            if (p.accountState === "authenticated") {
                return {text: "Conta autenticada · falha ao carregar modelos", tone: "warning"}
            }
            if (p.accountState === "unauthenticated") {
                return {text: "Login necessário", tone: "warning"}
            }
            return {text: "Falha na validação", tone: "danger"}
        }
        if (p.accountState === "unauthenticated") {
            return {text: "Login necessário", tone: "warning"}
        }
        if (p.accountState === "authenticated" || a.indexOf("Conta Google validada") === 0 || a.indexOf("Conta Google autenticada") === 0) return {text: "Conta autenticada", tone: "success"}
        if (p.attemptState === "idle" || p.attemptState === "cancelled") return {text: "Conta não verificada", tone: "warning"}
        if (!a || a.indexOf("Conta Google ainda") === 0) return {text: "Conta não verificada", tone: "warning"}
        return {text: "Falha na validação", tone: "danger"}
    }
    function selectProvider(id) {
        selectedProvider = id
        copied = false
        if (detailsScroll.contentItem) detailsScroll.contentItem.contentY = 0
    }
    function moveProvider(delta) {
        var items = studio.providerItems
        for (var i = 0; i < items.length; ++i) {
            if (items[i].id === root.selected.id) {
                var target = Math.max(0, Math.min(items.length - 1, i + delta))
                selectProvider(items[target].id)
                providerList.currentIndex = target
                providerList.positionViewAtIndex(target, ListView.Contain)
                if (providerList.currentItem) providerList.currentItem.forceActiveFocus()
                return
            }
        }
    }
    Timer {
        id: refreshTimer; interval: 50
        onTriggered: {
            studio.refreshProviders()
            root.refreshing = false
            root.refreshFeedback = "Runtimes verificados agora"
        }
    }
    Timer { id: loginTimer; interval: 50; onTriggered: { studio.openAntigravityLogin(); root.openingLogin = false } }
    Timer { id: copyTimer; interval: 1800; onTriggered: root.copied = false }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.scaledGeometry(12)

        VrComboBox {
            id: providerCombo
            visible: root.narrow
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            displayText: root.selected.name || "Selecione um provedor"
            model: studio.providerItems
            textRole: "name"
            currentIndex: {
                var items = studio.providerItems
                for (var i = 0; i < items.length; ++i) if (items[i].id === root.selected.id) return i
                return -1
            }
            Accessible.name: "Provedor selecionado"
            onActivated: root.selectProvider(studio.providerItems[currentIndex].id)
            background: Rectangle {
                radius: Theme.scaledGeometry(10)
                color: Theme.palette.background
                border.width: providerCombo.activeFocus ? 2 : 1
                border.color: providerCombo.activeFocus ? Theme.palette.focus : Theme.palette.border
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.scaledGeometry(16)

            // ------------------------------------------------ Left Sidebar
            ColumnLayout {
                visible: !root.narrow
                Layout.preferredWidth: Theme.scaledGeometry(280)
                Layout.fillHeight: true
                spacing: Theme.scaledGeometry(12)

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.scaledGeometry(4)
                    Layout.rightMargin: Theme.scaledGeometry(4)

                    Text {
                        text: "Provedores"
                        color: Theme.palette.text
                        opacity: 0.7
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeControl
                        font.weight: Font.Medium
                        Layout.fillWidth: true
                    }

                    Rectangle {
                        radius: Theme.scaledGeometry(8)
                        color: Theme.palette.codeSurface
                        border.width: 1
                        border.color: Theme.palette.border
                        implicitWidth: countText.implicitWidth + 14
                        implicitHeight: Theme.scaledGeometry(22)

                        Text {
                            id: countText
                            anchors.centerIn: parent
                            text: studio.providerItems.length
                            color: Theme.palette.mutedText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeCaption
                            font.weight: Font.Medium
                        }
                    }
                }

                ListView {
                    id: providerList
                    objectName: "providerSidebar"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: Theme.scaledGeometry(8)
                    model: studio.providerItems
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: VrScrollBar {}
                    delegate: ItemDelegate {
                        id: providerRow
                        required property var modelData
                        required property int index
                        readonly property var stateInfo: root.status(modelData)
                        width: providerList.width
                        height: Theme.scaledGeometry(72)
                        padding: 0
                        objectName: "providerRow_" + modelData.id
                        Accessible.name: modelData.name + ", " + stateInfo.text
                        Accessible.selected: root.selected.id === modelData.id
                        focusPolicy: Qt.StrongFocus
                        onClicked: { forceActiveFocus(); root.selectProvider(modelData.id) }
                        Keys.onDownPressed: root.moveProvider(1)
                        Keys.onUpPressed: root.moveProvider(-1)

                        background: Rectangle {
                            radius: Theme.scaledGeometry(12)
                            color: root.selected.id === providerRow.modelData.id
                                ? Qt.alpha(Theme.palette.brandOrange, 0.08)
                                : providerRow.hovered ? Theme.palette.codeSurface : Theme.palette.background
                            border.width: root.selected.id === providerRow.modelData.id ? 1.5 : 1
                            border.color: root.selected.id === providerRow.modelData.id
                                ? Theme.palette.brandOrange
                                : providerRow.hovered ? Theme.palette.chatBorder : Theme.palette.border

                            Rectangle {
                                visible: root.selected.id === providerRow.modelData.id
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                width: Theme.scaledGeometry(3)
                                height: Theme.scaledGeometry(28)
                                radius: 1.5
                                color: Theme.palette.brandOrange
                            }

                            Behavior on color { enabled: !frontend.reduceMotion; ColorAnimation { duration: Theme.fastDuration } }
                            Behavior on border.color { enabled: !frontend.reduceMotion; ColorAnimation { duration: Theme.fastDuration } }
                        }

                        contentItem: RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.scaledGeometry(12)
                            anchors.rightMargin: Theme.scaledGeometry(12)
                            spacing: Theme.scaledGeometry(10)

                            Rectangle {
                                Layout.preferredWidth: Theme.scaledGeometry(34)
                                Layout.preferredHeight: Theme.scaledGeometry(34)
                                radius: Theme.scaledGeometry(8)
                                color: Theme.palette.codeSurface
                                border.width: 1
                                border.color: Theme.palette.border

                                VrProviderIcon {
                                    anchors.centerIn: parent
                                    width: Theme.scaledGeometry(22)
                                    height: Theme.scaledGeometry(22)
                                    provider: providerRow.modelData.id
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: Theme.scaledGeometry(3)

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.scaledGeometry(6)

                                    Text {
                                        Layout.fillWidth: true
                                        text: providerRow.modelData.name
                                        elide: Text.ElideRight
                                        color: Theme.palette.headingText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeControl
                                        font.weight: root.selected.id === providerRow.modelData.id ? Font.DemiBold : Font.Medium
                                    }

                                    Rectangle {
                                        visible: !!providerRow.modelData.installVersion
                                        radius: Theme.scaledGeometry(4)
                                        color: Theme.palette.codeSurface
                                        border.width: 1
                                        border.color: Theme.palette.border
                                        implicitWidth: verText.implicitWidth + 8
                                        implicitHeight: Theme.scaledGeometry(16)

                                        Text {
                                            id: verText
                                            anchors.centerIn: parent
                                            text: providerRow.modelData.installVersion || ""
                                            color: Theme.palette.subtleText
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeCaption
                                        }
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.scaledGeometry(5)

                                    Rectangle {
                                        width: Theme.scaledGeometry(6); height: Theme.scaledGeometry(6); radius: Theme.scaledGeometry(3)
                                        color: providerRow.stateInfo.tone === "success" ? Theme.palette.success
                                            : providerRow.stateInfo.tone === "danger" ? Theme.palette.danger
                                            : providerRow.stateInfo.tone === "warning" ? Theme.palette.warning
                                            : Theme.palette.mutedText
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: (providerRow.modelData.enabled ? "Ativado \u00b7 " : "Desativado \u00b7 ") + providerRow.stateInfo.text
                                        elide: Text.ElideRight
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeCaption
                                    }
                                }
                            }

                            VrSwitch {
                                subdued: true
                                checked: !!providerRow.modelData.enabled
                                Accessible.name: "Ativar " + providerRow.modelData.name
                                onToggled: {
                                    studio.setProviderEnabled(providerRow.modelData.id, checked)
                                    checked = Qt.binding(function() { return !!providerRow.modelData.enabled })
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                visible: !root.narrow
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                color: Theme.palette.border
            }

            // ------------------------------------------------ Right Details
            ScrollView {
                id: detailsScroll
                objectName: "providerDetailsScroll"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                contentWidth: availableWidth
                clip: true
                topPadding: 0
                rightPadding: Theme.scaledGeometry(12)
                bottomPadding: Theme.scaledGeometry(24)
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                Item {
                    width: detailsScroll.availableWidth
                    implicitHeight: detailsColumn.implicitHeight

                    ColumnLayout {
                        id: detailsColumn
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(848, parent.width)
                        spacing: Theme.scaledGeometry(24)

                        // Header Identity Card
                        AppearanceGroup {
                            Layout.fillWidth: true

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: headerDetailsContent.implicitHeight + Theme.space2Xl

                                ColumnLayout {
                                    id: headerDetailsContent
                                    anchors.fill: parent
                                    anchors.margins: Theme.scaledGeometry(16)
                                    spacing: Theme.scaledGeometry(16)

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: headerDetailsContent.width < Theme.scaledGeometry(600) ? 2 : 3
                                        columnSpacing: Theme.scaledGeometry(14)

                                        Rectangle {
                                            Layout.preferredWidth: Theme.scaledGeometry(44)
                                            Layout.preferredHeight: Theme.scaledGeometry(44)
                                            radius: Theme.scaledGeometry(10)
                                            color: Theme.palette.codeSurface
                                            border.width: 1
                                            border.color: Theme.palette.border

                                            VrProviderIcon {
                                                anchors.centerIn: parent
                                                width: Theme.scaledGeometry(26)
                                                height: Theme.scaledGeometry(26)
                                                provider: root.selected.id || "codex"
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            spacing: Theme.scaledGeometry(3)

                                            GridLayout {
                                                Layout.fillWidth: true
                                                columns: headerDetailsContent.width < Theme.scaledGeometry(600) ? 1 : 2
                                                columnSpacing: Theme.spaceSm
                                                Text {
                                                    Layout.fillWidth: true
                                                    Layout.minimumWidth: 0
                                                    text: root.selected.name || "Selecione um provedor"
                                                    elide: Text.ElideRight
                                                    color: Theme.palette.headingText
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: Theme.fontSizeBody
                                                    font.weight: Font.DemiBold
                                                }
                                                VrProviderStatus {
                                                    objectName: "providerHeaderStatus"
                                                    announceChanges: true
                                                    text: root.status(root.selected).text
                                                    tone: root.status(root.selected).tone
                                                    busy: !!root.status(root.selected).busy
                                                }
                                            }

                                            Text {
                                                text: root.providerLabel(root.selected) + (root.selected.description ? " \u00b7 " + root.selected.description : "")
                                                elide: Text.ElideRight
                                                color: Theme.palette.subtleText
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSizeCaption
                                                Layout.fillWidth: true
                                            }
                                        }

                                        RowLayout {
                                            spacing: Theme.scaledGeometry(10)
                                            Layout.columnSpan: headerDetailsContent.width < Theme.scaledGeometry(600) ? 2 : 1
                                            Layout.alignment: Qt.AlignLeft | Qt.AlignVCenter

                                            Text {
                                                text: root.selected.enabled ? "Ativado" : "Desativado"
                                                color: root.selected.enabled ? Theme.palette.headingText : Theme.palette.mutedText
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSizeCaption
                                            }

                                            VrSwitch {
                                                id: headerEnabledSwitch
                                                objectName: "providerEnabledSwitch"
                                                subdued: true
                                                checked: !!root.selected.enabled
                                                enabled: !!root.selected.id
                                                Accessible.name: "Ativar " + (root.selected.name || "provedor")
                                                onToggled: {
                                                    studio.setProviderEnabled(root.selected.id, checked)
                                                    checked = Qt.binding(function() { return !!root.selected.enabled })
                                                }
                                            }

                                            VrProviderAction {
                                                objectName: "refreshProviderRuntimes"
                                                text: root.refreshing ? "Verificando\u2026" : "Verificar runtime"
                                                variant: "secondary"
                                                implicitHeight: Theme.scaledGeometry(32)
                                                enabled: !root.refreshing && !root.runtimeBusy
                                                Accessible.name: "Verificar os execut\u00e1veis instalados nesta m\u00e1quina"
                                                onClicked: {
                                                    root.refreshing = true
                                                    root.refreshFeedback = ""
                                                    refreshTimer.start()
                                                }
                                            }
                                        }
                                    }

                                    Text {
                                        visible: root.refreshFeedback.length > 0
                                        Layout.fillWidth: true
                                        text: root.refreshFeedback
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeCaption
                                        Accessible.name: text
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        height: 1
                                        color: Theme.palette.border
                                    }

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: headerDetailsContent.width < Theme.scaledGeometry(500) ? 1 : 2
                                        columnSpacing: Theme.spaceMd

                                        Text {
                                            text: "Nome de exibi\u00e7\u00e3o"
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeControl
                                            font.weight: Font.Medium
                                            Layout.preferredWidth: Theme.scaledGeometry(140)
                                        }

                                        VrTextField {
                                            id: providerDisplayName
                                            objectName: "providerDisplayName"
                                            Layout.fillWidth: true
                                            implicitHeight: Theme.scaledGeometry(34)
                                            text: root.selected.name || ""
                                            maximumLength: 80
                                            Accessible.name: "Nome de exibi\u00e7\u00e3o do provedor"
                                            background: Rectangle {
                                                radius: Theme.scaledGeometry(8)
                                                color: Theme.palette.codeSurface
                                                border.width: providerDisplayName.activeFocus ? 2 : 1
                                                border.color: providerDisplayName.activeFocus ? Theme.palette.focus : Theme.palette.border
                                            }
                                            onEditingFinished: {
                                                if (text.trim() && text.trim() !== root.selected.name)
                                                    studio.setProviderDisplayName(root.selected.id, text)
                                                text = Qt.binding(function() { return root.selected.name || "" })
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // ---------------- Section 1: Runtime
                        Text {
                            text: "Runtime"
                            Layout.leftMargin: Theme.scaledGeometry(16)
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeControl
                            font.weight: Font.Medium
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: runtimeStatusRow.implicitHeight + Theme.space2Xl

                                GridLayout {
                                    id: runtimeStatusRow
                                    columns: width < Theme.scaledGeometry(500) ? 1 : 2
                                    anchors.fill: parent
                                    anchors.margins: Theme.scaledGeometry(16)
                                    columnSpacing: Theme.scaledGeometry(12)

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        spacing: Theme.scaledGeometry(4)

                                        Text {
                                            text: "Estado da instala\u00e7\u00e3o"
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeControl
                                            font.weight: Font.DemiBold
                                        }

                                        Text {
                                            visible: !!root.selected.installVersion
                                            text: "Vers\u00e3o: " + (root.selected.installVersion || "")
                                            color: Theme.palette.mutedText
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeCaption
                                        }
                                    }

                                    VrProviderStatus {
                                        text: root.selected.runtimeState === "error" ? "Falha na instala\u00e7\u00e3o"
                                            : root.runtimeBusy ? root.status(root.selected).text
                                            : root.selected.available ? "Instalado nesta m\u00e1quina"
                                            : "CLI n\u00e3o encontrado"
                                        tone: root.selected.runtimeState === "error" ? "danger"
                                            : root.selected.available ? "success"
                                            : "warning"
                                        busy: root.runtimeBusy
                                    }
                                }

                                Rectangle {
                                    height: 1
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    color: Theme.palette.border
                                }
                            }

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: pathContentRow.implicitHeight + 24
                                visible: !!root.selected.command

                                RowLayout {
                                    id: pathContentRow
                                    anchors.fill: parent
                                    anchors.margins: Theme.scaledGeometry(16)
                                    spacing: Theme.scaledGeometry(12)

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        spacing: Theme.scaledGeometry(4)

                                        Text {
                                            text: "Caminho do execut\u00e1vel"
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeControl
                                            font.weight: Font.DemiBold
                                        }

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.scaledGeometry(8)
                                            HoverHandler { id: pathHover }

                                            Text {
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                text: root.selected.command || ""
                                                elide: Text.ElideMiddle
                                                color: Theme.palette.mutedText
                                                font.family: Theme.monospaceFontFamily
                                                font.pixelSize: Theme.monospaceFontSize(12)
                                                Accessible.name: "Caminho do execut\u00e1vel: " + text
                                            }

                                            VrIconButton {
                                                id: copyPath
                                                objectName: "copyProviderPath"
                                                implicitWidth: Theme.scaledGeometry(28)
                                                implicitHeight: Theme.scaledGeometry(28)
                                                iconSize: Theme.iconCompact
                                                iconKind: root.copied ? "check" : "copy"
                                                opacity: pathHover.hovered || hovered || activeFocus || root.copied ? 1 : 0.6
                                                Accessible.name: root.copied ? "Caminho copiado" : "Copiar caminho do execut\u00e1vel"
                                                onClicked: {
                                                    studio.copyText(root.selected.command)
                                                    root.copied = true
                                                    copyTimer.restart()
                                                }
                                            }
                                        }
                                    }
                                }

                                Rectangle {
                                    height: 1
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    color: Theme.palette.border
                                }
                            }

                            Item {
                                Layout.fillWidth: true
                                implicitHeight: installActionsCol.implicitHeight + 28

                                ColumnLayout {
                                    id: installActionsCol
                                    anchors.fill: parent
                                    anchors.margins: Theme.scaledGeometry(16)
                                    spacing: Theme.scaledGeometry(10)

                                    Text {
                                        visible: !root.selected.available && !root.runtimeBusy
                                        Layout.fillWidth: true
                                        text: "Instale o runtime para utilizar este provedor."
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeControl
                                        wrapMode: Text.WordWrap
                                    }

                                    Text {
                                        objectName: "providerInstallMessage"
                                        visible: !!root.selected.installMessage
                                        Layout.fillWidth: true
                                        text: root.selected.installMessage || ""
                                        textFormat: Text.PlainText
                                        wrapMode: Text.WrapAnywhere
                                        color: root.selected.runtimeState === "error" ? Theme.palette.danger : Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeCaption
                                        Accessible.name: text
                                    }

                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: Theme.scaledGeometry(8)

                                        VrProviderAction {
                                            objectName: "installProviderCli"
                                            visible: !!root.selected.installSupported
                                            enabled: !root.runtimeBusy && (!root.selected.available || root.selected.runtimeState === "error" || root.selected.runtimeState === "cancelled")
                                            text: root.runtimeBusy ? "Instalando CLI\u2026"
                                                : root.selected.available && (root.selected.runtimeState === "error" || root.selected.runtimeState === "cancelled") ? "Verificar CLI"
                                                : root.selected.available ? "CLI instalado"
                                                : root.selected.runtimeState === "error" ? "Tentar instalar novamente"
                                                : "Baixar e instalar CLI"
                                            variant: root.selected.available ? "secondary" : "primary"
                                            implicitHeight: Theme.scaledGeometry(32)
                                            onClicked: studio.installProviderCli(root.selected.id)
                                        }

                                        VrProviderAction {
                                            objectName: "cancelProviderInstall"
                                            visible: root.runtimeBusy && !!root.selected.installSupported
                                            text: "Cancelar"
                                            variant: "secondary"
                                            implicitHeight: Theme.scaledGeometry(32)
                                            onClicked: studio.cancelProviderInstall(root.selected.id)
                                        }

                                        VrProviderAction {
                                            visible: !!root.selected.installDocs
                                            text: "Instala\u00e7\u00e3o oficial \u2197"
                                            variant: "ghost"
                                            implicitHeight: Theme.scaledGeometry(32)
                                            onClicked: Qt.openUrlExternally(root.selected.installDocs)
                                        }
                                    }

                                    Text {
                                        visible: !!root.selected.installSupported
                                        Layout.fillWidth: true
                                        text: "Instala\u00e7\u00e3o oficial para seu usu\u00e1rio. Ap\u00f3s instalar, entre na sua conta para usar o provedor."
                                        color: Theme.palette.subtleText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeCaption
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }
                        }

                        // ---------------- Section 2: Autenticação e conta
                        Text {
                            text: "Autentica\u00e7\u00e3o e conta"
                            Layout.leftMargin: Theme.scaledGeometry(16)
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeControl
                            font.weight: Font.Medium
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            Item {
                                visible: root.selected.id === "codex" || root.selected.id === "claude"
                                Layout.fillWidth: true
                                implicitHeight: cliLoginContent.implicitHeight + 28

                                ColumnLayout {
                                    id: cliLoginContent
                                    anchors.fill: parent
                                    anchors.margins: Theme.scaledGeometry(16)
                                    spacing: Theme.scaledGeometry(12)

                                    Text {
                                        text: "Login via CLI oficial"
                                        color: Theme.palette.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeControl
                                        font.weight: Font.DemiBold
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Entre na conta pelo CLI oficial. O login abre em um terminal e as credenciais ficam sob controle do provedor."
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeControl
                                        wrapMode: Text.WordWrap
                                    }

                                    VrProviderAction {
                                        objectName: "providerCliLogin"
                                        text: "Entrar na conta"
                                        variant: "primary"
                                        implicitHeight: Theme.scaledGeometry(32)
                                        enabled: !!root.selected.available && !root.runtimeBusy
                                        onClicked: studio.openProviderLogin(root.selected.id)
                                    }
                                }
                            }

                            Item {
                                visible: root.google
                                Layout.fillWidth: true
                                implicitHeight: googleAuthContent.implicitHeight + 28

                                ColumnLayout {
                                    id: googleAuthContent
                                    anchors.fill: parent
                                    anchors.margins: Theme.scaledGeometry(16)
                                    spacing: Theme.scaledGeometry(12)

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: "Conta Google Antigravity"
                                            color: Theme.palette.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeControl
                                            font.weight: Font.DemiBold
                                            Layout.fillWidth: true
                                        }
                                        VrProviderStatus {
                                            objectName: "providerAccountStatus"
                                            text: root.validating ? "Validando conta\u2026"
                                                : root.isWaiting ? "Aguardando autoriza\u00e7\u00e3o no navegador\u2026"
                                                : root.isStarting ? "Iniciando autentica\u00e7\u00e3o\u2026"
                                                : root.isVerifying ? (root.account.indexOf("modelos") !== -1 ? "Carregando modelos\u2026" : "Verificando acesso\u2026")
                                                : (root.attemptState === "failed" && root.accountState === "authenticated") ? "Falha ao carregar modelos"
                                                : (root.accountState === "unauthenticated" || root.account.indexOf("Login necessário") !== -1) ? "Login necessário"
                                                : root.authError ? "Falha na valida\u00e7\u00e3o"
                                                : root.authenticated ? "Conta autenticada"
                                                : "Conta n\u00e3o verificada"
                                            tone: (root.validating || root.isWaiting || root.isStarting || root.isVerifying) ? "warning"
                                                : (root.attemptState === "failed" && root.accountState === "authenticated") ? "warning"
                                                : (root.accountState === "unauthenticated" || root.account.indexOf("Login necessário") !== -1) ? "warning"
                                                : root.authError ? "danger"
                                                : root.authenticated ? "success"
                                                : "muted"
                                            busy: root.validating || root.isStarting || root.isVerifying
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: root.isWaiting && !root.hasCallback ? (root.account + " " + root.expiresAt)
                                            : root.isWaiting && root.expiresAt ? ("Aguardando autoriza\u00e7\u00e3o no navegador. " + root.expiresAt + ". Abra o link para continuar.")
                                            : root.authError ? (root.selected.errorDetail || root.account)
                                            : root.authenticated ? root.account
                                            : root.loginPending ? "Aguarde a abertura do navegador para autorizar sua conta Google."
                                            : "Entre com sua conta Google no navegador. A mesma conta ser\u00e1 usada nos modelos e nas conversas do Studio."
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeControl
                                        wrapMode: Text.Wrap
                                    }

                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: Theme.scaledGeometry(8)

                                        VrProviderAction {
                                            objectName: "providerGoogleLogin"
                                            visible: !root.authenticated || root.loginPending
                                            text: root.openingLogin || root.isStarting || root.isVerifying ? "Abrindo login\u2026"
                                                : root.hasCallback ? "Abrir no navegador"
                                                : "Entrar com Google"
                                            variant: !root.authenticated && !root.loginPending && !root.authError ? "primary" : "secondary"
                                            implicitHeight: Theme.scaledGeometry(32)
                                            enabled: !!root.selected.available && !root.validating && !root.isStarting && !root.isVerifying && (!root.isWaiting || root.hasCallback) && !root.openingLogin && !root.runtimeBusy
                                            onClicked: {
                                                root.openingLogin = true
                                                loginTimer.start()
                                            }
                                        }

                                        VrProviderAction {
                                            visible: root.hasCallback
                                            text: "Copiar link"
                                            variant: "secondary"
                                            implicitHeight: Theme.scaledGeometry(32)
                                            enabled: Boolean(root.authUrl)
                                            onClicked: studio.copyText(root.authUrl)
                                        }

                                        VrProviderAction {
                                            visible: root.isWaiting || root.isStarting || root.isVerifying
                                            text: "Cancelar login"
                                            variant: "ghost"
                                            implicitHeight: Theme.scaledGeometry(32)
                                            onClicked: studio.cancelAntigravityLogin()
                                        }

                                        VrProviderAction {
                                            objectName: "validateGoogleAccount"
                                            visible: root.authenticated && !root.loginPending
                                            text: root.validating ? "Validando\u2026" : "Validar conex\u00e3o"
                                            variant: root.authError ? "primary" : "secondary"
                                            implicitHeight: Theme.scaledGeometry(32)
                                            enabled: !!root.selected.available && !root.validating && !root.isStarting && !root.isWaiting && !root.openingLogin && !root.runtimeBusy
                                            onClicked: studio.validateAntigravityAccount()
                                        }
                                        VrProviderAction {
                                            visible: root.authenticated
                                            text: "Trocar conta"
                                            variant: "ghost"
                                            implicitHeight: Theme.scaledGeometry(32)
                                            enabled: !!root.selected.available && !root.validating && !root.isStarting && !root.isWaiting && !root.openingLogin && !root.runtimeBusy
                                            onClicked: studio.reconnectAntigravityAccount()
                                        }
                                    }

                                    ColumnLayout {
                                        visible: root.hasCallback
                                        Layout.fillWidth: true
                                        spacing: Theme.scaledGeometry(6)

                                        Text {
                                            Layout.fillWidth: true
                                            text: "Retorno manual (se o redirecionamento local n\u00e3o concluir):"
                                            color: Theme.palette.subtleText
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeCaption
                                            wrapMode: Text.WordWrap
                                        }

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.scaledGeometry(8)

                                            VrTextField {
                                                id: manualCallbackField
                                                objectName: "manualCallbackField"
                                                Layout.fillWidth: true
                                                implicitHeight: Theme.scaledGeometry(36)
                                                placeholderText: "Cole a URL final (ex.: http://127.0.0.1:port/?code=...&state=...)"
                                                background: Rectangle {
                                                    radius: Theme.scaledGeometry(8)
                                                    color: Theme.palette.codeSurface
                                                    border.width: manualCallbackField.activeFocus ? 2 : 1
                                                    border.color: manualCallbackField.activeFocus ? Theme.palette.focus : Theme.palette.border
                                                }
                                                onAccepted: {
                                                    if (text.trim().length > 0) {
                                                        studio.submitAntigravityCallback(text.trim())
                                                        text = ""
                                                    }
                                                }
                                            }

                                            VrProviderAction {
                                                text: "Concluir retorno"
                                                variant: "secondary"
                                                implicitHeight: Theme.scaledGeometry(36)
                                                enabled: manualCallbackField.text.trim().length > 0
                                                onClicked: {
                                                    studio.submitAntigravityCallback(manualCallbackField.text.trim())
                                                    manualCallbackField.text = ""
                                                }
                                            }
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "A valida\u00e7\u00e3o confirma a conta e carrega os modelos, sem enviar uma mensagem."
                                        color: Theme.palette.subtleText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeCaption
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            Item {
                                visible: !root.google && root.selected.id !== "codex" && root.selected.id !== "claude"
                                Layout.fillWidth: true
                                implicitHeight: otherContent.implicitHeight + 28

                                ColumnLayout {
                                    id: otherContent
                                    anchors.fill: parent
                                    anchors.margins: Theme.scaledGeometry(16)
                                    spacing: Theme.scaledGeometry(8)

                                    Text {
                                        text: "Status da conta"
                                        color: Theme.palette.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeControl
                                        font.weight: Font.DemiBold
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: root.account || "Configura\u00e7\u00e3o padr\u00e3o do sistema."
                                        color: Theme.palette.mutedText
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeControl
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }
                        }

                        // ---------------- Section 3: Método de acesso
                        Text {
                            text: "M\u00e9todo de acesso"
                            Layout.leftMargin: Theme.scaledGeometry(16)
                            color: Theme.palette.text
                            opacity: 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeControl
                            font.weight: Font.Medium
                        }

                        AppearanceGroup {
                            Layout.fillWidth: true

                            AppearanceRow {
                                title: "M\u00e9todo"
                                description: root.google ? "Conta Google \u00b7 Antigravity" : (root.selected.description || "CLI local")
                                divider: true
                            }

                            AppearanceRow {
                                title: "Autentica\u00e7\u00e3o"
                                description: root.google ? "Navegador \u00b7 perfil exclusivo do Studio" : (root.account || "Credenciais do ambiente local")
                                divider: root.google
                            }

                            AppearanceRow {
                                visible: root.google
                                title: "Permiss\u00f5es"
                                description: "Herdadas da conversa. Sem chave de API. As solicita\u00e7\u00f5es de permiss\u00e3o aparecem na conversa."
                                divider: false
                            }
                        }

                        Item { Layout.preferredHeight: Theme.scaledGeometry(16) }
                    }
                }
            }
        }
    }
}
