import QtQuick
import "../theme"
import "../theme/LucidePaths.js" as LucidePaths

Canvas {
    id: root

    property string kind: ""
    property color foreground: Theme.palette.mutedText
    // Solid variants (favorite star, filled badges) paint the Lucide geometry
    // as a shape instead of a stroke; T3 uses the same split for star toggles.
    property bool filled: false
    // 2.0 on the 24-unit grid matches Lucide's official 2px stroke, the same
    // geometry T3 renders; at 12-20px the effective stroke stays 1.0-1.7px.
    property real strokeWidth: 2.0

    implicitWidth: 20
    implicitHeight: 20

    onKindChanged: requestPaint()
    onForegroundChanged: requestPaint()
    onFilledChanged: requestPaint()
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

        // Official Lucide geometry keeps the glyph mass identical to T3's
        // lucide-react icons at the same box size (see theme/LucidePaths.js).
        var paths = LucidePaths.paths[root.kind]
        if (paths) {
            for (var i = 0; i < paths.length; ++i) {
                ctx.beginPath()
                ctx.path = paths[i]
                if (root.filled) ctx.fill(); else ctx.stroke()
            }
            return
        }

        // VR-specific kinds without a Lucide counterpart keep local geometry.
        if (root.kind === "task") {
            rect(4, 4, 16, 16, 2.5)
            line(7.5, 9, 9.5, 11); line(9.5, 11, 13, 7.5)
            line(7.5, 15, 9.5, 17); line(9.5, 17, 13, 13.5)
            line(14.5, 9.5, 17, 9.5); line(14.5, 15.5, 17, 15.5)
        } else if (root.kind === "models") {
            ctx.beginPath(); ctx.arc(12, 12, 8, 0, Math.PI * 2); ctx.stroke()
            ctx.beginPath(); ctx.arc(12, 12, 3.2, 0, Math.PI * 2); ctx.stroke()
        } else if (root.kind === "expertSenior") {
            ctx.beginPath(); ctx.arc(10, 8, 3.1, 0, Math.PI * 2); ctx.stroke()
            ctx.beginPath(); ctx.arc(10, 20, 6.1, Math.PI, 0); ctx.stroke()
            ctx.beginPath(); ctx.moveTo(18.2, 4.6); ctx.lineTo(19.2, 6.7)
            ctx.lineTo(21.5, 7); ctx.lineTo(19.8, 8.6); ctx.lineTo(20.2, 11)
            ctx.lineTo(18.2, 9.9); ctx.lineTo(16.1, 11); ctx.lineTo(16.5, 8.6)
            ctx.lineTo(14.8, 7); ctx.lineTo(17.1, 6.7); ctx.closePath(); ctx.stroke()
        } else if (root.kind === "expertImplementation") {
            rect(3.5, 4.5, 7.2, 6.2, 1.4)
            rect(13.3, 13.3, 7.2, 6.2, 1.4)
            line(10.7, 7.6, 15.4, 7.6); line(15.4, 7.6, 15.4, 13.3)
            ctx.beginPath(); ctx.moveTo(16, 3.8); ctx.lineTo(17.2, 5.2)
            ctx.lineTo(20.3, 2.8); ctx.stroke()
        }
    }
}
