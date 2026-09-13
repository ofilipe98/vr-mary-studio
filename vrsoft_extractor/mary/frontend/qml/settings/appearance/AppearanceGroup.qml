import QtQuick
import QtQuick.Layouts
import "../../theme"

Rectangle {
    default property alias rows: column.data
    implicitHeight: column.implicitHeight + 2
    radius: 14
    color: Theme.palette.background
    border.color: Theme.palette.border
    ColumnLayout {
        id: column
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 1
        spacing: 0
    }
}
