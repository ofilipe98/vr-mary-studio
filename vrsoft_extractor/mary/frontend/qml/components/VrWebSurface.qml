import QtQuick
import QtWebEngine

WebEngineView {
    id: root

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
