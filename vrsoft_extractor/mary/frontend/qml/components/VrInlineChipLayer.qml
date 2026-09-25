import QtQuick
import "../theme"

// Paints the T3 inline-code chip behind a TextEdit body. Qt renders a
// fragment background as a flat rectangle; this layer maps the chip ranges
// reported by the bridge to rounded rectangles using the body's own layout,
// so the text keeps selection, links and copy behaviour untouched.
Item {
    id: root
    objectName: "inlineChipLayer"

    property var body: null
    property var ranges: []
    readonly property color fillColor: Theme.palette.inlineCodeSurface
    readonly property color borderColor: Theme.palette.chatBorder
    readonly property int chipBorderWidth: 1
    property var chipRects: []

    function schedule() {
        recompute.restart()
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
                    output.push({ x: minX, y: groupY, w: maxX - minX, h: lineHeight })
                groupY = rectangle.y
                minX = rectangle.x
                maxX = rectangle.x + rectangle.width
                lineHeight = rectangle.height
            }
            if (!isNaN(groupY))
                output.push({ x: minX, y: groupY, w: maxX - minX, h: lineHeight })
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

    Repeater {
        model: root.chipRects
        delegate: Rectangle {
            required property var modelData
            objectName: "inlineChip"
            x: modelData.x - Theme.inlineChipPadding
            y: modelData.y + Theme.inlineChipInset
            width: modelData.w + Theme.inlineChipPadding * 2
            height: Math.max(1, modelData.h - Theme.inlineChipInset * 2)
            radius: Theme.inlineChipRadius
            color: root.fillColor
            border.width: root.chipBorderWidth
            border.color: root.borderColor
        }
    }
}
