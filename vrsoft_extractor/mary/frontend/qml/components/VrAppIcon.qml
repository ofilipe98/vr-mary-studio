import QtQuick
import QtQuick.Controls
import "../theme"

Item {
    id: root

    property string appName: ""
    property string fallbackKind: "browser"
    property real iconSize: 22
    property real containerSize: 32
    property bool showBackground: true
    property color fallbackForeground: Theme.palette.brandOrange

    implicitWidth: containerSize
    implicitHeight: containerSize

    readonly property var iconMap: ({
        "vradm": "VRAdm", "vranalytics": "VRAnalytics", "vratacado": "VRAtacado", "vratacadoweb": "VRAtacadoweb",
        "vratacarejo": "VRAtacado", "vratualizador": "VRAtualizador", "vrautorizador": "VRAutorizador",
        "vrbancodeideias": "VRBancodeIdeias", "vrcaixa": "VRCaixa", "vrcash": "VRCash",
        "vrcentralcompra": "VRCentralCompra", "vrcentralrede": "VRCentralRede", "vrchat": "VRChat",
        "vrcoletormobile": "VRColetorMobile", "vrcoletorserver": "VRColetorServer", "vrcoletorweb": "VRColetorWeb",
        "vrcomissao": "VRComissao", "vrcommons": "VRCommons", "vrcomponents": "VRComponents",
        "vrconcentrador": "VRConcentrador", "vrconsignacao": "VRConsignado", "vrconsignado": "VRConsignado",
        "vrconsultacheque": "VRConsultaCheque", "vrconsultapreco": "VRConsultaPreco", "vrcontabil": "VRContabil",
        "vrconvenio": "VRConvenio", "vrcore": "VRCore", "vrcotacao": "VRCotacao", "vrdatabase": "VRDatabase",
        "vrdelivery": "VRDelivery", "vrdisplayatendimento": "VRDisplayAtendimento", "vrecommercesphera": "VRECommerceSphera",
        "vrecommercewaio": "VREcommerceWaio", "vremissoretiqueta": "VREmissorEtiqueta", "vrencerramento": "VREncerramento",
        "vrestacionamento": "VREstacionamento", "vretiquetaeletronica": "VREtiquetaEletronica", "vrexportacaovenda": "VRExportacaoVenda",
        "vrexpurgador": "VRExpurgador", "vrficha": "VRFicha", "vrfichamobile": "VRFichaMobile", "vrfichaserver": "VRFichaServer",
        "vrfichaweb": "VRFichaWeb", "vrfinanceiro": "VRFinanceiro", "vrfood": "VRFood", "vrframework": "VRFramework",
        "vrfrente": "VRFrente", "vrgeradorjks": "VRGeradorJKS", "vrgerenciadorarcos": "VRGerenciadorArcos",
        "vrgerenciadorbalanca": "VRGerenciadorBalanca", "vrgerenciadorcrm": "VRGerenciadorCRM",
        "vrgerenciadorcentralcompra": "VRGerenciadorCentralCompra", "vrgerenciadordmcard": "VRGerenciadorDMCard",
        "vrgerenciadorecommercesphera": "VRGerenciadorECommerceSphera", "vrgerenciadormensagem": "VRGerenciadorMensagem",
        "vrgerenciadornfce": "VRGerenciadorNFCe", "vrgerenciadorscanntech": "VRGerenciadorScanntech",
        "vrgerenciadorvan": "VRGerenciadorVAN", "vrgerenciadorwms": "VRGerenciadorWMS", "vrgerenciadorwaio": "VRGerenciadorWaio",
        "vrgerenciadorxml": "VRGerenciadorXML", "vrgestor": "VRGestor", "vrglasfish": "VRGlasfish",
        "vrintegracao": "VRIntegracao", "vrintegracaoonblox": "VRIntegracaoOnblox", "vrjadeconnect": "VRJadeConnect",
        "vrlib": "VRLib", "vrloja": "VRLoja", "vrlubuntu": "VRLubuntu", "vrmarketing": "VRMarketing",
        "vrmaster": "VRMaster", "vrmasterweb": "VRMaster-web", "vrmaster-web": "VRMaster-web",
        "vrmasterfisco": "VRMasterfisco", "vrmensagem": "VRMensagem", "vrmicroterminalgertec": "VRMicroTerminalGertec",
        "vrmicroterminal": "VRMicroterminal", "vrmobile": "VRMobile", "vronline": "VROnline",
        "vroperadorbalanca": "VROperadorBalança", "vrpdvadmin": "VRPDVAdmin", "vrparticionador": "VRParticionador",
        "vrpdv": "VRPdv", "vrportal": "VRPortal", "vrrecebimento": "VRRecebimento", "vrsat": "VRSat",
        "vrsequencianfce": "VRSequenciaNFCE", "vrservicecontainer": "VRServiceContainer", "vrservicemanager": "VRServiceManager",
        "vrsetup": "VRSetup", "vrsetuppdv": "VRSetupPDV", "vrsitef": "VRSitef", "vrsoftware": "VRSoftware",
        "vrspringcommons": "VRSpringCommons", "vrsupertroco": "VRSuperTroco", "vrtestaperiferico": "VRTestaPeriferico",
        "vrtotem": "VRTotem", "vrunificadorsped": "VRUnificadorSped", "vrutil": "VRUtil", "vrvader": "VRVader",
        "vrvenda-media": "VRVenda-Media", "vrwms": "VRWMS", "vregalaxtouch": "VReGalaxTouch"
    })

    function canonicalName(raw) {
        if (!raw) return "";
        var clean = String(raw).trim();
        clean = clean.replace(/^(lib|libs)[\/\\]/i, "").replace(/\.jar$/i, "");
        var key = clean.toLowerCase();
        return iconMap[key] || "";
    }

    readonly property string canonical: canonicalName(appName)
    readonly property string officialPath: canonical ? ("file:///D:/Codex/4.5.95_com_PDV/img/" + canonical + ".ico") : ""
    readonly property string assetPath: canonical ? Qt.resolvedUrl("../../../assets/app_icons/" + canonical + ".ico") : ""

    property string activeSource: officialPath
    property bool hasIcon: canonical.length > 0 && !imageFailed
    property bool imageFailed: false

    onAppNameChanged: {
        imageFailed = false;
        activeSource = officialPath;
    }

    Rectangle {
        id: bgContainer
        visible: root.showBackground
        anchors.fill: parent
        radius: Theme.radiusSmall
        color: Theme.palette.chatBackground
        border.width: 1
        border.color: Theme.palette.chatBorder

        Image {
            id: iconImage
            anchors.centerIn: parent
            width: root.iconSize
            height: root.iconSize
            source: root.hasIcon ? root.activeSource : ""
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            visible: root.hasIcon && status === Image.Ready

            onStatusChanged: {
                if (status === Image.Error) {
                    if (root.activeSource === root.officialPath && root.assetPath.length > 0) {
                        root.activeSource = root.assetPath;
                    } else {
                        root.imageFailed = true;
                    }
                }
            }
        }

        VrLineIcon {
            anchors.centerIn: parent
            width: Math.round(root.iconSize * 0.75)
            height: Math.round(root.iconSize * 0.75)
            visible: !root.hasIcon || iconImage.status !== Image.Ready
            kind: root.fallbackKind
            foreground: root.fallbackForeground
        }
    }
}
