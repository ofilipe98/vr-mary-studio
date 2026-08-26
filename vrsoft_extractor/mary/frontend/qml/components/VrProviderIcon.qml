import QtQuick

Item {
    id: root

    property string provider: "codex"

    implicitWidth: 22
    implicitHeight: 22
    clip: true

    Rectangle {
        visible: root.provider === "codex"
        anchors.fill: parent
        radius: width / 2
        color: "#F6F7F8"
    }

    Image {
        anchors.fill: parent
        source: root.providerIcon(root.provider)
        fillMode: root.provider === "codex"
            ? Image.PreserveAspectCrop : Image.PreserveAspectFit
        sourceSize.width: root.provider === "codex" ? 64 : 48
        sourceSize.height: root.provider === "codex" ? 36 : 48
    }

    function providerIcon(providerName) {
        if (providerName === "claude")
            return Qt.resolvedUrl("../../../assets/provider-claude.webp")
        if (providerName === "opencode")
            return Qt.resolvedUrl("../../../assets/provider-opencode.svg")
        return Qt.resolvedUrl("../../../assets/provider-gpt.png")
    }
}
