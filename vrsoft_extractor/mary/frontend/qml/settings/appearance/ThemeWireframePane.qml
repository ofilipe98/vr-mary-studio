import QtQuick
Canvas {
    id: root
    property bool isDark: true
    readonly property var selectedPalette: {
        var id = isDark ? frontend.themeDark : frontend.themeLight
        var themes = frontend.availableThemes
        for (var i = 0; i < themes.length; ++i)
            if (themes[i].id === id) return themes[i].palette
        return frontend.palette
    }
    onIsDarkChanged: requestPaint()
    onSelectedPaletteChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        var c = getContext("2d"); c.reset(); c.save()
        var p = selectedPalette, w = width, h = height
        function box(x,y,bw,bh,r,color,stroke) {
            c.beginPath(); c.roundedRect(x,y,bw,bh,r,r)
            c.fillStyle=color; c.fill()
            if(stroke) { c.strokeStyle=stroke; c.lineWidth=1; c.stroke() }
        }
        c.beginPath(); c.roundedRect(0,0,w,h,9,9); c.clip()
        box(0,0,w,h,9,p.background)
        box(0,0,w*.22,h,0,p.previewSidebar || p.surface)
        c.fillStyle=p.border; c.fillRect(w*.22,0,1,h)
        box(8,12,w*.16,10,5,p.background,p.border)
        for(var i=0;i<3;i++) box(8,30+i*14,w*.16,10,5,p.previewMessage || p.surfaceRaised)
        box(w*.48,16,w*.24,13,7,p.previewMessage || p.surfaceRaised)
        var line = root.isDark ? Qt.rgba(1,1,1,.12) : Qt.rgba(0,0,0,.13)
        box(w*.27,40,w*.34,7,4,line)
        box(w*.27,53,w*.26,7,4,line)
        box(w*.26,h-32,w*.68,21,8,p.background,p.border)
        box(w*.29,h-24,w*.21,5,3,line)
        box(w*.87,h-28,12,12,6,p.previewAction || p.accessibleOrange)
        box(w*.75,12,w*.20,64,11,p.surface,p.border)
        for(var j=0;j<3;j++) {
            box(w*.78,23+j*19,3,3,1,[p.success,p.accessibleOrange,p.warning][j])
            box(w*.80,23+j*19,w*.075,4,2,line)
        }
        c.restore()
        c.beginPath(); c.roundedRect(.5,.5,w-1,h-1,9,9); c.lineWidth=1; c.strokeStyle=p.border; c.stroke()
    }
}
