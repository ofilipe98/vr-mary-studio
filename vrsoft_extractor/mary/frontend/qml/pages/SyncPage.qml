import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

Item {
    Rectangle { anchors.fill: parent; color: frontend.palette.chatBackground }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pageMargin
        spacing: Theme.scaledGeometry(8)

        VrPageHeader {
            Layout.fillWidth: true
            title: "Sincronizações"
            subtitle: "A primeira sincronização pode demorar; as próximas usam revisão/hash."
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(54)
            color: "transparent"
            border.width: 0
            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(8)
                Text {
                    Layout.fillWidth: true
                    text: studio.syncRunning ? "Em andamento" : "Nenhuma execução"
                    color: frontend.palette.mutedText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeCaption
                }
                VrButton { text: "Sincronizar tudo"; variant: "primary"; enabled: !studio.syncRunning; onClicked: studio.runSync("all") }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.scaledGeometry(8)
            VrButton { Layout.fillWidth: true; text: "Sincronizar Wiki"; enabled: !studio.syncRunning; onClicked: studio.runSync("vrwiki") }
            VrButton { Layout.fillWidth: true; text: "Sincronizar Wiki Endoo"; enabled: !studio.syncRunning; onClicked: studio.runSync("endoo") }
            VrButton { Layout.fillWidth: true; text: "Sincronizar KB"; enabled: !studio.syncRunning; onClicked: confirmKb.open() }
            VrButton { Layout.fillWidth: true; text: "Indexar Schema selecionado"; enabled: !studio.syncRunning; onClicked: studio.runSync("schema") }
            VrButton { Layout.fillWidth: true; text: "Login/KB visível"; enabled: !studio.syncRunning; onClicked: studio.runSync("kb_visible") }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.scaledGeometry(10)
            Text { text: "Arquivo do Schema"; color: frontend.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl }
            VrTextField { Layout.fillWidth: true; text: studio.schemaPath; readOnly: true }
            VrButton { text: "Escolher arquivo…"; onClicked: studio.chooseSchemaFile() }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.scaledGeometry(28)
            radius: Theme.scaledGeometry(7)
            color: frontend.palette.chatSidebar
            Text {
                anchors.fill: parent
                anchors.leftMargin: Theme.scaledGeometry(12)
                text: studio.syncStatus
                color: frontend.palette.mutedText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeControl
                font.weight: Font.DemiBold
                verticalAlignment: Text.AlignVCenter
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "transparent"
            border.width: 0

            ListView {
                id: syncLogList
                objectName: "syncLogList"
                anchors.fill: parent
                anchors.margins: Theme.scaledGeometry(12)
                visible: count > 0
                clip: true
                reuseItems: true
                cacheBuffer: 240
                spacing: 2
                model: studio.syncLogModel
                property bool followTail: true
                delegate: TextEdit {
                    required property string lineText
                    width: syncLogList.width - 12
                    height: paintedHeight + 4
                    text: lineText
                    textFormat: TextEdit.PlainText
                    readOnly: true
                    activeFocusOnPress: false
                    selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    color: frontend.palette.text
                    font.family: Theme.monospaceFontFamily
                    font.pixelSize: Theme.monospaceFontSize(11)
                }
                ScrollBar.vertical: VrScrollBar { }
                onMovementStarted: followTail = atYEnd
                onMovementEnded: followTail = atYEnd
                onCountChanged: {
                    if (followTail)
                        Qt.callLater(function() { syncLogList.positionViewAtEnd() })
                }
            }

            VrMiddleAutoScroller {
                objectName: "syncAutoScroller"
                anchors.fill: syncLogList
                target: syncLogList
                enabled: syncLogList.visible
            }

            VrEmptyState {
                anchors.centerIn: parent
                visible: syncLogList.count === 0
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
        width: Math.min(parent.width - Theme.space2Xl, Theme.scaledGeometry(470))
        implicitHeight: confirmationContent.implicitHeight + topPadding + bottomPadding
        modal: true
        title: "Sincronizar o Movidesk KB?"
        header: null
        footer: null
        onAccepted: studio.runSync("kb")
        contentItem: ColumnLayout {
            id: confirmationContent
            spacing: Theme.spaceLg
            Text {
                Layout.fillWidth: true
                text: confirmKb.title
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.headingSize
                font.weight: Theme.weightDemiBold
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: "O Movidesk pode precisar encerrar uma sessão já aberta em outro navegador. Deseja continuar?"
                color: frontend.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.controlSize
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                VrButton { text: "Cancelar"; onClicked: confirmKb.reject() }
                VrButton { text: "Sincronizar"; variant: "primary"; onClicked: confirmKb.accept() }
            }
        }
        background: Rectangle { color: frontend.palette.surface; border.width: 1; border.color: frontend.palette.border; radius: Theme.radiusPopup }
    }
}
