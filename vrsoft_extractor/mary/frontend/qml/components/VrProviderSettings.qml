pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root
    objectName: "providerSettings"
    property string selectedProvider: "antigravity"
    property bool refreshing: false
    property bool openingLogin: false
    property string refreshFeedback: ""
    property bool copied: false
    readonly property bool narrow: width < 720
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
    readonly property string authUrl: String(selected.authUrl || "")
    readonly property string expiresAt: String(selected.expiresAt || "")
    readonly property bool isWaiting: Boolean(selected.isWaiting)
    readonly property bool isVerifying: Boolean(selected.isVerifying)
    readonly property bool isStarting: Boolean(selected.isStarting)
    readonly property bool hasCallback: isWaiting && authUrl.length > 0
    readonly property bool validating: isVerifying || account.indexOf("Validando") === 0
    readonly property bool authenticated: accountState === "authenticated" || account.indexOf("Conta Google validada") === 0
    readonly property bool loginPending: isWaiting || isStarting || account.indexOf("Conclua o login") === 0
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
        if (!p.enabled) return {text: "Desativado", tone: "muted"}
        if (!p.available) return {text: "Não instalado", tone: "warning"}
        if (p.id !== "antigravity") return {text: "CLI instalado", tone: "success"}
        var a = String(p.accountStatus || "")
        if (p.isVerifying || a.indexOf("Validando") === 0) return {text: "Validando conta…", tone: "muted", busy: true}
        if (p.isWaiting || p.isStarting || a.indexOf("Conclua o login") === 0) return {text: "Login em andamento", tone: "warning"}
        if (p.accountState === "authenticated" || a.indexOf("Conta Google validada") === 0) return {text: "Conta autenticada", tone: "success"}
        if (p.attemptState === "idle" || p.attemptState === "cancelled") return {text: "Conta não verificada", tone: "warning"}
        if (!a || a.indexOf("Conta Google ainda") === 0) return {text: "Conta não verificada", tone: "warning"}
        return {text: "Falha na validação", tone: "danger"}
    }
    function selectProvider(id) {
        selectedProvider = id
        copied = false
        detailsScroll.contentItem.contentY = 0
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
        anchors.fill: parent; spacing: 12
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
            background: Rectangle { radius: Theme.radiusSmall; color: frontend.palette.codeSurface; border.width: providerCombo.activeFocus ? 2 : 1; border.color: providerCombo.activeFocus ? frontend.palette.focus : frontend.palette.chatBorder }
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            ColumnLayout {
                visible: !root.narrow
                Layout.preferredWidth: 248; Layout.fillHeight: true
                Layout.rightMargin: 12; spacing: 8
                RowLayout {
                    Layout.fillWidth: true; Layout.leftMargin: 12; Layout.rightMargin: 12; Layout.topMargin: 12
                    Text { Layout.fillWidth: true; text: "Provedores"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { text: studio.providerItems.length; color: frontend.palette.subtleText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                }
                ListView {
                    id: providerList; objectName: "providerSidebar"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 4
                    model: studio.providerItems
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: VrScrollBar {}
                    delegate: ItemDelegate {
                        id: providerRow
                        required property var modelData
                        required property int index
                        readonly property var stateInfo: root.status(modelData)
                        width: providerList.width; height: 68
                        padding: 12; spacing: 12
                        objectName: "providerRow_" + modelData.id
                        Accessible.name: modelData.name + ", " + stateInfo.text
                        Accessible.selected: root.selected.id === modelData.id
                        focusPolicy: Qt.StrongFocus
                        onClicked: { forceActiveFocus(); root.selectProvider(modelData.id) }
                        Keys.onDownPressed: root.moveProvider(1)
                        Keys.onUpPressed: root.moveProvider(-1)
                        background: Rectangle {
                            radius: Theme.radiusSmall
                            color: root.selected.id === providerRow.modelData.id ? frontend.palette.codeHeader
                                : providerRow.hovered ? frontend.palette.codeSurface : "transparent"
                            border.width: providerRow.activeFocus ? 1 : 0; border.color: frontend.palette.focus
                            Rectangle {
                                visible: root.selected.id === providerRow.modelData.id
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                width: 2; height: 24; radius: 1; color: frontend.palette.subtleText
                            }
                            Behavior on color { enabled: !frontend.reduceMotion; ColorAnimation { duration: Theme.fastDuration } }
                        }
                        contentItem: RowLayout {
                            spacing: 12
                            Item { Layout.preferredWidth: 28; Layout.preferredHeight: 28
                                VrProviderIcon { anchors.centerIn: parent; width: 20; height: 20; provider: providerRow.modelData.id }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 4
                                Text { Layout.fillWidth: true; text: providerRow.modelData.name; elide: Text.ElideRight; color: frontend.palette.headingText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: root.selected.id === providerRow.modelData.id ? Font.DemiBold : Font.Medium }
                                VrProviderStatus { Layout.fillWidth: true; text: providerRow.stateInfo.text; tone: providerRow.stateInfo.tone; busy: !!providerRow.stateInfo.busy }
                            }
                        }
                    }
                }
            }
            Rectangle { visible: !root.narrow; Layout.fillHeight: true; Layout.preferredWidth: 1; color: frontend.palette.chatDivider }
            ScrollView {
                id: detailsScroll; objectName: "providerDetailsScroll"
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.minimumWidth: 0
                contentWidth: availableWidth; clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ColumnLayout {
                    width: detailsScroll.availableWidth
                    spacing: 20
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: root.narrow ? 4 : 24
                        Layout.rightMargin: root.narrow ? 8 : 24
                        Layout.topMargin: 12; Layout.bottomMargin: 24
                        spacing: 16
                        GridLayout {
                            columns: root.width < 500 ? 1 : 3
                            Layout.fillWidth: true; columnSpacing: 12; rowSpacing: 12
                            Item { visible: root.width >= 500; Layout.preferredWidth: 32; Layout.preferredHeight: 32; Layout.alignment: Qt.AlignTop
                                VrProviderIcon { anchors.centerIn: parent; width: 22; height: 22; provider: root.selected.id || "codex" }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 4
                                Text { Layout.fillWidth: true; text: root.selected.name || "Selecione um provedor"; elide: Text.ElideRight; color: frontend.palette.headingText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(18); font.weight: Font.DemiBold }
                                Text { Layout.fillWidth: true; text: root.providerLabel(root.selected); elide: Text.ElideRight; color: frontend.palette.subtleText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                                VrProviderStatus { objectName: "providerHeaderStatus"; announceChanges: true; Layout.fillWidth: true; Layout.topMargin: 4; text: root.status(root.selected).text; tone: root.status(root.selected).tone; busy: !!root.status(root.selected).busy }
                            }
                            ColumnLayout {
                                Layout.alignment: root.width < 500 ? Qt.AlignLeft : Qt.AlignTop | Qt.AlignRight; spacing: 8
                                RowLayout {
                                    Layout.alignment: root.width < 500 ? Qt.AlignLeft : Qt.AlignRight; spacing: 8
                                    Text { text: root.selected.enabled ? "Ativado" : "Desativado"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                                    VrSwitch {
                                        objectName: "providerEnabledSwitch"; subdued: true
                                        checked: !!root.selected.enabled
                                        enabled: !!root.selected.id
                                        Accessible.name: "Ativar " + (root.selected.name || "provedor")
                                        ToolTip.text: "Disponível para novas conversas"; ToolTip.visible: hovered || activeFocus; ToolTip.delay: 600
                                        onToggled: { studio.setProviderEnabled(root.selected.id, checked); checked = Qt.binding(function() { return !!root.selected.enabled }) }
                                    }
                                }
                                VrProviderAction {
                                    objectName: "refreshProviderRuntimes"
                                    text: root.refreshing ? "Verificando…" : "Verificar runtime"
                                    enabled: !root.refreshing && !root.runtimeBusy
                                    ToolTip.text: "Verificar os executáveis instalados nesta máquina"; ToolTip.visible: hovered || activeFocus; ToolTip.delay: 600
                                    onClicked: { root.refreshing = true; root.refreshFeedback = ""; refreshTimer.start() }
                                }
                            }
                        }
                        Text { visible: root.refreshFeedback.length > 0; Layout.fillWidth: true; text: root.refreshFeedback; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); Accessible.name: text }
                        GridLayout {
                            Layout.fillWidth: true; columns: root.width < 500 ? 1 : 2; columnSpacing: 24; rowSpacing: 8
                            Text { text: "Nome de exibição"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13) }
                            VrTextField {
                                objectName: "providerDisplayName"; Layout.fillWidth: true; Layout.minimumWidth: 40; implicitHeight: 38
                                text: root.selected.name || ""; maximumLength: 80
                                Accessible.name: "Nome de exibição do provedor"
                                onEditingFinished: {
                                    if (text.trim() && text.trim() !== root.selected.name)
                                        studio.setProviderDisplayName(root.selected.id, text)
                                    text = Qt.binding(function() { return root.selected.name || "" })
                                }
                                background: Rectangle { radius: Theme.radiusSmall; color: frontend.palette.codeSurface; border.width: parent.activeFocus ? 2 : 1; border.color: parent.activeFocus ? frontend.palette.focus : frontend.palette.chatBorder }
                            }
                        }
                        VrProviderSection {
                            Layout.fillWidth: true; title: "Runtime"
                            VrProviderStatus { Layout.fillWidth: true; text: root.runtimeBusy ? root.status(root.selected).text : root.selected.available ? "Instalado nesta máquina" : "CLI não encontrado"; tone: root.selected.available ? "success" : "warning"; busy: root.runtimeBusy }
                            RowLayout {
                                id: pathRow; Layout.fillWidth: true; visible: !!root.selected.command; spacing: 8
                                HoverHandler { id: pathHover }
                                Text {
                                    Layout.fillWidth: true; Layout.minimumWidth: 0
                                    text: root.selected.command || ""; elide: Text.ElideMiddle
                                    color: frontend.palette.subtleText; font.family: Theme.monospaceFontFamily; font.pixelSize: Theme.monospaceFontSize(12)
                                    Accessible.name: "Caminho do executável: " + text
                                    ToolTip.text: text; ToolTip.visible: truncated && (pathHover.hovered || copyPath.activeFocus); ToolTip.delay: 500
                                }
                                VrIconButton {
                                    id: copyPath; objectName: "copyProviderPath"
                                    implicitWidth: 28; implicitHeight: 28; iconSize: 14
                                    iconKind: root.copied ? "check" : "copy"
                                    opacity: pathHover.hovered || hovered || activeFocus || root.copied ? 1 : 0.45
                                    Accessible.name: root.copied ? "Caminho copiado" : "Copiar caminho do executável"
                                    ToolTip.text: Accessible.name; ToolTip.visible: hovered || activeFocus
                                    onClicked: { studio.copyText(root.selected.command); root.copied = true; copyTimer.restart() }
                                }
                            }
                            Text { visible: !root.selected.available && !root.runtimeBusy; Layout.fillWidth: true; text: "Instale o runtime para utilizar este provedor."; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); wrapMode: Text.WordWrap }
                            VrProviderAction {
                                visible: root.google; enabled: !root.runtimeBusy
                                text: root.selected.available ? "Instalação oficial ↗" : "Abrir instalação oficial ↗"
                                variant: root.selected.available ? "secondary" : "primary"
                                onClicked: Qt.openUrlExternally("https://antigravity.google/docs/cli/install/")
                            }
                        }
                        VrProviderSection {
                            visible: root.google; Layout.fillWidth: true; title: "Conta Google"
                            VrProviderStatus {
                                objectName: "providerAccountStatus"; Layout.fillWidth: true
                                text: root.validating ? "Validando conta…" : root.isWaiting ? "Aguardando autorização no navegador…" : root.authenticated ? "Conta validada" : root.authError ? "Falha na validação" : root.loginPending ? "Conclua o login no CLI" : "Conta não verificada"
                                tone: root.authenticated ? "success" : root.authError ? "danger" : (root.validating || root.isWaiting) ? "warning" : "muted"
                                busy: root.validating || root.isStarting
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.isWaiting && !root.hasCallback ? (root.account + " " + root.expiresAt)
                                    : root.isWaiting && root.expiresAt ? ("Aguardando autorização no navegador. " + root.expiresAt + ". Abra o link para continuar.")
                                    : root.authError ? (root.selected.errorDetail || root.account)
                                    : root.authenticated ? root.account
                                    : root.loginPending ? "Conclua a autenticação no navegador e valide a conta para confirmar a conexão."
                                    : "Entre com sua conta Google pelo CLI ou valide uma sessão existente. O login é gerenciado pelo Antigravity."
                                color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); wrapMode: Text.Wrap
                            }
                            Flow {
                                Layout.fillWidth: true; spacing: 8
                                VrProviderAction {
                                    objectName: "providerGoogleLogin"
                                    text: root.openingLogin || root.isStarting ? "Abrindo login…" : root.hasCallback ? "Abrir no navegador" : root.isWaiting ? "Login aberto no CLI" : root.authenticated ? "Abrir login" : "Entrar com Google"
                                    variant: !root.authenticated && !root.loginPending && !root.authError ? "primary" : "secondary"
                                    enabled: !!root.selected.available && !root.validating && !root.isStarting && (!root.isWaiting || root.hasCallback) && !root.openingLogin && !root.runtimeBusy
                                    onClicked: {
                                        root.openingLogin = true
                                        loginTimer.start()
                                    }
                                }
                                VrProviderAction {
                                    visible: root.hasCallback
                                    text: "Copiar link"
                                    variant: "secondary"
                                    enabled: Boolean(root.authUrl)
                                    onClicked: studio.copyText(root.authUrl)
                                }
                                VrProviderAction {
                                    visible: root.isWaiting || root.isStarting || root.isVerifying
                                    text: "Cancelar login"
                                    variant: "ghost"
                                    onClicked: studio.cancelAntigravityLogin()
                                }
                                VrProviderAction {
                                    objectName: "validateGoogleAccount"
                                    text: root.validating ? "Validando…" : root.authError ? "Tentar novamente" : root.authenticated ? "Validar conexão" : "Validar conta"
                                    variant: root.authError || root.loginPending ? "primary" : "secondary"
                                    enabled: !!root.selected.available && !root.validating && !root.openingLogin && !root.runtimeBusy
                                    onClicked: studio.validateAntigravityAccount()
                                }
                            }
                            ColumnLayout {
                                visible: root.hasCallback
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    Layout.fillWidth: true
                                    text: "Retorno manual (se o redirecionamento local não concluir):"
                                    color: frontend.palette.subtleText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    wrapMode: Text.WordWrap
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    VrTextField {
                                        id: manualCallbackField
                                        Layout.fillWidth: true
                                        implicitHeight: 36
                                        placeholderText: "Cole a URL final (ex.: http://127.0.0.1:port/?code=...&state=...)"
                                        background: Rectangle { radius: Theme.radiusSmall; color: frontend.palette.codeSurface; border.width: parent.activeFocus ? 2 : 1; border.color: parent.activeFocus ? frontend.palette.focus : frontend.palette.chatBorder }
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
                                        enabled: manualCallbackField.text.trim().length > 0
                                        onClicked: {
                                            studio.submitAntigravityCallback(manualCallbackField.text.trim())
                                            manualCallbackField.text = ""
                                        }
                                    }
                                }
                            }
                            Text { Layout.fillWidth: true; text: "A validação envia uma mensagem curta e utiliza a cota da conta."; color: frontend.palette.subtleText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); wrapMode: Text.WordWrap }
                        }
                        VrProviderSection {
                            Layout.fillWidth: true; title: "Método de acesso"
                            GridLayout {
                                Layout.fillWidth: true; columns: 2; columnSpacing: 24; rowSpacing: 8
                                Text { text: "Método"; color: frontend.palette.subtleText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                                Text { Layout.fillWidth: true; text: root.google ? "Conta Google · Antigravity CLI" : root.selected.description || ""; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); wrapMode: Text.WordWrap }
                                Text { text: "Autenticação"; color: frontend.palette.subtleText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                                Text { Layout.fillWidth: true; text: root.google ? "Navegador · sessão no cofre do sistema" : root.account; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); wrapMode: Text.WordWrap }
                                Text { visible: root.google; text: "Permissões"; color: frontend.palette.subtleText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                                Text { visible: root.google; Layout.fillWidth: true; text: "Herdadas da conversa"; color: frontend.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); wrapMode: Text.WordWrap }
                            }
                            Text { visible: root.google; Layout.fillWidth: true; text: "Sem chave de API no Studio. Ações que exigem confirmação no CLI podem ser recusadas no modo integrado."; color: frontend.palette.subtleText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); wrapMode: Text.WordWrap }
                        }
                    }
                }
            }
        }
    }
}
