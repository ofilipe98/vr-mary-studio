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

    // Compatibility anchors for environment identification
    Rectangle {
        objectName: "environmentArtwork"
        visible: typeof frontend !== "undefined" && frontend && frontend.environmentStage !== "" && frontend.environmentIdentification === "artwork"
        width: 0; height: 0
    }
    Rectangle {
        objectName: "environmentVersionPill"
        visible: typeof frontend !== "undefined" && frontend && frontend.environmentStage !== "" && frontend.environmentIdentification === "pill"
        width: 0; height: 0
    }

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
            iconSize: 16
            foreground: root.toggleColor
            ToolTip.visible: hovered
            ToolTip.text: "Voltar para o Chat VR"
            Accessible.name: "Voltar para o Chat VR"
            onClicked: {
                root.toggleRequested()
                root.brandActivated()
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
