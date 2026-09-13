import QtQuick
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: root
    required property var research
    signal resumeRequested(bool grantBudget)
    visible: false
}
