import QtQuick
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root

    // Readable line length on QHD and 4K: cap the content and center it.
    property int maximumWidth: 1120

    anchors.horizontalCenter: parent.horizontalCenter
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    anchors.topMargin: Theme.pageMargin
    anchors.bottomMargin: Theme.pageMargin
    width: Math.min(parent.width - 2 * Theme.pageMargin, root.maximumWidth)
}
