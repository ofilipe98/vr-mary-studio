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
    property bool expanded: false
    // While streaming, show the full content so the tail stays followable.
    // The message keeps expanded=true after streaming ends (no post-stream jump).
    property bool streaming: false
    // Reset per-message expansion when the delegate binds another message.
    property string messageKey: ""
    property color fadeColor: Theme.palette.chatBackground
    property bool overflows: false
    signal layoutChanging()
    signal toggled(bool expanded)

    readonly property bool effectiveExpanded: expanded || streaming
    // Hosts declare their blocks as direct children; they land in contentColumn.
    default property alias content: contentColumn.data

    spacing: 2

    onMessageKeyChanged: {
        root.expanded = false
        Qt.callLater(root.updateOverflow)
    }
    onCollapsedMaxHeightChanged: Qt.callLater(root.updateOverflow)
    onStreamingChanged: {
        if (root.streaming && !root.expanded)
            root.expanded = true
        Qt.callLater(root.updateOverflow)
    }
    onWidthChanged: Qt.callLater(root.updateOverflow)
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
        root.layoutChanging()
        root.expanded = !root.expanded
        root.toggled(root.expanded)
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
            enabled: !frontend.reduceMotion && !root.streaming
            NumberAnimation { duration: Theme.fastDuration; easing.type: Easing.OutCubic }
        }

        Column {
            id: contentColumn
            width: parent.width
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
        visible: root.overflows
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
