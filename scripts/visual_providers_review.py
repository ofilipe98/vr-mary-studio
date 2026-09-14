"""Offline render of the real settings page; never logs in or changes user prefs."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from visual_chat_review import (
    QApplication, QSettings, QObject, QTest, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
    _apply_application_font, repaint_icons, find_items,
)
from PySide6.QtCore import Qt, QPoint


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
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
        items = [dict(id=p, name=n, enabled=True, available=True,
                      command="C:\\Users\\example\\AppData\\Local\\" + p + "\\bin\\" + p + ".exe",
                      accountStatus="Conta Google ainda não verificada" if p == "antigravity" else "Autenticação gerenciada pelo CLI",
                      description=d)
                 for p, n, d in [("codex", "Codex", "Codex App Server local · modelos, tools e Build integrado"),
                                 ("claude", "Claude", "Claude Code local · conversas e modelos Claude"),
                                 ("opencode", "OpenCode", "OpenCode local · modelos e sessões via CLI"),
                                 ("antigravity", "Antigravity", "Antigravity CLI · conta Google")]]
        studio._providers = items
        with patch.object(chat, "refreshModels"):
            engine = create_engine(frontend, chat, studio)
            assert engine.rootObjects(), [w.toString() for w in engine._qml_warnings]
            window = engine.rootObjects()[0]
            QTest.qWait(250)
            page = window.findChild(QObject, "settingsPage")
            page.setProperty("tabIndex", 1)
            QTest.qWait(100)
            panel = window.findChild(QObject, "providerSettings")
            studio._providers = [dict(i) for i in items]
            studio.providersChanged.emit()
            if panel.metaObject().indexOfProperty("narrow") >= 0:
                window.setWidth(1366)
                window.setHeight(768)
                QTest.qWait(150)
                def item(name):
                    found = find_items(window.contentItem(), name)
                    assert found, name
                    return found[0]
                def click(name):
                    target = item(name)
                    point = target.mapToScene(target.boundingRect().center()).toPoint()
                    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
                    QTest.qWait(80)
                click("providerRow_codex")
                assert panel.property("selectedProvider") == "codex"
                QTest.keyClick(window, Qt.Key_Down)
                assert panel.property("selectedProvider") == "claude"
                QTest.keyClick(window, Qt.Key_Down)
                assert panel.property("selectedProvider") == "opencode"
                QTest.keyClick(window, Qt.Key_Down)
                assert panel.property("selectedProvider") == "antigravity"
                with patch.object(studio, "setProviderEnabled") as toggle:
                    click("providerEnabledSwitch")
                    toggle.assert_called_once_with("antigravity", False)
                studio.providersChanged.emit()
                with patch.object(studio, "copyText") as copy:
                    click("copyProviderPath")
                    copy.assert_called_once_with(items[-1]["command"])
                with patch.object(studio, "openAntigravityLogin") as login:
                    click("providerGoogleLogin")
                    login.assert_called_once_with()
                with patch.object(studio, "validateAntigravityAccount") as validate:
                    click("validateGoogleAccount")
                    validate.assert_called_once_with()
                with patch.object(studio, "refreshProviders") as refresh:
                    click("refreshProviderRuntimes")
                    refresh.assert_called_once_with()
                panel.setProperty("refreshFeedback", "")
                with patch.object(studio, "setProviderDisplayName") as rename:
                    click("providerDisplayName")
                    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
                    item("providerDisplayName").setProperty("text", "Google Workspace")
                    QTest.keyClick(window, Qt.Key_Return)
                    rename.assert_called_once_with("antigravity", "Google Workspace")
                # The last enabled runtime cannot be disabled; the switch must
                # return to the bridge's authoritative state after rejection.
                for p in items:
                    prefs.setValue(f"providers/{p['id']}/enabled", p["id"] == "antigravity")
                studio.refreshProviders()
                click("providerEnabledSwitch")
                assert item("providerEnabledSwitch").property("checked") is True
                for p in items:
                    prefs.setValue(f"providers/{p['id']}/enabled", True)
                studio._providers = [dict(i) for i in items]
                studio.providersChanged.emit()
                for name in ["providerRow_antigravity", "providerEnabledSwitch", "providerDisplayName", "copyProviderPath"]:
                    target = item(name)
                    target.forceActiveFocus()
                    QTest.mouseMove(window, target.mapToScene(target.boundingRect().center()).toPoint())
                    QTest.qWait(180)
                    window.grabWindow().save(str(output / ("focus-" + name + ".png")))
                for p in items[:-1]:
                    click("providerRow_" + p["id"])
                    assert not item("providerGoogleLogin").isVisible()
                    window.grabWindow().save(str(output / (p["id"] + ".png")))
                click("providerRow_antigravity")
                item("providerRow_antigravity").setFocus(False)
                panel.forceActiveFocus()
                QTest.mouseMove(window, QPoint(1, 1))
                print("PASS: mouse selection, keyboard navigation, enable, copy, login, validation, runtime refresh")
                print("PASS: rename, rejected last-provider toggle, all provider details, focus and hover")
            scenarios = [
                ("unauthenticated", {}),
                ("ready", {"accountStatus": "Conta Google validada com uma resposta real"}),
                ("missing", {"available": False, "command": ""}),
                ("disabled", {"enabled": False}),
                ("updating", {"runtimeState": "updating"}),
                ("installing", {"runtimeState": "installing", "available": False, "command": ""}),
                ("validating", {"accountStatus": "Validando conta Google…"}),
                ("auth-error", {"accountStatus": "Não foi possível validar a conta. Abra o CLI e confira o login e a cota."}),
                ("long-path", {"command": "C:\\Users\\example\\" + "a-very-long-directory\\" * 20 + "agy.exe"}),
                ("six-providers", {}),
            ]
            for width, height in [(1366, 768), (1920, 1080), (768, 1024), (390, 844)]:
                window.setWidth(width)
                window.setHeight(height)
                for name, changes in scenarios:
                    studio._providers = [dict(i) for i in items]
                    studio._providers[-1].update(changes)
                    if name == "six-providers":
                        studio._providers += [dict(items[0], id="fixture-a", name="Runtime de demonstração A"), dict(items[0], id="fixture-b", name="Runtime de demonstração B")]
                    studio.providersChanged.emit()
                    QTest.qWait(100)
                    panel.forceActiveFocus()
                    QTest.mouseMove(window, QPoint(1, 1))
                    assert window.width() == width and window.height() == height
                    if panel.metaObject().indexOfProperty("narrow") >= 0:
                        point = panel.mapToScene(panel.boundingRect().topRight())
                        assert point.x() <= width + 1, (name, width, point.x())
                        if name == "validating":
                            assert not item("validateGoogleAccount").isEnabled()
                            assert not item("providerGoogleLogin").isEnabled()
                        if name == "missing":
                            assert not item("providerGoogleLogin").isEnabled()
                    repaint_icons(window.contentItem())
                    QTest.qWait(50)
                    window.grabWindow().save(str(output / f"{name}-{width}x{height}.png"))
                if panel.metaObject().indexOfProperty("narrow") >= 0 and width == 390:
                    scroll = item("providerDetailsScroll").property("contentItem")
                    scroll.setProperty("contentY", max(0, scroll.property("contentHeight") - scroll.height()))
                    QTest.qWait(100)
                    window.grabWindow().save(str(output / "mobile-bottom.png"))
            frontend.setTheme("light")
            window.setWidth(1366)
            window.setHeight(768)
            QTest.qWait(200)
            window.grabWindow().save(str(output / "light.png"))
            warnings = [w.toString() for w in engine._qml_warnings]
            (output / "qml-warnings.txt").write_text("\n".join(warnings), encoding="utf-8")
            assert not warnings, warnings
            print(f"Captured 41 states. QML warnings: {len(warnings)}. {output.resolve()}")
            window.close()
        studio.close()
        chat.close()
        engine.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()
