import QtQuick
import QtQuick.Controls
import "../theme"

Item {
    id: root

    property string title: ""
    property var iconSource: ""
    property string iconKind: ""
    property bool selected: false
    property bool compact: false
    signal activated()

    // Resting fill keeps the hover RGB with zero alpha: ColorAnimation
    // interpolates RGBA without premultiplying alpha, so animating from
    // "transparent" (#00000000) would flash a dark box over the sidebar.
    readonly property color navHoverFill: Theme.palette.navHover
    readonly property color navRestFill: Qt.rgba(
        navHoverFill.r, navHoverFill.g, navHoverFill.b, 0)

    // T3 settings navigation row: h-8 (32), rounded-md (8), px-2 (8), gap-2 (8),
    // text-sm (14) and a size-4 (16) icon.
    implicitHeight: Theme.sidebarRowHeight
    implicitWidth: compact ? Theme.scaledGeometry(34) : navLabel.implicitWidth + 44
    focus: false
    activeFocusOnTab: true
    transformOrigin: Item.Center
    scale: !frontend.reduceMotion && navTap.pressed ? 0.975 : 1
    Accessible.role: Accessible.Button
    Accessible.name: "Abrir " + title
    Keys.onReturnPressed: activated()
    Keys.onEnterPressed: activated()
    Keys.onSpacePressed: activated()

    Behavior on scale {
        enabled: !frontend.reduceMotion
        NumberAnimation { duration: Theme.pressDuration; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusControl
        color: root.selected
            ? Theme.palette.chatControl
            : (pointer.hovered || root.activeFocus ? root.navHoverFill : root.navRestFill)
        border.width: root.activeFocus ? 1 : (root.selected ? 1 : 0)
        border.color: root.activeFocus
            ? Theme.palette.focus
            : (root.selected ? Qt.rgba(255, 255, 255, 0.08) : "transparent")

        Behavior on color {
            enabled: !frontend.reduceMotion
            ColorAnimation { duration: Theme.fastDuration }
        }
    }

    Row {
        anchors.fill: parent
        anchors.leftMargin: root.compact ? 0 : Theme.sidebarContentInset
        anchors.rightMargin: root.compact ? 0 : Theme.sidebarContentInset
        spacing: Theme.sidebarControlGap

        Item {
            width: root.compact ? parent.width : Theme.iconSmall
            height: parent.height

            Image {
                id: navIcon
                visible: root.iconKind.length === 0 && root.iconSource.toString().length > 0
                anchors.centerIn: parent
                width: Theme.iconSmall
                height: Theme.iconSmall
                source: root.iconSource
                sourceSize.width: 32
                sourceSize.height: 32
                fillMode: Image.PreserveAspectFit
                opacity: root.selected ? 1.0 : (pointer.hovered ? 0.95 : 0.72)
            }

            // Official Lucide geometry (stroke 2) keeps the navigation aligned
            // with every other line icon instead of the thinner 1.6 SVGs.
            VrLineIcon {
                visible: root.iconKind.length > 0
                anchors.centerIn: parent
                width: Theme.iconSmall
                height: Theme.iconSmall
                kind: root.iconKind
                foreground: root.selected ? "#FFFFFF" : Theme.palette.navText
                opacity: root.selected ? 1.0 : (pointer.hovered ? 0.95 : 0.78)
            }
        }

        Text {
            id: navLabel
            visible: !root.compact
            width: Math.max(0, parent.width - Theme.iconSmall - Theme.sidebarControlGap)
            height: parent.height
            text: root.title
            color: root.selected ? "#FFFFFF" : Theme.palette.navText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeControl
            font.weight: root.selected ? Font.Medium : Font.Normal
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            renderType: Theme.textRenderType
        }
    }

    HoverHandler { id: pointer }
    TapHandler {
        id: navTap
        onTapped: {
            root.forceActiveFocus()
            root.activated()
        }
    }

}
