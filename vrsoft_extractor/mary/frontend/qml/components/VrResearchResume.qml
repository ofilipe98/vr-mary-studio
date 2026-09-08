import QtQuick
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: root
    required property var research
    signal resumeRequested(bool grantBudget)
    visible: !!research.runId
    spacing: 8
    VrButton {
        objectName: "resumeResearchButton"
        Layout.alignment: Qt.AlignHCenter
        text: "Retomar investigação"
        enabled: !!root.research.publicationReady || (Number(root.research.callsRemaining || 0) > 0 && Number(root.research.secondsRemaining || 0) > 0)
        onClicked: root.resumeRequested(false)
    }
    VrButton {
        objectName: "resumeResearchWithBudgetButton"
        Layout.alignment: Qt.AlignHCenter
        text: "Retomar +15 chamadas / +300 s"
        onClicked: root.resumeRequested(true)
    }
}
