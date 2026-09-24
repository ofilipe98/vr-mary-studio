import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    objectName: "decompiledSurfaceView"

    property var payload: ({})
    property var frontendBridge: null
    property bool showClean: true
    property bool copied: false

    readonly property string state: String(payload && payload.state || "")
    readonly property bool hasCode: state === "ready" && (displayedCode.length > 0)
    readonly property string rawBody: String(payload && payload.body || "")
    readonly property string cleanBody: String(payload && payload.clean_body || "")
    readonly property string displayedCode: (showClean && cleanBody.length > 0) ? cleanBody : rawBody
    readonly property int targetLine: (showClean && cleanBody.length > 0)
        ? Math.max(0, Number(payload && payload.clean_target_line || 0))
        : Math.max(0, Number(payload && payload.raw_target_line || 0))
    readonly property int lineCount: {
        var code = root.displayedCode
        if (!code || !code.length) return 0
        var count = 1
        for (var i = 0; i < code.length; ++i) {
            if (code[i] === "\n") count++
        }
        return count
    }
    readonly property string lineNumbersText: {
        var count = root.lineCount
        if (count <= 0) return ""
        var nums = []
        for (var i = 1; i <= count; ++i) {
            nums.push(i)
        }
        return nums.join("\n")
    }

    signal candidateSelected(string candidateReference)

    color: Theme.palette.background

    onPayloadChanged: {
        root.showClean = true
        Qt.callLater(root.scrollToTargetLine)
    }

    onShowCleanChanged: {
        Qt.callLater(root.scrollToTargetLine)
    }

    Timer {
        id: copyTimer
        interval: 1400
        onTriggered: root.copied = false
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Header
        Rectangle {
            id: header
            objectName: "decompiledCodeHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(52)
            color: Theme.palette.chatSidebar
            border.width: 1
            border.color: Theme.palette.chatBorder

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(10)
                anchors.rightMargin: Theme.scaledGeometry(10)
                spacing: Theme.scaledGeometry(8)

                VrLineIcon {
                    Layout.preferredWidth: Theme.iconSmall
                    Layout.preferredHeight: Theme.iconSmall
                    kind: "code"
                    foreground: Theme.palette.brandOrange
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 1

                    RowLayout {
                        spacing: Theme.scaledGeometry(6)
                        Text {
                            text: {
                                var title = String(root.payload && (root.payload.title || root.payload.qualified_name || root.payload.reference) || "Código")
                                var sym = String(root.payload && root.payload.target_symbol || "")
                                return sym.length > 0 ? (title + " · " + sym) : title
                            }
                            color: Theme.palette.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                            elide: Text.ElideMiddle
                            Layout.maximumWidth: header.width * 0.55
                        }

                        // Tool Badge
                        Rectangle {
                            visible: Boolean(root.payload && root.payload.tool)
                            radius: Theme.scaledGeometry(4)
                            color: Theme.palette.chatControl
                            implicitHeight: Theme.scaledGeometry(18)
                            implicitWidth: toolLabel.implicitWidth + 8
                            Text {
                                id: toolLabel
                                anchors.centerIn: parent
                                text: String(root.payload && root.payload.tool || "")
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeMicro
                            }
                        }

                        // Release Badge
                        Rectangle {
                            visible: Boolean(root.payload && root.payload.release_id)
                            radius: Theme.scaledGeometry(4)
                            color: Theme.palette.chatControl
                            implicitHeight: Theme.scaledGeometry(18)
                            implicitWidth: releaseLabel.implicitWidth + 8
                            Text {
                                id: releaseLabel
                                anchors.centerIn: parent
                                text: String(root.payload && root.payload.release_id || "")
                                color: Theme.palette.mutedText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeMicro
                            }
                        }

                        // Truncated Badge
                        Rectangle {
                            visible: Boolean(root.payload && root.payload.truncated)
                            radius: Theme.scaledGeometry(4)
                            color: Qt.alpha(Theme.palette.warning, 0.2)
                            implicitHeight: Theme.scaledGeometry(18)
                            implicitWidth: truncLabel.implicitWidth + 8
                            Text {
                                id: truncLabel
                                anchors.centerIn: parent
                                text: "Truncado"
                                color: Theme.palette.warning
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeMicro
                                font.weight: Font.DemiBold
                            }
                        }
                    }

                    Text {
                        text: String(root.payload && root.payload.package_name || "")
                        color: Theme.palette.mutedText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeMicro
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                        visible: text.length > 0
                    }
                }

                // Clean Toggle
                VrButton {
                    id: cleanToggle
                    objectName: "decompiledCleanToggle"
                    visible: root.hasCode && Boolean(root.payload && root.payload.clean_body && root.payload.clean_body.length > 0 && root.payload.clean_body !== root.payload.body)
                    text: root.showClean ? "Limpo" : "Original"
                    variant: root.showClean ? "primary" : "ghost"
                    implicitHeight: Theme.scaledGeometry(26)
                    onClicked: {
                        root.showClean = !root.showClean
                        Qt.callLater(root.scrollToTargetLine)
                    }
                }

                // Copy Button
                VrIconButton {
                    id: copyButton
                    objectName: "decompiledCopyButton"
                    visible: root.hasCode
                    implicitWidth: Theme.scaledGeometry(26)
                    implicitHeight: Theme.scaledGeometry(26)
                    iconSize: Theme.iconCompact
                    iconKind: root.copied ? "check" : "copy"
                    foreground: root.copied ? Theme.palette.success : Theme.palette.mutedText
                    Accessible.name: root.copied ? "Copiado!" : "Copiar código"
                    onClicked: {
                        if (typeof studio !== "undefined" && studio) {
                            studio.copyText(root.displayedCode)
                        }
                        root.copied = true
                        copyTimer.restart()
                    }
                }
            }
        }

        // Body area
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // Code View (when ready)
            Item {
                id: decompiledCodeArea
                anchors.fill: parent
                visible: root.hasCode

                RowLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Gutter with Line Numbers (pinned horizontally, syncs vertically)
                    Rectangle {
                        id: lineGutter
                        Layout.fillHeight: true
                        Layout.preferredWidth: Math.max(Theme.scaledGeometry(36), Theme.scaledGeometry(16 + String(root.lineCount).length * 8))
                        color: Theme.palette.chatSidebar
                        clip: true

                        Flickable {
                            id: gutterFlickable
                            anchors.fill: parent
                            contentY: decompiledCodeScroll.contentY
                            contentHeight: decompiledCodeScroll.contentHeight
                            interactive: false
                            boundsBehavior: Flickable.StopAtBounds

                            Text {
                                id: gutterText
                                width: lineGutter.width - Theme.scaledGeometry(8)
                                anchors.top: parent.top
                                anchors.topMargin: Theme.scaledGeometry(10)
                                horizontalAlignment: Text.AlignRight
                                text: root.lineNumbersText
                                color: Theme.palette.mutedText
                                font.family: Theme.monospaceFontFamily
                                font.pixelSize: Theme.monospaceFontSize(12)
                            }
                        }

                        Rectangle {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: 1
                            color: Theme.palette.chatBorder
                        }
                    }

                    // Code Editor (scrolls both horizontally and vertically)
                    Flickable {
                        id: decompiledCodeScroll
                        objectName: "decompiledCodeScroll"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        flickableDirection: Flickable.AutoFlickIfNeeded
                        ScrollBar.vertical: VrScrollBar { }
                        ScrollBar.horizontal: VrScrollBar { }

                        contentWidth: Math.max(width, codeBody.paintedWidth + 28)
                        contentHeight: Math.max(height, codeBody.paintedHeight + 20)

                        TextEdit {
                            id: codeBody
                            objectName: "decompiledCodeBody"
                            leftPadding: Theme.scaledGeometry(12)
                            rightPadding: Theme.scaledGeometry(14)
                            topPadding: Theme.scaledGeometry(10)
                            bottomPadding: Theme.scaledGeometry(10)
                            text: root.displayedCode
                            textFormat: TextEdit.PlainText
                            readOnly: true
                            selectByMouse: true
                            persistentSelection: true
                            activeFocusOnPress: true
                            renderType: Theme.textRenderType
                            wrapMode: TextEdit.NoWrap
                            color: Theme.palette.text
                            selectionColor: Theme.palette.selection
                            selectedTextColor: Theme.palette.text
                            font.family: Theme.monospaceFontFamily
                            font.pixelSize: Theme.monospaceFontSize(12)

                            // Subtle target line highlight bar
                            Rectangle {
                                id: lineHighlight
                                visible: root.targetLine > 0 && root.lineCount >= root.targetLine
                                anchors.left: parent.left
                                anchors.right: parent.right
                                y: codeBody.topPadding + (root.targetLine - 1) * (codeBody.contentHeight / Math.max(1, root.lineCount))
                                height: codeBody.contentHeight / Math.max(1, root.lineCount)
                                color: Qt.alpha(Theme.palette.brandOrange, 0.12)
                                border.width: 1
                                border.color: Qt.alpha(Theme.palette.brandOrange, 0.35)
                                z: -1
                            }

                            Component.onCompleted: {
                                if (typeof frontend !== "undefined" && frontend) {
                                    frontend.highlightCodeDocument(codeBody.textDocument, "java")
                                }
                            }

                            Connections {
                                target: typeof frontend !== "undefined" ? frontend : null
                                function onThemeChanged() {
                                    if (typeof frontend !== "undefined" && frontend) {
                                        frontend.highlightCodeDocument(codeBody.textDocument, "java")
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Ambiguous View (when multiple candidates found)
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(16)
                spacing: Theme.scaledGeometry(12)
                visible: root.state === "ambiguous"

                Text {
                    id: ambiguousNotice
                    objectName: "decompiledStatusNotice"
                    Layout.fillWidth: true
                    text: String(root.payload && root.payload.message || "Múltiplas classes encontradas. Selecione um candidato:")
                    color: Theme.palette.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }

                ListView {
                    id: candidateList
                    objectName: "decompiledAmbiguousList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: Theme.scaledGeometry(6)
                    model: (root.payload && root.payload.candidates) || []
                    ScrollBar.vertical: VrScrollBar { }

                    delegate: Rectangle {
                        id: candidateCard
                        required property var modelData
                        required property int index
                        width: candidateList.width
                        height: Theme.scaledGeometry(54)
                        radius: Theme.scaledGeometry(8)
                        color: candidateHover.hovered ? Theme.palette.chatControl : Theme.palette.chatSidebar
                        border.width: 1
                        border.color: Theme.palette.chatBorder

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.scaledGeometry(12)
                            anchors.rightMargin: Theme.scaledGeometry(12)
                            spacing: Theme.scaledGeometry(8)

                            VrLineIcon {
                                Layout.preferredWidth: Theme.iconCompact
                                Layout.preferredHeight: Theme.iconCompact
                                kind: "code"
                                foreground: Theme.palette.brandOrange
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    Layout.fillWidth: true
                                    text: {
                                        var c = candidateCard.modelData
                                        if (typeof c === "string") return c
                                        return String(c.canonical || c.qualified_name || c.reference || c.class_name || "")
                                    }
                                    color: Theme.palette.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideMiddle
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: {
                                        var c = candidateCard.modelData
                                        if (typeof c === "object" && c.package_name) return String(c.package_name)
                                        return ""
                                    }
                                    color: Theme.palette.mutedText
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeMicro
                                    elide: Text.ElideRight
                                    visible: text.length > 0
                                }
                            }

                            VrLineIcon {
                                Layout.preferredWidth: Theme.iconMicro
                                Layout.preferredHeight: Theme.iconMicro
                                kind: "chevronRight"
                                foreground: Theme.palette.mutedText
                            }
                        }

                        HoverHandler { id: candidateHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            onTapped: {
                                var c = candidateCard.modelData
                                var ref = ""
                                if (typeof c === "string") ref = c
                                else ref = String(c.canonical || c.qualified_name || c.reference || "")
                                if (ref.length > 0) {
                                    root.candidateSelected(ref)
                                    if (typeof chat !== "undefined" && chat) {
                                        chat.openDecompiledReference("vr-code:" + ref)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Not Found / Error / Empty View
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(parent.width - 32, Theme.scaledGeometry(360))
                spacing: Theme.scaledGeometry(10)
                visible: !root.hasCode && root.state !== "ambiguous"

                VrLineIcon {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: Theme.scaledGeometry(36)
                    Layout.preferredHeight: Theme.scaledGeometry(36)
                    kind: root.state === "error" ? "close" : "code"
                    foreground: root.state === "error" ? Theme.palette.danger : Theme.palette.mutedText
                }

                Text {
                    id: statusNotice
                    objectName: "decompiledStatusNotice"
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: {
                        if (root.state === "not_found")
                            return String(root.payload && root.payload.message || "Classe ou método não encontrado na release ativa.")
                        if (root.state === "error")
                            return String(root.payload && root.payload.message || "Erro ao carregar código descompilado.")
                        return "Clique em uma referência de código Java no chat para inspecionar aqui."
                    }
                    color: root.state === "error" ? Theme.palette.danger : Theme.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    lineHeight: Theme.bodyLineHeight
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    function scrollToTargetLine() {
        if (!decompiledCodeScroll || !codeBody) return
        var text = String(root.displayedCode || "")
        var line = Number(root.targetLine || 0)
        if (line <= 0 || !text.length) {
            decompiledCodeScroll.contentY = 0
            return
        }
        var lines = text.split("\n")
        var offset = 0
        for (var index = 0; index < Math.min(line - 1, lines.length); ++index) {
            offset += lines[index].length + 1
        }
        var lineText = lines[line - 1] !== undefined ? lines[line - 1] : ""
        if (codeBody.select) {
            codeBody.select(offset, offset + lineText.length)
        }
        if (codeBody.cursorPosition !== undefined) {
            codeBody.cursorPosition = offset
        }

        var areaHeight = codeBody.contentHeight
        var count = Math.max(1, root.lineCount)
        var lineHeight = areaHeight / count
        var scrollHeight = decompiledCodeScroll.height
        var maxY = Math.max(0, areaHeight - scrollHeight)
        var targetY = (line - 1) * lineHeight - scrollHeight * 0.35
        decompiledCodeScroll.contentY = Math.max(0, Math.min(targetY, maxY))
    }
}
