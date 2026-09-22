import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"
ColumnLayout {
    spacing: Theme.scaledGeometry(14)
    RowLayout {
        Layout.fillWidth: true; Layout.leftMargin: Theme.scaledGeometry(16); Layout.rightMargin: Theme.scaledGeometry(16); spacing: Theme.scaledGeometry(8)
        Text { text: "Tipografia"; color: Theme.palette.text; opacity: .7; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); Layout.fillWidth: true }
        Text { text: "Avançado"; color: Theme.palette.mutedText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
        VrSwitch {
            thumbColor: Theme.palette.background
            inactiveColor: Theme.palette.controlBorder || Theme.palette.border
            objectName: "typographyAdvancedSwitch"
            checked: frontend.typographyAdvanced
            Accessible.name: "Mostrar opções avançadas de tipografia"
            onToggled: frontend.setTypographyAdvanced(checked)
        }
    }
    AppearanceGroup {
        Layout.fillWidth: true
        FontSetting {
            title: "Fonte da interface"; description: "Todo o texto fora dos blocos de código e do terminal."
            settingKey: "interfaceFont"; family: frontend.interfaceFontFamily; size: frontend.interfaceFontSize
            minSize: 11; maxSize: 22
            changed: family !== "Segoe UI" || size !== 16
            onTypographySelected: (family,size) => frontend.setInterfaceTypography(family,size)
            PromptFontPreview { visible: !frontend.typographyAdvanced }
        }
        FontSetting {
            objectName: "promptFontSetting"
            visible: frontend.typographyAdvanced
            title: "Fonte da mensagem"; description: "Apenas a caixa onde você escreve suas mensagens."
            settingKey: "promptFont"; family: frontend.promptFontFamily; size: frontend.promptFontSize
            minSize: 12; maxSize: 20
            changed: family !== frontend.interfaceFontFamily || size !== 14
            onTypographySelected: (family,size) => frontend.setPromptTypography(family,size)
            PromptFontPreview { }
        }
        FontSetting {
            title: frontend.typographyAdvanced ? "Fonte do código" : "Fonte monoespaçada"
            description: frontend.typographyAdvanced ? "Blocos de código, diferenças e prévias de arquivos." : "Blocos de código, diferenças, prévias de arquivos e terminal."
            settingKey: "codeFont"; family: frontend.codeFontFamily; size: frontend.codeFontSize
            minSize: 10; maxSize: 20; monospaceOnly: true
            changed: family !== "Consolas" || size !== 13
            onTypographySelected: (family,size) => frontend.setCodeTypography(family,size)
            CodeFontPreview { }
            TerminalFontPreview { visible: !frontend.typographyAdvanced }
        }
        FontSetting {
            objectName: "terminalFontSetting"
            visible: frontend.typographyAdvanced
            title: "Fonte do terminal"; description: "Texto do terminal, independente dos blocos de código e diferenças."
            settingKey: "terminalFont"; family: frontend.terminalFontFamily; size: frontend.terminalFontSize
            minSize: 8; maxSize: 20; monospaceOnly: true
            changed: family !== frontend.codeFontFamily || size !== 12
            onTypographySelected: (family,size) => frontend.setTerminalTypography(family,size)
            TerminalFontPreview { }
        }
        AppearanceRow {
            visible: frontend.typographyAdvanced && frontend.isMacOS
            title: "Suavização da fonte"; description: "Use uma suavização mais fina em tons de cinza."
            VrSwitch { thumbColor: Theme.palette.background; inactiveColor: Theme.palette.controlBorder || Theme.palette.border; checked: frontend.fontSmoothing; onToggled: frontend.setFontSmoothing(checked) }
        }
        AppearanceRow {
            visible: !frontend.isMacOS
            title: "Rasterização nativa"; description: "ClearType do Windows; desativado usa o rasterizador do Qt (texto mais uniforme, como no T3 Code)."
            resetKey: "textRendering"; resetVisible: frontend.textRenderingMode !== "qt"
            VrSwitch {
                objectName: "appearanceNativeRenderingSwitch"
                thumbColor: Theme.palette.background
                inactiveColor: Theme.palette.controlBorder || Theme.palette.border
                checked: frontend.textRenderingMode === "native"
                Accessible.name: "Rasterização nativa (ClearType)"
                onToggled: frontend.setTextRenderingMode(checked ? "native" : "qt")
            }
        }
        AppearanceRow {
            title: "Quebra de linha"; description: "Quebre linhas longas em códigos, tabelas, diferenças e prévias de arquivos."
            resetKey: "wordWrap"; resetVisible: !frontend.wordWrap; divider: false
            VrSwitch { objectName: "appearanceWordWrapSwitch"; thumbColor: Theme.palette.background; inactiveColor: Theme.palette.controlBorder || Theme.palette.border; checked: frontend.wordWrap; onToggled: frontend.setWordWrap(checked) }
        }
    }
}
