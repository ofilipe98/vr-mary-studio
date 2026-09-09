"""Offline render and warning checker for all tabs in SettingsPage."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import ExitStack
import json
import zipfile

from visual_chat_review import (
    QApplication, QSettings, QObject, QTest, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
    _apply_application_font, repaint_icons, find_items,
)
from PySide6.QtCore import QPointF, Qt

def check_geometry(item, viewport_width):
    """Catch collapsed cards and overlapping layout children, even without QML warnings."""
    if not item.isVisible():
        return
    name = item.objectName() or item.metaObject().className()
    if item.objectName().startswith("vrUltra") and item.objectName().endswith("Card"):
        assert item.height() > 30, (name, "collapsed card", item.height())
        for child in item.childItems():
            assert child.y() + child.height() <= item.height() + 1, (name, "content outside card")
    if "Layout" in item.metaObject().className():
        children = [c for c in item.childItems() if c.isVisible() and c.width() > 1 and c.height() > 1]
        for index, child in enumerate(children):
            for other in children[index + 1:]:
                overlap_x = min(child.x() + child.width(), other.x() + other.width()) - max(child.x(), other.x())
                overlap_y = min(child.y() + child.height(), other.y() + other.height()) - max(child.y(), other.y())
                assert overlap_x < 1 or overlap_y < 1, (name, "overlap", child.objectName(), other.objectName())
    if item.objectName() in {"rootField", "movideskEmail", "movideskPassword", "endooEmail", "endooPassword", "interfaceFontCombo", "browserZoomCombo", "vrUltraAddReleaseButton"}:
        left = item.mapToScene(QPointF(0, 0)).x()
        assert left >= -1 and left + item.width() <= viewport_width + 1, (name, "horizontal overflow", left, item.width())
        assert item.height() >= 30, (name, "collapsed control")
    for child in item.childItems():
        check_geometry(child, viewport_width)


def wait_for(predicate):
    import time
    deadline = time.monotonic() + 10
    while not predicate():
        QTest.qWait(10)
        time.sleep(.005)
        assert time.monotonic() < deadline, "Background UI operation timed out"


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".test-tmp/settings_review")
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = MarySettings(app_dir=root, root=root / "VRProject", old_root=root / "legacy")
        prefs = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Configurações")
        frontend.setReduceMotion(True)
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)

        from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog
        catalog = ErpReleaseCatalog(settings.root, expected_jar_count=1)
        for number, major in enumerate((1, 2, 2)):
            source = root / f"package-{number}"
            source.mkdir()
            with zipfile.ZipFile(source / "VRApp.jar", "w") as jar:
                jar.writestr("META-INF/MANIFEST.MF", "Main-Class: App\n")
                jar.writestr("vrapp.properties", f"versao.major={major}\nversao.minor=0\nversao.release=0\nversao.build=0\nversao.beta=0\n")
                jar.writestr("App.class", f"fixture bytecode {number}")
            catalog.import_release(f"package-{number}", source)
        from vrsoft_extractor.mary.jvm_batches import DecompilationBatchPlanner, DecompilationBatchExecutor
        from vrsoft_extractor.mary.jvm_toolchain import DecompileResult
        from vrsoft_extractor.mary.code_index import JavaCodeIndex
        class PreviewAdapter:
            name = "vineflower"
            def decompile(self, request):
                request.output_dir.mkdir(parents=True, exist_ok=True)
                (request.output_dir / "App.java").write_text(
                    "public class App {\n    public int value() { return 2; }\n}\n", encoding="utf-8")
                return DecompileResult(tool=self.name, status="completed", duration_ms=1,
                    exit_code=0, output_dir=str(request.output_dir))
        for number in range(3):
            plan = DecompilationBatchPlanner(settings.root, catalog=catalog).plan(f"package-{number}")
            DecompilationBatchExecutor(settings.root, catalog=catalog, adapters=(PreviewAdapter(),)).run(plan["plan_id"], limit=10)
            JavaCodeIndex(settings.root, catalog=catalog).index_plan(plan["plan_id"])
        chat.refreshApplicationsCatalog()

        items = [dict(id=p, name=n, enabled=True, available=True,
                      command="C:\\Users\\example\\AppData\\Local\\" + p + "\\bin\\" + p + ".exe",
                      accountStatus="Autenticação OK",
                      description=d)
                 for p, n, d in [("codex", "Codex", "Codex App Server local"),
                                 ("antigravity", "Antigravity", "Antigravity CLI")]]
        studio._providers = items

        with ExitStack() as patches:
            for target, method in [(chat, "refreshModels"), (studio, "refreshProviders")]:
                patches.enter_context(patch.object(target, method))
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [w.toString() for w in engine._qml_warnings]
            window = engine.rootObjects()[0]
            window.setWidth(1280)
            window.setHeight(820)
            QTest.qWait(300)

            page = window.findChild(QObject, "settingsPage")
            assert page is not None, "settingsPage not found"

            tab_names = ["0_geral", "1_provedores", "2_vr_ultra", "3_aplicativos", "4_aparencia", "5_browser", "6_arquivados", "7_skills"]

            scenarios = [(1280, 820, "100"), (1920, 1080, "100"), (768, 1024, "100"), (390, 844, "100"), (1280, 820, "150")]
            captures = []
            for theme in ["dark_orange", "light"]:
                frontend.setTheme(theme)
                for width, height, scale in scenarios:
                    window.setWidth(width)
                    window.setHeight(height)
                    frontend.setUiScale(scale)
                    for idx, name in enumerate(tab_names):
                        page.setProperty("tabIndex", idx)
                        QTest.qWait(120)
                        app.processEvents()
                        scroll_name = {0: "generalScroll", 2: "vrUltraSettingsScroll", 3: "appsSettingsScroll", 4: "appearanceSettingsScroll", 5: "browserSettingsScroll"}.get(idx)
                        scroll = window.findChild(QObject, scroll_name) if scroll_name else None
                        flick = scroll.property("contentItem") if scroll else None
                        if flick:
                            flick.setProperty("contentY", 0)
                        QTest.qWait(30)
                        if idx != 1:
                            try:
                                check_geometry(page, width)
                            except AssertionError:
                                window.grabWindow().save(str(out_dir / "geometry-failure.png"))
                                raise
                        for position in (["top", "bottom"] if flick and flick.property("contentHeight") > flick.property("height") else ["top"]):
                            if position == "bottom":
                                flick.setProperty("contentY", max(0, flick.property("contentHeight") - flick.property("height")))
                            repaint_icons(window.contentItem())
                            QTest.qWait(25)
                            filename = f"{theme}_{width}x{height}_{scale}_{name}_{position}.png"
                            assert window.grabWindow().save(str(out_dir / filename))
                            captures.append(filename)
                        if idx == 6:
                            archive_list = window.findChild(QObject, "archivedList")
                            assert archive_list.property("height") > 100, "Archive list lost its available height"
                    print(f"Verified all tabs: {theme}, {width}x{height}, scale {scale}%", flush=True)

            # Navigate the populated catalog and all version panels, including variants.
            page.setProperty("tabIndex", 3)
            QTest.qWait(100)
            apps_page = window.findChild(QObject, "appsSettingsPage")
            chat.selectApplication("vrapp")
            assert len(chat.appVersions) == 2
            for theme in ["dark_orange", "light"]:
                frontend.setTheme(theme)
                for width, scale in [(1280, "100"), (390, "100"), (1280, "150")]:
                    window.setWidth(width)
                    window.setHeight(900)
                    frontend.setUiScale(scale)
                    chat.selectAppVersion(chat.appVersions[0]["version"])
                    assert len(chat.appVariants) == 2
                    chat.selectAppVariant(chat.appVariants[1]["variant_id"])
                    apps_page.setProperty("navigationLevel", 2)
                    chat.selectAppOrigin("package-1" if chat.selectedAppVariantId == catalog.apps_store.get_package("package-1")["composition"][0]["variant_id"] else "package-2")
                    for panel in range(5):
                        apps_page.setProperty("versionSubTab", panel)
                        if panel == 4:
                            assert chat.loadApplicationSources("", 0, "")
                            wait_for(lambda: chat._app_sources_thread is None)
                            assert chat.applicationSources.get("sources"), chat.applicationSources
                            key = chat.applicationSources["sources"][0]["source_key"]
                            assert chat.loadApplicationSources("", 0, key)
                            wait_for(lambda: chat._app_sources_thread is None)
                            assert "public class App" in chat.applicationSources["body"]
                        QTest.qWait(100)
                        scroll = window.findChild(QObject, "appsSettingsScroll")
                        flick = scroll.property("contentItem")
                        check_geometry(page, width)
                        for position in ("top", "bottom"):
                            flick.setProperty("contentY", 0 if position == "top" else max(0, flick.property("contentHeight") - flick.property("height")))
                            QTest.qWait(30)
                            filename = f"apps-version-{theme}-{width}-{scale}-{panel}-{position}.png"
                            assert window.grabWindow().save(str(out_dir / filename))
                            captures.append(filename)
            # Exercise the real application context action, then inspect preview and Ultra.
            window.findChild(QObject, "useApplicationInUltra").clicked.emit()
            assert len(chat.ultraApplicationContexts) == 1 and chat.ultraApplicationContextsReady
            assert chat.previewApplicationImport(str(root / "package-1"), False, "")
            wait_for(lambda: not chat.releaseSnapshotRunning)
            assert chat.applicationImportPreview["state"] == "ready"
            apps_page.setProperty("navigationLevel", 0)
            for theme in ["dark_orange", "light"]:
                frontend.setTheme(theme)
                for width in [1280, 390]:
                    window.setWidth(width)
                    frontend.setUiScale("100")
                    for tab, label in [(3, "import-preview"), (2, "ultra-context")]:
                        page.setProperty("tabIndex", tab)
                        QTest.qWait(100)
                        scroll = window.findChild(QObject, "appsSettingsScroll" if tab == 3 else "vrUltraSettingsScroll")
                        flick = scroll.property("contentItem")
                        flick.setProperty("contentY", 0 if tab == 3 else max(0, flick.property("contentHeight") - flick.property("height")))
                        QTest.qWait(50)
                        check_geometry(page, width)
                        filename = f"{label}-{theme}-{width}.png"
                        assert window.grabWindow().save(str(out_dir / filename))
                        captures.append(filename)
            chat.cancelApplicationImport()
            page.setProperty("tabIndex", 3)
            timeout_picker = window.findChild(QObject, "vrUltraCodeProcessingTimeoutPicker")
            timeout_picker.activated.emit(0)
            assert chat.codeProcessingTimeoutSeconds == chat.codeProcessingTimeoutOptions[0]["value"]
            cpu_picker = window.findChild(QObject, "vrUltraCodeProcessingCpuPicker")
            cpu_picker.activated.emit(0)
            assert chat.codeProcessingMaxCpuCores == chat.codeProcessingCpuCoreOptions[0]["value"]
            chat._code_processing_attention_batches = [
                {"batchId": "failed-1", "label": "VRApp.jar · lote 1", "jar": "VRApp.jar"},
                {"batchId": "failed-2", "label": "VRApp.jar · lote 2", "jar": "VRApp.jar"},
            ]
            chat._code_processing_can_retry = True
            chat.stateChanged.emit()
            QTest.qWait(20)
            window.findChild(QObject, "vrUltraCodeProcessingRetryPicker").activated.emit(1)
            assert chat.codeProcessingRetryBatch == "failed-2"

            # Exercise real QML controls and local persistence with disposable preferences.
            window.setWidth(1280)
            window.setHeight(820)
            frontend.setUiScale("100")
            page.setProperty("tabIndex", 2)
            QTest.qWait(80)
            toggle = window.findChild(QObject, "vrUltraSeniorProfileToggle")
            toggle.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Space)
            assert chat.seniorProfileEnabled
            picker = window.findChild(QObject, "vrUltraResponseModePicker")
            picker.activated.emit(2)
            assert chat.vrResponseMode == "support"
            page.setProperty("tabIndex", 5)
            window.findChild(QObject, "browserZoomCombo").activated.emit(4)
            assert frontend.browserZoom == "125"

            # Populated, filtered, and restored archive states.
            cid = db.create_conversation("Revisão visual de configurações", "codex", "gpt-5.6", settings.root)
            chat._orchestrator.archive(cid)
            studio.refreshArchived("")
            page.setProperty("tabIndex", 6)
            for width in [1280, 390]:
                window.setWidth(width)
                QTest.qWait(120)
                check_geometry(page, width)
                filename = f"archive-populated-{width}.png"
                assert window.grabWindow().save(str(out_dir / filename))
                captures.append(filename)
            search = window.findChild(QObject, "archivedSearch")
            search.setProperty("text", "sem correspondencia")
            QTest.qWait(240)
            assert archive_list.property("count") == 0
            search.setProperty("text", "")
            QTest.qWait(240)
            assert archive_list.property("count") == 1
            row = find_items(window.contentItem(), "archivedConversationRow")[0]
            def descendants(item):
                for child in item.childItems():
                    yield child
                    yield from descendants(child)
            restore = next(child for child in descendants(row) if child.property("text") == "Restaurar")
            restore.forceActiveFocus()
            QTest.keyClick(window, Qt.Key_Space)
            QTest.qWait(80)
            assert archive_list.property("count") == 0

            print(f"Total QML warnings: {len(engine._qml_warnings)}")
            for w in engine._qml_warnings:
                print("WARNING:", w.toString())
            assert len(engine._qml_warnings) == 0, f"Found {len(engine._qml_warnings)} warnings!"
            (out_dir / "results.json").write_text(json.dumps({"captures": captures, "qml_warnings": 0, "geometry": "passed", "controls_and_archive": "passed"}, indent=2), encoding="utf-8")
            print("SUCCESS: All tabs rendered without warnings!")
            window.close()
            studio.close()
            chat.close()

if __name__ == "__main__":
    main()
