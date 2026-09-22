import QtQuick
import QtQuick.Controls
import "../../theme"
import "../../components"
AbstractButton {
    id: root
    property string mode: "dark"
    property color canvasColor: "#0a0a0a"
    property color accentColor: "#1c1c1f"
    property color actionColor: Theme.palette.brandOrange
    property bool isActive: false
    implicitWidth: Theme.scaledGeometry(68); implicitHeight: Theme.scaledGeometry(68)
    hoverEnabled: true
    Accessible.name: mode === "light" ? "Usar variante clara" : "Usar variante escura"
    Accessible.checkable: true; Accessible.checked: isActive
    background: Rectangle {
        radius: width/2; color: "transparent"
        border.width: root.isActive || root.visualFocus ? 2 : 0; border.color: Theme.palette.focus
    }
    contentItem: Item {
        Canvas {
            id: orb
            anchors.centerIn: parent; width: Theme.scaledGeometry(52); height: Theme.scaledGeometry(52)
            renderTarget: Canvas.Image
            onPaint: {
                var c = getContext("2d"); c.reset(); c.save()
                var w=width, h=height, dark=root.mode === "dark"
                c.beginPath(); c.arc(w/2,h/2,w/2,0,Math.PI*2); c.clip()
                c.fillStyle=Qt.tint(root.canvasColor, Qt.alpha(dark ? "#09090b" : "#ffffff", .2)); c.fillRect(0,0,w,h)
                var x=dark ? .28 : .72, y=dark ? .78 : .22
                var g=c.createRadialGradient(w*x,h*y,0,w*x,h*y,w*.78)
                g.addColorStop(0,root.accentColor); g.addColorStop(.36,Qt.alpha(root.accentColor,dark?.62:.72)); g.addColorStop(1,Qt.alpha(root.accentColor,0))
                c.fillStyle=g; c.fillRect(0,0,w,h)
                var a=c.createRadialGradient(w*(dark?.82:.18),h*(dark?.18:.82),0,w*(dark?.82:.18),h*(dark?.18:.82),w*.74)
                a.addColorStop(0,Qt.alpha(root.actionColor,.45)); a.addColorStop(1,Qt.alpha(root.actionColor,0))
                c.fillStyle=a; c.fillRect(0,0,w,h); c.restore()
            }
        }
        Rectangle {
            visible: root.isActive
            anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 2
            width: Theme.scaledGeometry(20); height: Theme.scaledGeometry(20); radius: Theme.scaledGeometry(10)
            color: Theme.palette.background; border.color: Theme.palette.border
            VrLineIcon {
                anchors.centerIn: parent; width: Theme.iconMicro; height: Theme.iconMicro
                kind: root.mode === "light" ? "sun" : "moon"; foreground: Theme.palette.text
            }
        }
    }
    onCanvasColorChanged: orb.requestPaint()
    onAccentColorChanged: orb.requestPaint()
    onActionColorChanged: orb.requestPaint()
    onModeChanged: orb.requestPaint()
}
