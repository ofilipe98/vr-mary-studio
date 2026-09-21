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

    implicitHeight: Theme.controlHeightCompact
    leftPadding: Theme.scaledGeometry(13)
    rightPadding: Theme.scaledGeometry(34)
    focusPolicy: Qt.StrongFocus
    font.family: Theme.fontFamily
    font.pixelSize: Theme.controlSize

    contentItem: Text {
        leftPadding: 0
        rightPadding: 0
        text: control.displayText
        color: Theme.palette.text
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
        renderType: Theme.textRenderType
    }

    indicator: Text {
        x: control.width - width - 13
        y: (control.height - height) / 2 - 1
        text: "▾"
        color: Theme.palette.mutedText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
        renderType: Theme.textRenderType
    }

    background: Rectangle {
        radius: Theme.radiusControl
        color: control.hovered ? Theme.palette.hover : Theme.palette.surfaceRaised
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.palette.focus : Theme.palette.border
    }

    delegate: ItemDelegate {
        id: optionDelegate
        required property int index
        required property var modelData

        width: ListView.view ? ListView.view.width : control.width
        height: control.showSettingsAction ? Theme.menuRowHeight : Theme.pickerRowHeight
        highlighted: control.highlightedIndex === index

        contentItem: RowLayout {
            spacing: Theme.scaledGeometry(8)
            VrLineIcon {
                visible: control.showSettingsAction
                Layout.preferredWidth: visible ? 14 : 0
                Layout.preferredHeight: Theme.scaledGeometry(14)
                kind: "folder"
                foreground: Theme.palette.mutedText
            }
            Text {
                Layout.fillWidth: true
                text: control.textRole ? optionDelegate.modelData[control.textRole]
                    : optionDelegate.modelData
                color: Theme.palette.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.controlSize
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideMiddle
                renderType: Theme.textRenderType
            }
            Item {
                id: settingsAction
                objectName: "projectSettingsButton"
                visible: control.showSettingsAction
                    && String(optionDelegate.modelData[control.settingsPathRole] || "").length > 0
                Layout.preferredWidth: visible ? 22 : 0
                Layout.preferredHeight: Theme.scaledGeometry(30)
                VrLineIcon {
                    anchors.centerIn: parent
                    width: Theme.scaledGeometry(14)
                    height: Theme.scaledGeometry(14)
                    kind: "settings"
                    foreground: settingsMouse.containsMouse
                        ? Theme.palette.text : Theme.palette.mutedText
                }
                Accessible.name: "Configurar pasta"
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
            color: parent.highlighted ? Theme.palette.selection : Theme.palette.surface
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
            color: Qt.alpha(Theme.palette.surface, Theme.glassOpacity)
            border.width: 1
            border.color: Theme.palette.border
            radius: Theme.radiusPopup
        }
    }
}
