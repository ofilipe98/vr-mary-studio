import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: card

    default property alias content: contentColumn.data
    property int contentSpacing: Theme.spaceMd
    property bool flat: false

    implicitHeight: Math.max(120, contentColumn.implicitHeight + Theme.space2Xl)
    clip: true
    color: flat ? "transparent" : frontend.palette.surface
    radius: flat ? 0 : Theme.radiusCard
    border.width: flat ? 0 : 1
    border.color: frontend.palette.border

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: Theme.spaceLg
        spacing: card.contentSpacing
    }
}
