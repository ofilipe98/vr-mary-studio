import QtQuick
import "../theme"

// Paints the T3 inline-code chip behind a TextEdit body. Qt renders a
// fragment background as a flat rectangle; this layer maps the chip ranges
// reported by the bridge to rounded rectangles using the body's own layout,
// so the text keeps selection, links and copy behaviour untouched.
// Each visual line gets its own pill (Chrome's box-decoration-break: clone):
// the box is the code font box plus `.1rem` padding and the 1px border on
// each side, top-aligned to the code glyphs, which keeps the pill uniform on
// pure-code and mixed lines (browser reference: 19.19px per line).
Item {
    id: root
    objectName: "inlineChipLayer"

    property var body: null
    property var ranges: []
    // Surface font of the body (markdown body or table size); the inline-code
    // font derived below must match text_rendering's inline_code_ratio.
    property real fontPixelSize: Theme.markdownBodySize
    readonly property color fillColor: Theme.palette.inlineCodeSurface
    readonly property color borderColor: Theme.palette.chatBorder
    readonly property int chipBorderWidth: 1
    property var chipRects: []

    FontMetrics {
        id: codeMetrics
        font.family: Theme.monospaceFontFamily
        font.pixelSize: Math.max(1, Math.round(Math.trunc(root.fontPixelSize) * 0.857))
    }
    FontMetrics {
        id: bodyMetrics
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(1, Math.trunc(root.fontPixelSize))
    }

    function schedule() {
        recompute.restart()
    }

    function groupRect(groupY, minX, maxX, lineHeight) {
        var codeAscent = codeMetrics.ascent
        var codeBox = codeMetrics.ascent + codeMetrics.descent
        // positionToRectangle reports the line font box (max ascent + max
        // descent): on a pure-code line that box is the code font box, on a
        // mixed line the body font makes it taller and the code glyphs sit on
        // the shared baseline, `lineAscent - codeAscent` below the line top.
        var lineAscent = Math.abs(lineHeight - codeBox) <= 0.6
            ? codeAscent
            : lineHeight - bodyMetrics.descent
        return {
            x: minX - Theme.inlineChipPadding,
            y: groupY + lineAscent - codeAscent
                - Theme.inlineChipPaddingY - root.chipBorderWidth,
            w: maxX - minX + Theme.inlineChipPadding * 2,
            h: Math.max(1, codeBox
                + (Theme.inlineChipPaddingY + root.chipBorderWidth) * 2)
        }
    }

    function computeRects() {
        var list = root.ranges || []
        var output = []
        if (!root.body) {
            root.chipRects = output
            return
        }
        for (var index = 0; index < list.length; ++index) {
            var start = Number(list[index].start)
            var end = Number(list[index].end)
            if (!isFinite(start) || !isFinite(end) || end <= start)
                continue
            var groupY = NaN
            var minX = 0
            var maxX = 0
            var lineHeight = 0
            for (var position = start; position < end; ++position) {
                var rectangle = root.body.positionToRectangle(position)
                if (Math.round(rectangle.y) === Math.round(groupY)) {
                    minX = Math.min(minX, rectangle.x)
                    maxX = Math.max(maxX, rectangle.x + rectangle.width)
                    lineHeight = Math.max(lineHeight, rectangle.height)
                    continue
                }
                if (!isNaN(groupY))
                    output.push(root.groupRect(groupY, minX, maxX, lineHeight))
                groupY = rectangle.y
                minX = rectangle.x
                maxX = rectangle.x + rectangle.width
                lineHeight = rectangle.height
            }
            if (!isNaN(groupY))
                output.push(root.groupRect(groupY, minX, maxX, lineHeight))
        }
        root.chipRects = output
    }

    onRangesChanged: schedule()
    onBodyChanged: schedule()
    onWidthChanged: schedule()

    Timer {
        id: recompute
        interval: 0
        onTriggered: root.computeRects()
    }

    Connections {
        target: root.body
        function onTextChanged() { root.schedule() }
        function onWidthChanged() { root.schedule() }
        function onPaintedHeightChanged() { root.schedule() }
        function onPaintedWidthChanged() { root.schedule() }
    }

    // Typography changes re-run applyStyle (fresh ranges); these cover chip
    // geometry tokens and fonts that can change without new ranges.
    Connections {
        target: Theme
        function onInlineChipPaddingYChanged() { root.schedule() }
        function onMarkdownBodySizeChanged() { root.schedule() }
        function onMonospaceFontFamilyChanged() { root.schedule() }
    }

    Repeater {
        model: root.chipRects
        delegate: Rectangle {
            required property var modelData
            objectName: "inlineChip"
            x: modelData.x
            y: modelData.y
            width: modelData.w
            height: modelData.h
            radius: Theme.inlineChipRadius
            color: root.fillColor
            border.width: root.chipBorderWidth
            border.color: root.borderColor
        }
    }
}
