pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window

Item {
    id: root
    objectName: "vrResizeBorders"
    property Window window: null
    anchors.fill: parent
    visible: root.window ? (root.window.visibility !== Window.Maximized && root.window.visibility !== Window.FullScreen) : false
    z: 10000

    readonly property int borderThickness: 5
    readonly property int cornerSize: 8

    // Left border
    MouseArea {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: root.cornerSize
        anchors.bottomMargin: root.cornerSize
        width: root.borderThickness
        cursorShape: Qt.SizeHorCursor
        onPressed: if (root.window) root.window.startSystemResize(Qt.LeftEdge)
    }

    // Right border
    MouseArea {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: root.cornerSize
        anchors.bottomMargin: root.cornerSize
        width: root.borderThickness
        cursorShape: Qt.SizeHorCursor
        onPressed: if (root.window) root.window.startSystemResize(Qt.RightEdge)
    }

    // Top border
    MouseArea {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: root.cornerSize
        anchors.rightMargin: root.cornerSize
        height: root.borderThickness
        cursorShape: Qt.SizeVerCursor
        onPressed: if (root.window) root.window.startSystemResize(Qt.TopEdge)
    }

    // Bottom border
    MouseArea {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.cornerSize
        anchors.rightMargin: root.cornerSize
        height: root.borderThickness
        cursorShape: Qt.SizeVerCursor
        onPressed: if (root.window) root.window.startSystemResize(Qt.BottomEdge)
    }

    // Top-Left corner
    MouseArea {
        anchors.left: parent.left
        anchors.top: parent.top
        width: root.cornerSize
        height: root.cornerSize
        cursorShape: Qt.SizeFDiagCursor
        onPressed: if (root.window) root.window.startSystemResize(Qt.TopEdge | Qt.LeftEdge)
    }

    // Top-Right corner
    MouseArea {
        anchors.right: parent.right
        anchors.top: parent.top
        width: root.cornerSize
        height: root.cornerSize
        cursorShape: Qt.SizeBDiagCursor
        onPressed: if (root.window) root.window.startSystemResize(Qt.TopEdge | Qt.RightEdge)
    }

    // Bottom-Left corner
    MouseArea {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        width: root.cornerSize
        height: root.cornerSize
        cursorShape: Qt.SizeBDiagCursor
        onPressed: if (root.window) root.window.startSystemResize(Qt.BottomEdge | Qt.LeftEdge)
    }

    // Bottom-Right corner
    MouseArea {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: root.cornerSize
        height: root.cornerSize
        cursorShape: Qt.SizeFDiagCursor
        onPressed: if (root.window) root.window.startSystemResize(Qt.BottomEdge | Qt.RightEdge)
    }
}
