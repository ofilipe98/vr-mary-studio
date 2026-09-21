import QtQuick
import QtQuick.Layouts
import "../../theme"
import "../../components"

RowLayout {
    id: root
    property alias from: slider.from
    property alias to: slider.to
    property alias stepSize: slider.stepSize
    property alias value: slider.value
    property string suffix: "%"
    property string settingName: ""
    property string accessibleLabel: ({contrast: "Contraste", glass: "Opacidade do vidro", motion: "Animações dos painéis"})[settingName] || settingName
    signal moved(int value)
    implicitWidth: 208 * Theme.selectedScale
    Layout.preferredWidth: implicitWidth
    Layout.maximumWidth: implicitWidth
    spacing: Theme.scaledGeometry(12)
    Rectangle {
        Layout.preferredWidth: (root.suffix === " ms" ? 64 : 48) * Theme.textScale
        implicitHeight: Math.max(24, Theme.fontSize(11) + 10); radius: Theme.scaledGeometry(8)
        color: Theme.palette.mutedSurface || Theme.palette.surfaceRaised
        Text {
            anchors.centerIn: parent; text: Math.round(slider.value) + root.suffix
            font.family: Theme.monospaceFontFamily; font.pixelSize: Theme.fontSizeCaption; font.weight: Theme.weightMedium
            color: Theme.palette.text
        }
    }
    VrSlider {
        id: slider
        objectName: root.settingName + "Slider"
        Accessible.name: root.accessibleLabel
        Layout.fillWidth: true; Layout.preferredWidth: root.suffix === " ms" ? 132 : 148
        padding: 0
        onMoved: root.moved(Math.round(value))
    }
}
