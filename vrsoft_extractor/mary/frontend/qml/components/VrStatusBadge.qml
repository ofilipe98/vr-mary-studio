import QtQuick
import "../theme"

Rectangle {
    id: badge

    property string text: ""
    property string kind: "info"

    implicitWidth: label.implicitWidth + 18
    implicitHeight: 26
    radius: 13
    color: {
        if (kind === "success")
            return frontend.themeId === "dark_orange" ? "#183629" : "#E8F5ED"
        if (kind === "warning")
            return frontend.themeId === "dark_orange" ? "#3A2A1F" : "#FFF4E5"
        return frontend.palette.selection
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: badge.text
        color: kind === "success" ? frontend.palette.success
            : kind === "warning" ? frontend.palette.warning
            : frontend.palette.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(11)
        font.weight: Font.DemiBold
    }
}
