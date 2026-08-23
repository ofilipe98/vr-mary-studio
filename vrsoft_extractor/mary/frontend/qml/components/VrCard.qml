import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: card

    default property alias content: contentColumn.data
    property int contentSpacing: Theme.spaceMd

    implicitHeight: Math.max(120, contentColumn.implicitHeight + Theme.space2Xl)
    color: frontend.palette.surface
    radius: Theme.radiusCard
    border.width: 1
    border.color: frontend.palette.border

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: Theme.spaceLg
        spacing: card.contentSpacing
    }
}
