import QtQuick
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: root
    required property var research
    signal resumeRequested()
    visible: false
}
