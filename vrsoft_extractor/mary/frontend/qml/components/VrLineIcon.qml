import QtQuick

Canvas {
    id: root

    property string kind: ""
    property color foreground: frontend.palette.mutedText
    property real strokeWidth: 1.7

    implicitWidth: 20
    implicitHeight: 20

    onKindChanged: requestPaint()
    onForegroundChanged: requestPaint()
    onStrokeWidthChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onVisibleChanged: requestPaint()
    Component.onCompleted: requestPaint()

    Connections {
        target: frontend
        function onThemeChanged() { root.requestPaint() }
    }

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.strokeStyle = root.foreground
        ctx.fillStyle = root.foreground
        ctx.lineWidth = root.strokeWidth
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        var sx = width / 24
        var sy = height / 24
        ctx.scale(sx, sy)

        function line(x1, y1, x2, y2) {
            ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke()
        }
        function rect(x, y, w, h, radius) {
            var r = Math.min(radius, w / 2, h / 2)
            ctx.beginPath(); ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y)
            ctx.quadraticCurveTo(x + w, y, x + w, y + r)
            ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
            ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r)
            ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y); ctx.stroke()
        }

        if (kind === "browser") {
            ctx.beginPath(); ctx.arc(12, 12, 8.2, 0, Math.PI * 2); ctx.stroke()
            line(3.8, 12, 20.2, 12)
            ctx.beginPath(); ctx.moveTo(12, 3.8)
            ctx.bezierCurveTo(7.5, 6.5, 7.5, 17.5, 12, 20.2)
            ctx.bezierCurveTo(16.5, 17.5, 16.5, 6.5, 12, 3.8); ctx.stroke()
        } else if (kind === "terminal") {
            rect(3.5, 5, 17, 14, 2)
            ctx.beginPath(); ctx.moveTo(7, 9); ctx.lineTo(10, 12); ctx.lineTo(7, 15); ctx.stroke()
            line(12.5, 15, 17, 15)
        } else if (kind === "files") {
            ctx.beginPath(); ctx.moveTo(3.5, 8); ctx.lineTo(3.5, 18); ctx.quadraticCurveTo(3.5, 20, 5.5, 20); ctx.lineTo(18.5, 20); ctx.quadraticCurveTo(20.5, 20, 20.5, 18); ctx.lineTo(20.5, 9); ctx.quadraticCurveTo(20.5, 7, 18.5, 7); ctx.lineTo(11, 7); ctx.lineTo(9, 4.8); ctx.lineTo(5.5, 4.8); ctx.quadraticCurveTo(3.5, 4.8, 3.5, 7); ctx.closePath(); ctx.stroke()
        } else if (kind === "folder") {
            ctx.beginPath(); ctx.moveTo(3.5, 7.5); ctx.lineTo(3.5, 18)
            ctx.quadraticCurveTo(3.5, 20, 5.5, 20); ctx.lineTo(18.5, 20)
            ctx.quadraticCurveTo(20.5, 20, 20.5, 18); ctx.lineTo(20.5, 9)
            ctx.quadraticCurveTo(20.5, 7, 18.5, 7); ctx.lineTo(11, 7)
            ctx.lineTo(9, 4.8); ctx.lineTo(5.5, 4.8)
            ctx.quadraticCurveTo(3.5, 4.8, 3.5, 7.5); ctx.stroke()
        } else if (kind === "context") {
            ctx.beginPath(); ctx.moveTo(4, 5); ctx.quadraticCurveTo(8, 3.5, 11, 5); ctx.lineTo(11, 20); ctx.quadraticCurveTo(8, 18.2, 4, 20); ctx.closePath(); ctx.stroke()
            ctx.beginPath(); ctx.moveTo(20, 5); ctx.quadraticCurveTo(16, 3.5, 13, 5); ctx.lineTo(13, 20); ctx.quadraticCurveTo(16, 18.2, 20, 20); ctx.closePath(); ctx.stroke()
        } else if (kind === "agents") {
            rect(4, 8, 16, 11, 2.2); rect(8.5, 4.5, 7, 4, 1.5)
            line(8, 13, 8.1, 13); line(16, 13, 16.1, 13); line(9.5, 16, 14.5, 16)
        } else if (kind === "panelRight") {
            rect(3.5, 4.5, 17, 15, 2.5); line(15, 5, 15, 19)
        } else if (kind === "panelLeft") {
            rect(3.5, 4.5, 17, 15, 2.5); line(9, 5, 9, 19)
        } else if (kind === "newChat") {
            ctx.beginPath(); ctx.moveTo(11.5, 5.2); ctx.lineTo(6.5, 5.2)
            ctx.quadraticCurveTo(4.5, 5.2, 4.5, 7.2); ctx.lineTo(4.5, 17.5)
            ctx.quadraticCurveTo(4.5, 19.5, 6.5, 19.5); ctx.lineTo(16.8, 19.5)
            ctx.quadraticCurveTo(18.8, 19.5, 18.8, 17.5); ctx.lineTo(18.8, 12.5); ctx.stroke()
            ctx.beginPath(); ctx.moveTo(10, 16); ctx.lineTo(10.8, 12.7)
            ctx.lineTo(18, 5.5); ctx.lineTo(20.5, 8); ctx.lineTo(13.3, 15.2)
            ctx.closePath(); ctx.stroke()
        } else if (kind === "back") {
            line(16, 5, 9, 12); line(9, 12, 16, 19)
        } else if (kind === "forward") {
            line(8, 5, 15, 12); line(15, 12, 8, 19)
        } else if (kind === "reload") {
            ctx.beginPath(); ctx.arc(12, 12, 7, -0.8, Math.PI * 1.65); ctx.stroke()
            line(16.8, 4.5, 18.8, 8.2); line(18.8, 8.2, 14.8, 8)
        } else if (kind === "plus") {
            line(12, 5, 12, 19); line(5, 12, 19, 12)
        } else if (kind === "close") {
            line(6, 6, 18, 18); line(18, 6, 6, 18)
        } else if (kind === "chevronDown") {
            line(6, 9, 12, 15); line(12, 15, 18, 9)
        } else if (kind === "chevronUp") {
            line(6, 15, 12, 9); line(12, 9, 18, 15)
        } else if (kind === "chevronRight") {
            line(9, 6, 15, 12); line(15, 12, 9, 18)
        } else if (kind === "task") {
            rect(4, 4, 16, 16, 2.5)
            line(7.5, 9, 9.5, 11); line(9.5, 11, 13, 7.5)
            line(7.5, 15, 9.5, 17); line(9.5, 17, 13, 13.5)
            line(14.5, 9.5, 17, 9.5); line(14.5, 15.5, 17, 15.5)
        } else if (kind === "search") {
            ctx.beginPath(); ctx.arc(10.5, 10.5, 5.8, 0, Math.PI * 2); ctx.stroke(); line(14.7, 14.7, 19.5, 19.5)
        } else if (kind === "models") {
            ctx.beginPath(); ctx.arc(12, 12, 8, 0, Math.PI * 2); ctx.stroke()
            ctx.beginPath(); ctx.arc(12, 12, 3.2, 0, Math.PI * 2); ctx.stroke()
        } else if (kind === "star") {
            var outer = 8.5; var inner = 3.8; var angle = -Math.PI / 2
            ctx.beginPath()
            for (var point = 0; point < 10; ++point) {
                var radius = point % 2 === 0 ? outer : inner
                var px = 12 + Math.cos(angle) * radius
                var py = 12 + Math.sin(angle) * radius
                if (point === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                angle += Math.PI / 5
            }
            ctx.closePath(); ctx.stroke()
        } else if (kind === "copy") {
            rect(8, 8, 11, 11, 2.2)
            ctx.beginPath(); ctx.moveTo(5, 14); ctx.lineTo(5, 7)
            ctx.quadraticCurveTo(5, 5, 7, 5); ctx.lineTo(14, 5); ctx.stroke()
        } else if (kind === "archive") {
            rect(4, 7, 16, 13, 2)
            rect(3, 4, 18, 5, 1.5)
            line(9, 13, 15, 13)
        } else if (kind === "lock") {
            rect(5, 10, 14, 10, 2)
            ctx.beginPath(); ctx.arc(12, 10, 4.5, Math.PI, 0); ctx.stroke()
        } else if (kind === "unlock") {
            rect(5, 10, 14, 10, 2)
            ctx.beginPath(); ctx.arc(12, 10, 4.5, Math.PI, 0)
            ctx.moveTo(7.5, 10); ctx.lineTo(7.5, 7.2); ctx.stroke()
        } else if (kind === "edit") {
            ctx.beginPath(); ctx.moveTo(5, 19); ctx.lineTo(7, 14)
            ctx.lineTo(16.8, 4.2); ctx.lineTo(19.8, 7.2)
            ctx.lineTo(10, 17); ctx.closePath(); ctx.stroke()
            line(5, 19, 10, 17)
        } else if (kind === "auto") {
            function sparkle(cx, cy, horizontal, vertical) {
                ctx.beginPath()
                ctx.moveTo(cx, cy - vertical)
                ctx.quadraticCurveTo(cx + horizontal * 0.2, cy - vertical * 0.2,
                    cx + horizontal, cy)
                ctx.quadraticCurveTo(cx + horizontal * 0.2, cy + vertical * 0.2,
                    cx, cy + vertical)
                ctx.quadraticCurveTo(cx - horizontal * 0.2, cy + vertical * 0.2,
                    cx - horizontal, cy)
                ctx.quadraticCurveTo(cx - horizontal * 0.2, cy - vertical * 0.2,
                    cx, cy - vertical)
                ctx.closePath()
                ctx.stroke()
            }
            sparkle(9.5, 12.5, 5.2, 6.3)
            sparkle(17.3, 6.1, 2.2, 2.8)
            sparkle(18.2, 17.7, 1.8, 2.3)
        } else if (kind === "settings") {
            var toothStep = Math.PI / 4
            ctx.beginPath()
            for (var tooth = 0; tooth < 8; ++tooth) {
                var center = -Math.PI / 2 + tooth * toothStep
                var angles = [center - 0.31, center - 0.15, center + 0.15, center + 0.31]
                var radii = [7.2, 9.2, 9.2, 7.2]
                for (var edge = 0; edge < angles.length; ++edge) {
                    var gx = 12 + Math.cos(angles[edge]) * radii[edge]
                    var gy = 12 + Math.sin(angles[edge]) * radii[edge]
                    if (tooth === 0 && edge === 0) ctx.moveTo(gx, gy)
                    else ctx.lineTo(gx, gy)
                }
            }
            ctx.closePath(); ctx.stroke()
            ctx.beginPath(); ctx.arc(12, 12, 2.8, 0, Math.PI * 2); ctx.stroke()
        } else if (kind === "trash") {
            ctx.beginPath(); ctx.moveTo(7, 8); ctx.lineTo(8, 20)
            ctx.quadraticCurveTo(8.1, 21, 9.2, 21); ctx.lineTo(14.8, 21)
            ctx.quadraticCurveTo(15.9, 21, 16, 20); ctx.lineTo(17, 8); ctx.stroke()
            line(5.5, 7, 18.5, 7); line(9.5, 4, 14.5, 4)
            line(10.5, 10, 10.8, 18); line(13.5, 10, 13.2, 18)
        }
    }
}
