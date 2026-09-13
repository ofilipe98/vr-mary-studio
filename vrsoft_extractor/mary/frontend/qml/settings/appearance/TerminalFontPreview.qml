import QtQuick
import QtQuick.Layouts
import "../../theme"
Rectangle {
    Layout.fillWidth: true
    implicitHeight: terminal.implicitHeight + 24
    radius: 10
    color: Theme.palette.terminalBackground || Theme.palette.background
    border.color: Theme.palette.controlBorder || Theme.palette.border
    Text {
        id: terminal
        objectName: "terminalFontPreview"
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16
        font.family: frontend.terminalFontFamily; font.pixelSize: Theme.terminalFontSize(12)
        color: Theme.palette.text; textFormat: Text.RichText; lineHeight: 1.1
        wrapMode: frontend.wordWrap ? Text.WrapAnywhere : Text.NoWrap; clip: true
        text: ("<font color='"+Theme.palette.warning+"'>VITE v7.1.1</font>  pronto em <b>1.24s</b><br/><br/>"+
              "<font color='"+Theme.palette.warning+"'>➜</font>  Local:    <u><font color='"+Theme.palette.link+"'>http://127.0.0.1:5173/</font></u><br/>"+
              "<font color='"+Theme.palette.warning+"'>➜</font>  Rede:  <u><font color='"+Theme.palette.link+"'>http://192.168.1.24:5173/</font></u><br/><br/>"+
              "<font color='"+Theme.palette.warning+"'>✓ 85 aprovados</font>   <font color='"+Theme.palette.warning+"'>⚠ 2 avisos</font>   <font color='"+Theme.palette.danger+"'>✗ 0 falhas</font><br/><br/>"+
              "<span style='background-color:"+Theme.palette.warning+";color:"+Theme.palette.background+"'> PRONTO </span> aguardando alterações — pressione <b>q</b> para sair<br/><br/>"+
              "<font color='"+Theme.palette.link+"'>➜ vrstudio</font> git:(<font color='"+Theme.palette.danger+"'>main</font>) <font color='"+Theme.palette.warning+"'>✗</font> ▏").replace(/ {2,}/g, spaces => "&nbsp;".repeat(spaces.length))
    }
}
