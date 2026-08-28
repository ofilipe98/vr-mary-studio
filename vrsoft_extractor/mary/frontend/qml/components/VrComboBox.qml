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
        font.pixelSize: Theme.fontSize(14)
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
        height: control.showSettingsAction ? 32 : 40
        highlighted: control.highlightedIndex === index

        contentItem: RowLayout {
            spacing: 8
            VrLineIcon {
                visible: control.showSettingsAction
                Layout.preferredWidth: visible ? 14 : 0
                Layout.preferredHeight: 14
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
                Layout.preferredWidth: visible ? 22 : 0
                Layout.preferredHeight: 30
                VrLineIcon {
                    anchors.centerIn: parent
                    width: 13
                    height: 13
                    kind: "settings"
                    strokeWidth: 1.55
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
            radius: control.showSettingsAction ? 6 : 8
            color: parent.highlighted ? frontend.palette.selection : frontend.palette.surface
        }
    }

    popup: Popup {
        objectName: control.popupObjectName
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        padding: control.showSettingsAction ? 4 : 6

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            spacing: control.showSettingsAction ? 1 : 2
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
