import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

RowLayout {
    id: root
    property string text: ""
    property string tone: "muted"
    property bool busy: false
    property bool announceChanges: false
    onTextChanged: if (announceChanges && visible && text.length) Accessible.announce(text)
    readonly property color statusColor: tone === "success" ? Theme.palette.success
        : tone === "warning" ? Theme.palette.warning
        : tone === "danger" ? Theme.palette.danger : Theme.palette.subtleText
    spacing: Theme.scaledGeometry(8)
    Accessible.role: Accessible.StaticText
    Accessible.name: text
    Rectangle {
        Layout.preferredWidth: Theme.scaledGeometry(6); Layout.preferredHeight: Theme.scaledGeometry(6)
        radius: Theme.scaledGeometry(3); color: root.statusColor
        opacity: root.busy ? 0.5 : 0.85
        SequentialAnimation on opacity {
            running: root.busy && root.visible && !frontend.reduceMotion
            loops: Animation.Infinite
            NumberAnimation { to: 1; duration: 650 }
            NumberAnimation { to: 0.4; duration: 650 }
        }
    }
    Text {
        Layout.fillWidth: true
        text: root.text
        color: root.tone === "danger" ? root.statusColor : Theme.palette.mutedText
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeCaption
        elide: Text.ElideRight
    }
}
