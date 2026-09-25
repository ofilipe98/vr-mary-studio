import QtQuick
import QtQuick.Layouts
import "../../theme"

ColumnLayout {
    spacing: Theme.scaledGeometry(36)
    ColumnLayout {
        Layout.fillWidth: true; spacing: Theme.scaledGeometry(14)
        Text { text: "Interface"; Layout.leftMargin: Theme.scaledGeometry(16); color: Theme.palette.text; opacity: 0.7; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl }
        AppearanceGroup {
            Layout.fillWidth: true
            AppearanceRow {
                title: "Contraste"; description: "Ajuste o contraste das cores e bordas da interface."
                resetKey: "contrast"; resetVisible: frontend.appearanceContrast !== 100
                AppearanceRange {
                    settingName: "contrast"; from: 50; to: 200; stepSize: 5
                    value: frontend.appearanceContrast; onMoved: value => frontend.setAppearanceContrast(value)
                }
            }
            AppearanceRow {
                title: "Opacidade do vidro"; description: "Valores maiores deixam menus, janelas e a caixa de mensagem mais opacos."
                resetKey: "glass"; resetVisible: frontend.glassOpacity !== 80
                AppearanceRange {
                    settingName: "glass"; from: 40; to: 100; stepSize: 5
                    value: frontend.glassOpacity; onMoved: value => frontend.setGlassOpacity(value)
                }
            }
            AppearanceRow {
                title: "Identificação do ambiente"; description: "Escolha como identificar os ambientes Dev e Nightly."
                resetKey: "environment"; resetVisible: frontend.environmentIdentification !== "artwork"; divider: false
                AppearanceCombo {
                    objectName: "environmentIdentificationCombo"
                    model: ["Destaque no logo", "Nenhuma"]
                    readonly property var values: ["artwork", "none"]
                    currentIndex: values.indexOf(frontend.environmentIdentification)
                    onActivated: index => frontend.setEnvironmentIdentification(values[index])
                }
            }
        }
    }
    ColumnLayout {
        Layout.fillWidth: true; spacing: Theme.scaledGeometry(14)
        Text { text: "Movimento"; Layout.leftMargin: Theme.scaledGeometry(16); color: Theme.palette.text; opacity: 0.7; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl }
        AppearanceGroup {
            Layout.fillWidth: true
            AppearanceRow {
                id: motionRow
                title: "Animações dos painéis"; description: "Defina a velocidade de abertura e fechamento dos painéis."
                resetKey: "motion"; resetVisible: frontend.rawPanelAnimationDurationMs !== 0; divider: false
                PanelAnimationsPreview { Layout.preferredWidth: motionRow.compact ? 80 : 112; Layout.rightMargin: Theme.scaledGeometry(8) }
                AppearanceRange {
                    settingName: "motion"; from: 0; to: 400; stepSize: 25; suffix: " ms"
                    value: frontend.rawPanelAnimationDurationMs; onMoved: value => frontend.setPanelAnimationDurationMs(value)
                }
            }
        }
    }
}
