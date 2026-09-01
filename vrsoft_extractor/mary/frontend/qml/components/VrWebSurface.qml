import QtQuick
import QtWebEngine

WebEngineView {
    id: root

    readonly property bool fillViewport: frontend.browserViewport === "fill"
    readonly property var viewportParts: frontend.browserViewport.split("x")
    readonly property real requestedWidth: fillViewport
        ? (parent ? parent.width : 1) : Number(viewportParts[0] || 1)
    readonly property real requestedHeight: fillViewport
        ? (parent ? parent.height : 1) : Number(viewportParts[1] || 1)

    width: requestedWidth
    height: requestedHeight
    transformOrigin: Item.TopLeft
    scale: fillViewport || !parent ? 1 : Math.min(
        1, parent.width / requestedWidth, parent.height / requestedHeight)

    zoomFactor: frontend.browserZoomFactor
    backgroundColor: frontend.browserAppearance === "dark"
        ? "#090909" : frontend.browserAppearance === "light"
        ? "#FFFFFF" : frontend.palette.chatBackground

    signal addressChanged(string value)

    function navigate(value) {
        var normalized = String(value || "").trim()
        if (!normalized.length)
            return
        if (normalized.toLowerCase().indexOf("localhost") === 0)
            normalized = "http://" + normalized
        else if (normalized.indexOf("://") < 0 && normalized.indexOf(".") < 0)
            normalized = "https://www.google.com/search?q=" + encodeURIComponent(normalized)
        else if (normalized.indexOf("://") < 0)
            normalized = "https://" + normalized
        root.url = normalized
    }

    function goBackPage() {
        if (root.canGoBack)
            root.goBack()
    }

    function goForwardPage() {
        if (root.canGoForward)
            root.goForward()
    }

    function reloadPage() {
        root.reload()
    }

    onUrlChanged: root.addressChanged(root.url.toString())
}
