import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

ComboBox {
    id: control

    property string popupObjectName: ""
    property bool showSettingsAction: false
    property string settingsPathRole: "path"
    signal itemSettingsRequested(int index)

    implicitHeight: Theme.controlHeight
    leftPadding: 13
    rightPadding: 34
    focusPolicy: Qt.StrongFocus
    font.family: Theme.fontFamily
    font.pixelSize: Theme.bodySize

    contentItem: Text {
        leftPadding: 0
        rightPadding: 0
        text: control.displayText
        color: frontend.palette.text
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
    }

    indicator: Text {
        x: control.width - width - 13
        y: (control.height - height) / 2 - 1
        text: "▾"
        color: frontend.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: 14
    }

    background: Rectangle {
        radius: Theme.radiusControl
        color: control.hovered ? frontend.palette.hover : frontend.palette.surfaceRaised
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? frontend.palette.focus : frontend.palette.border
    }

    delegate: ItemDelegate {
        id: optionDelegate
        required property int index
        required property var modelData

        width: ListView.view ? ListView.view.width : control.width
        height: 40
        highlighted: control.highlightedIndex === index

        contentItem: RowLayout {
            spacing: 8
            VrLineIcon {
                visible: control.showSettingsAction
                Layout.preferredWidth: visible ? 15 : 0
                Layout.preferredHeight: 15
                kind: "folder"
                foreground: frontend.palette.mutedText
            }
            Text {
                Layout.fillWidth: true
                text: control.textRole ? optionDelegate.modelData[control.textRole]
                    : optionDelegate.modelData
                color: frontend.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideMiddle
            }
            Item {
                id: settingsAction
                objectName: "projectSettingsButton"
                visible: control.showSettingsAction
                    && String(optionDelegate.modelData[control.settingsPathRole] || "").length > 0
                Layout.preferredWidth: visible ? 28 : 0
                Layout.preferredHeight: 28
                VrLineIcon {
                    anchors.centerIn: parent
                    width: 15
                    height: 15
                    kind: "settings"
                    foreground: settingsMouse.containsMouse
                        ? frontend.palette.text : frontend.palette.mutedText
                }
                ToolTip.visible: settingsMouse.containsMouse
                ToolTip.text: "Configurar pasta"
                MouseArea {
                    id: settingsMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    preventStealing: true
                    onClicked: {
                        control.popup.close()
                        control.itemSettingsRequested(optionDelegate.index)
                    }
                }
            }
        }
        background: Rectangle {
            radius: 8
            color: parent.highlighted ? frontend.palette.selection : frontend.palette.surface
        }
    }

    popup: Popup {
        objectName: control.popupObjectName
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 12, 320)
        padding: 6

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            spacing: 2
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }

        background: Rectangle {
            color: frontend.palette.surface
            border.width: 1
            border.color: frontend.palette.border
            radius: Theme.radiusPopup
        }
    }
}
