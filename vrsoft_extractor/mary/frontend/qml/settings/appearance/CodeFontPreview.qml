import QtQuick
import QtQuick.Layouts
import "../../theme"
Rectangle {
    id: root
    Layout.fillWidth: true
    implicitHeight: 42 + lines.implicitHeight + 10
    color: Qt.tint(Theme.palette.background, Qt.alpha(Theme.palette.text,.055))
    readonly property string keyword: frontend.resolvedAppearance === "dark" ? "#ff477e" : "#a626a4"
    readonly property string functionColor: frontend.resolvedAppearance === "dark" ? "#a97cff" : "#6f42c1"
    readonly property string valueColor: frontend.resolvedAppearance === "dark" ? "#e7b77c" : "#986801"
    RowLayout {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: Theme.scaledGeometry(14); spacing: Theme.scaledGeometry(8)
        Text { text: "▣"; color: Theme.palette.focus; font.pixelSize: Theme.fontSizeBody }
        Text { text: "src/formatUser.ts"; color: Theme.palette.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeControl; Layout.fillWidth: true }
        Text { text: "-1"; color: Theme.palette.danger; font.family: frontend.codeFontFamily; font.pixelSize: Theme.fontSizeCaption }
        Text { text: "+1"; color: Theme.palette.success; font.family: frontend.codeFontFamily; font.pixelSize: Theme.fontSizeCaption }
    }
    ColumnLayout {
        id: lines
        anchors.top: parent.top; anchors.topMargin: Theme.scaledGeometry(44); anchors.left: parent.left; anchors.right: parent.right
        spacing: 0
        Repeater {
            model: [
                {n:"1",change:0,text:"<font color='"+root.keyword+"'>export function</font> <font color='"+root.functionColor+"'>formatUser</font>(user: <font color='"+root.functionColor+"'>User</font>) {"},
                {n:"2",change:-1,text:"  <font color='"+root.keyword+"'>return</font> user.name.<font color='"+root.functionColor+"'>toUpperCase</font>();"},
                {n:"2",change:1,text:"  <font color='"+root.keyword+"'>return</font> <font color='"+root.valueColor+"'>`&#36;{user.name} &lt;&#36;{user.email}&gt;`</font>; <font color='"+Theme.palette.mutedText+"'>// 0O 1lI</font>"},
                {n:"3",change:0,text:"}"}
            ]
            Rectangle {
                id: line
                required property var modelData
                Layout.fillWidth: true
                implicitHeight: Math.max(20,code.implicitHeight+2)
                color: modelData.change < 0 ? Qt.alpha(Theme.palette.danger,.19) : modelData.change > 0 ? Qt.alpha(Theme.palette.success,.19) : "transparent"
                Rectangle { width: Theme.scaledGeometry(3); height: parent.height; color: line.modelData.change < 0 ? Theme.palette.danger : Theme.palette.success; visible: line.modelData.change !== 0 }
                Text {
                    x: 14; y: 1; text: line.modelData.n
                    color: line.modelData.change < 0 ? Theme.palette.danger : line.modelData.change > 0 ? Theme.palette.success : Theme.palette.mutedText
                    font.family: frontend.codeFontFamily; font.pixelSize: Theme.monospaceFontSize(12)
                }
                Text {
                    id: code
                    objectName: "codeFontPreviewLine"
                    x: 38; y: 1; width: parent.width-46
                    text: line.modelData.text.replace(/ {2,}/g, spaces => "&nbsp;".repeat(spaces.length)); textFormat: Text.RichText
                    color: Theme.palette.text; font.family: frontend.codeFontFamily; font.pixelSize: Theme.monospaceFontSize(12)
                    wrapMode: frontend.wordWrap ? Text.WrapAnywhere : Text.NoWrap
                    clip: true
                }
            }
        }
    }
}
