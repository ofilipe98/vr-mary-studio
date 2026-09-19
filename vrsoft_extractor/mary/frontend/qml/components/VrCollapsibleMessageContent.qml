pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import "../theme"

// Collapsible wrapper for chat message bodies. Clips only the outer
// container so Markdown, code blocks, tables and text selection keep
// their internal state. The toggle appears only on real overflow
// (measured implicitHeight vs collapsedMaxHeight), never on character count.
Column {
    id: root
    objectName: "collapsibleMessageContent"

    // Single visual budget for the collapsed state (density-consistent).
    property int collapsedMaxHeight: Theme.scaledGeometry(240)
    // Inner spacing between message blocks. Hosts set it to preserve their
    // pre-collapse rhythm (assistant Markdown used spacing 12).
    property real contentSpacing: 0
    property bool expanded: false
    // While streaming, the full content stays visible so the tail can be
    // followed. Never force `expanded` here: manual state must survive.
    property bool streaming: false
    // Reset per-message expansion when the delegate binds another message.
    property string messageKey: ""
    property color fadeColor: Theme.palette.chatBackground
    property bool overflows: false
    property bool animating: false
    signal layoutChanging()
    // heightDelta is old viewport height minus new viewport height
    // (positive when collapsing). The host applies scroll
    // compensation as height changes flush to contentHeight; this
    // signal never arms preserveReader().
    signal toggled(bool expanded, real heightDelta)
    signal anchorRequested()
    signal transitionFinished()

    readonly property bool effectiveExpanded: expanded || streaming
    // Hosts declare their blocks as direct children; they land in contentColumn.
    default property alias content: contentColumn.data

    spacing: 2

    onMessageKeyChanged: {
        root.expanded = false
        Qt.callLater(root.updateOverflow)
    }
    onCollapsedMaxHeightChanged: Qt.callLater(root.updateOverflow)
    // Recalculate overflow when streaming starts/ends, but never rewrite
    // the manual `expanded` state: a long message the user never expanded
    // returns to collapsed once streaming ends.
    onStreamingChanged: {
        root.updateOverflow()
        if (!root.streaming && !root.expanded && root.overflows) {
            var fullH = contentColumn ? contentColumn.implicitHeight : 0
            var collapsedH = Math.min(fullH, root.collapsedMaxHeight)
            if (Math.abs(viewport.height - collapsedH) > 1 && !frontend.reduceMotion)
                root.animating = true
            root.anchorRequested()
            if (root.animating) {
                Qt.callLater(function() {
                    if (root.animating && !heightAnim.running) {
                        root.animating = false
                        root.transitionFinished()
                    }
                })
            }
        }
    }
    Component.onCompleted: Qt.callLater(root.updateOverflow)

    function updateOverflow() {
        if (!contentColumn)
            return
        var full = contentColumn.implicitHeight
        var shouldOverflow = full > root.collapsedMaxHeight + 1
        if (root.overflows !== shouldOverflow)
            root.overflows = shouldOverflow
        if (!shouldOverflow && root.expanded && !root.streaming)
            root.expanded = false
    }

    function toggle() {
        // The button is hidden while streaming; guard keyboard paths too.
        if (root.streaming)
            return
        var full = contentColumn.implicitHeight
        var collapsedH = Math.min(full, root.collapsedMaxHeight)
        var targetH = root.expanded ? collapsedH : full
        if (Math.abs(viewport.height - targetH) > 1 && !frontend.reduceMotion && !root.streaming)
            root.animating = true
        root.anchorRequested()
        var oldH = root.expanded ? full : collapsedH
        root.expanded = !root.expanded
        var newH = root.expanded ? full : collapsedH
        root.toggled(root.expanded, oldH - newH)
        if (root.animating) {
            Qt.callLater(function() {
                if (root.animating && !heightAnim.running) {
                    root.animating = false
                    root.transitionFinished()
                }
            })
        }
    }

    Item {
        id: viewport
        width: parent.width
        implicitHeight: root.effectiveExpanded
            ? contentColumn.implicitHeight
            : Math.min(contentColumn.implicitHeight, root.collapsedMaxHeight)
        height: implicitHeight
        clip: true

        Behavior on height {
            id: heightBehavior
            enabled: !frontend.reduceMotion && !root.streaming
            NumberAnimation {
                id: heightAnim
                duration: Theme.fastDuration
                easing.type: Easing.OutCubic
                onRunningChanged: {
                    if (!running) {
                        root.animating = false
                        root.transitionFinished()
                    }
                }
            }
        }

        Column {
            id: contentColumn
            objectName: "collapsibleContentColumn"
            width: parent.width
            spacing: root.contentSpacing
            onImplicitHeightChanged: {
                // Content grew after first layout (Markdown, fonts, code
                // wrap, tables, images): re-evaluate real overflow.
                // No layoutChanging here: Flickable keeps contentY stable on
                // inner growth, and emitting would arm preserveReader's timer
                // against in-flight wheel/scrollbar gestures. Explicit height
                // changes (toggle) emit layoutChanging via toggle().
                Qt.callLater(root.updateOverflow)
            }
            onWidthChanged: Qt.callLater(root.updateOverflow)
        }

        // Subtle fade hint that more content exists below. Uses the host
        // message background and vanishes fully when expanded.
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 44
            visible: root.overflows && !root.effectiveExpanded
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: root.fadeColor }
            }
        }
    }

    Connections {
        target: frontend
        function onThemeChanged() { Qt.callLater(root.updateOverflow) }
        function onTypographyChanged() { Qt.callLater(root.updateOverflow) }
    }

    Button {
        id: toggleButton
        objectName: "messageExpandButton"
        // Hidden while streaming: full content is shown and there is no
        // collapsed state to toggle to, so no dead control is exposed.
        visible: root.overflows && !root.streaming
        text: root.effectiveExpanded ? "Mostrar menos" : "Mostrar mais"
        focusPolicy: Qt.StrongFocus
        leftPadding: 8
        rightPadding: 8
        topPadding: 4
        bottomPadding: 4
        implicitHeight: 28
        Accessible.role: Accessible.Button
        Accessible.name: toggleButton.text
        Accessible.description: root.effectiveExpanded ? "Recolher mensagem" : "Expandir mensagem completa"
        Accessible.checkable: true
        Accessible.checked: root.effectiveExpanded
        onClicked: root.toggle()
        contentItem: Text {
            text: toggleButton.text
            color: toggleButton.hovered || toggleButton.activeFocus || toggleButton.down
                ? Theme.palette.text : Theme.palette.mutedText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.captionSize
            font.weight: Theme.weightMedium
            horizontalAlignment: Text.AlignLeft
            verticalAlignment: Text.AlignVCenter
            renderType: Theme.textRenderType
            Behavior on color {
                enabled: !frontend.reduceMotion
                ColorAnimation { duration: Theme.fastDuration }
            }
        }
        background: Rectangle {
            radius: Theme.radiusSmall
            color: toggleButton.down || toggleButton.hovered ? Theme.palette.hover : "transparent"
            border.width: toggleButton.activeFocus ? 1 : 0
            border.color: Theme.palette.focus
            Behavior on color {
                enabled: !frontend.reduceMotion
                ColorAnimation { duration: Theme.fastDuration }
            }
        }
        HoverHandler {
            cursorShape: Qt.PointingHandCursor
        }
    }
}
