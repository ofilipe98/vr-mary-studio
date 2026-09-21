import QtQuick
import "../theme"
import QtQuick.Layouts

// Keep controls aligned, and move them below their label in narrow panels.
GridLayout {
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    columns: width < 620 ? 1 : 2
    columnSpacing: Theme.scaledGeometry(24)
    rowSpacing: Theme.scaledGeometry(8)
}
