import QtQuick
import QtQuick.Layouts
import "../../theme"
ColumnLayout {
    id: root
    spacing: 12
    function themeById(id) {
        var themes = frontend.availableThemes
        for(var i=0;i<themes.length;i++) if(themes[i].id===id) return themes[i]
        return null
    }
    readonly property var cards: {
        var result=[]
        var ids=["t3-code","t3-chat","grove","ocean","ember","iris"]
        for(var i=0;i<ids.length;i++) {
            var dark=themeById(ids[i]), light=themeById(ids[i]+"-light")
            result.push({id:ids[i], name:dark.name, light:light, dark:dark, builtIn:true})
        }
        var themes=frontend.availableThemes
        for(var j=0;j<themes.length;j++) {
            var t=themes[j]
            if(!t.builtIn) {
                var group = t.collection ? result.find(card => card.id === t.collection) : null
                if(group) group[t.appearance] = t
                else result.push({id:t.collection || t.id,name:t.name,light:t.appearance==="light"?t:null,dark:t.appearance==="dark"?t:null,builtIn:false})
            }
        }
        return result
    }
    function editTheme(theme, editing) {
        editorModal.isEditing=editing
        editorModal.targetThemeId=editing?theme.id:""
        editorModal.themeName=editing?theme.name:"Tema personalizado"
        editorModal.themeAppearance=theme.appearance
        var p=theme.palette
        editorModal.colorBackground=p.background
        editorModal.colorSurface=p.surface
        editorModal.colorBorder=p.border
        editorModal.colorAccent=p.accessibleOrange
        editorModal.colorText=p.text
        editorModal.colorMuted=p.mutedText
        editorModal.open()
    }
    function duplicateTheme(theme) {
        var id=frontend.duplicateTheme(theme.id,theme.name+" (cópia)")
        var copy=themeById(id)
        if(copy) editTheme(copy,true)
    }
    function deleteCard(card) {
        var ids = [card.light, card.dark].filter(t => t !== null).map(t => t.id)
        for(var i=0;i<ids.length;i++) frontend.deleteCustomTheme(ids[i])
    }
    GridLayout {
        Layout.fillWidth: true; Layout.leftMargin: 16; Layout.rightMargin: 16
        columns: root.width < 460 * Theme.textScale ? 2 : 3
        columnSpacing: 8; rowSpacing: 10
        Text { text: "Temas"; color: Theme.palette.text; opacity: .7; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); Layout.fillWidth: true; Layout.columnSpan: parent.columns === 2 ? 2 : 1 }
        AppearanceAction {
            objectName: "createThemeButton"; text: "Criar tema"; iconKind: "paintbrush"
            onClicked: root.editTheme({appearance:frontend.resolvedAppearance,palette:frontend.palette},false)
        }
        AppearanceAction { objectName: "importThemeButton"; text: "Adicionar tema"; iconKind: "plus"; onClicked: importModal.open() }
    }
    GridLayout {
        Layout.fillWidth: true
        columns: root.width >= 700 ? 3 : root.width >= 460 ? 2 : 1
        rowSpacing: 8; columnSpacing: 8
        Repeater {
            model: root.cards
            ThemeCard {
                required property var modelData
                themeId: modelData.id; themeName: modelData.name
                lightTheme: modelData.light; darkTheme: modelData.dark; isBuiltIn: modelData.builtIn
                onEditRequested: root.editTheme(activeTheme,true)
                onDuplicateRequested: root.duplicateTheme(activeTheme)
                onExportRequested: {
                    exportModal.jsonContent=frontend.exportThemeJson(activeTheme.id)
                    exportModal.themeName=modelData.name; exportModal.open()
                }
                onDeleteRequested: root.deleteCard(modelData)
            }
        }
    }
    ThemeEditorModal { id: editorModal; objectName: "themeEditorModal" }
    ThemeImportModal { id: importModal; objectName: "themeImportModal" }
    ThemeExportModal { id: exportModal; objectName: "themeExportModal" }
}
