import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    Rectangle { anchors.fill: parent; color: frontend.palette.background }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: 8

        VrPageHeader {
            Layout.fillWidth: true
            title: "Sincronizações"
            subtitle: "A primeira sincronização pode demorar; as próximas usam revisão/hash."
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 54
            radius: Theme.radiusCard
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border
            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                Text {
                    Layout.fillWidth: true
                    text: studio.syncRunning ? "Em andamento" : "Nenhuma execução"
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(11)
                }
                VrButton { text: "Sincronizar tudo"; variant: "primary"; enabled: !studio.syncRunning; onClicked: studio.runSync("all") }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            VrButton { Layout.fillWidth: true; text: "Sincronizar Wiki"; enabled: !studio.syncRunning; onClicked: studio.runSync("vrwiki") }
            VrButton { Layout.fillWidth: true; text: "Sincronizar Wiki Endoo"; enabled: !studio.syncRunning; onClicked: studio.runSync("endoo") }
            VrButton { Layout.fillWidth: true; text: "Sincronizar KB"; enabled: !studio.syncRunning; onClicked: confirmKb.open() }
            VrButton { Layout.fillWidth: true; text: "Indexar Schema selecionado"; enabled: !studio.syncRunning; onClicked: studio.runSync("schema") }
            VrButton { Layout.fillWidth: true; text: "Login/KB visível"; enabled: !studio.syncRunning; onClicked: studio.runSync("kb_visible") }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Text { text: "Arquivo do Schema"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13) }
            VrTextField { Layout.fillWidth: true; text: studio.schemaPath; readOnly: true }
            VrButton { text: "Escolher arquivo…"; onClicked: studio.chooseSchemaFile() }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            radius: 7
            color: frontend.palette.surfaceRaised
            Text {
                anchors.fill: parent
                anchors.leftMargin: 12
                text: studio.syncStatus
                color: frontend.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
                font.weight: Font.DemiBold
                verticalAlignment: Text.AlignVCenter
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: frontend.palette.surface
            radius: Theme.radiusCard
            border.width: 1
            border.color: frontend.palette.border

            ScrollView {
                anchors.fill: parent
                anchors.margins: 12
                visible: studio.syncLog.length > 0
                TextArea {
                    width: parent.width
                    text: studio.syncLog
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextArea.Wrap
                    color: frontend.palette.text
                    background: Item { }
                    font.family: "Cascadia Mono"
                    font.pixelSize: Theme.fontSize(12)
                }
            }

            VrEmptyState {
                anchors.centerIn: parent
                visible: studio.syncLog.length === 0
                title: studio.syncRunning ? "Sincronizando fontes…" : "Nenhuma sincronização nesta sessão"
                description: studio.syncRunning ? "O progresso aparecerá aqui." : "Escolha uma fonte ou sincronize tudo"
                actionText: studio.syncRunning ? "" : "Sincronizar tudo"
                onAction: studio.runSync("all")
            }
        }
    }

    Dialog {
        id: confirmKb
        anchors.centerIn: parent
        width: 470
        modal: true
        title: "Sincronizar o Movidesk KB?"
        standardButtons: Dialog.Yes | Dialog.No
        onAccepted: studio.runSync("kb")
        contentItem: Text {
            text: "O Movidesk pode precisar encerrar uma sessão já aberta em outro navegador. Deseja continuar?"
            color: frontend.palette.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            wrapMode: Text.WordWrap
        }
        background: Rectangle { color: frontend.palette.surface; border.width: 1; border.color: frontend.palette.border; radius: Theme.radiusPopup }
    }
}
