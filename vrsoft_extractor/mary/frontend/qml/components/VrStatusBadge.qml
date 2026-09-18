import QtQuick
import "../theme"

Rectangle {
    id: badge

    property string text: ""
    property string kind: "info"

    implicitWidth: label.implicitWidth + 18
    implicitHeight: 24
    radius: height / 2
    color: {
        if (kind === "success")
            return frontend.themeId === "dark_orange" ? "#183629" : "#E8F5ED"
        if (kind === "warning")
            return frontend.themeId === "dark_orange" ? "#3A2A1F" : "#FFF4E5"
        return Theme.palette.selection
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: badge.text
        color: kind === "success" ? Theme.palette.success
            : kind === "warning" ? Theme.palette.warning
            : Theme.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeCaption
        font.weight: Theme.weightMedium
        renderType: Theme.textRenderType
    }
}
