import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    id: root

    property bool showToggle: true
    property color primaryColor: Theme.palette.text
    property color toggleColor: Theme.palette.mutedText
    signal toggleRequested()
    signal brandActivated()

    implicitHeight: 32

    RowLayout {
        anchors.fill: parent
        spacing: 6

        VrIconButton {
            id: toggleBtn
            objectName: "brandHeaderToggle"
            visible: root.showToggle
            implicitWidth: 28
            implicitHeight: 28
            iconKind: "panelLeft"
            iconSize: Theme.iconSmall
            foreground: root.toggleColor
            Accessible.name: "Voltar para o Chat VR"
            onClicked: {
                root.toggleRequested()
            }
        }

        Text {
            id: brandTitle
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            text: (typeof frontend !== "undefined" && frontend && frontend.appName) ? frontend.appName : "VR Norte Studio"
            color: root.primaryColor
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(14)
            font.weight: Font.DemiBold
            renderType: Theme.textRenderType
            elide: Text.ElideRight

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.brandActivated()
            }
        }
    }
}
