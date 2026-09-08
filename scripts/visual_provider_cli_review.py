"""Offline UI smoke for CLI installation; no real downloads or account login."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from visual_chat_review import (
    QApplication, QSettings, QObject, QTest, MarySettings, MaryDatabase,
    FrontendBridge, ChatBridge, StudioBridge, create_engine,
    _apply_application_font, find_items, Qt,
)
from vrsoft_extractor.mary.provider_cli import INSTALL_DOCS


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/provider-cli-install")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        settings = MarySettings(app_dir=root, root=root / "VRProject", old_root=root / "legacy")
        prefs = QSettings(str(root / "prefs.ini"), QSettings.IniFormat)
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        frontend = FrontendBridge(settings, prefs, theme_override="dark_orange", initial_page="Configurações")
        chat = ChatBridge(settings, db, prefs)
        studio = StudioBridge(settings, db, prefs)
        items = [dict(id=p, name=p.title(), available=False, enabled=True,
                      installSupported=True, installDocs=INSTALL_DOCS[p], command="",
                      accountStatus="Autenticação gerenciada pelo CLI")
                 for p in ("codex", "claude", "antigravity")]
        try:
            with patch.object(chat, "refreshModels"):
                engine = create_engine(frontend, chat, studio)
                assert engine.rootObjects()
                window = engine.rootObjects()[0]
                window.setWidth(1366)
                window.setHeight(768)
                QTest.qWait(150)
                window.findChild(QObject, "settingsPage").setProperty("tabIndex", 1)
                QTest.qWait(100)
                panel = window.findChild(QObject, "providerSettings")

                def item(name):
                    result = find_items(window.contentItem(), name)
                    assert result, name
                    return result[0]

                def click(name):
                    target = item(name)
                    assert target.isVisible() and target.isEnabled(), name
                    point = target.mapToScene(target.boundingRect().center()).toPoint()
                    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
                    QTest.qWait(50)

                for provider in ("codex", "claude", "antigravity"):
                    studio._providers = [dict(i) for i in items]
                    studio.providersChanged.emit()
                    panel.setProperty("selectedProvider", provider)
                    QTest.qWait(80)
                    with patch.object(studio, "installProviderCli") as install:
                        click("installProviderCli")
                        install.assert_called_once_with(provider)
                    window.grabWindow().save(str(output / f"{provider}-missing.png"))
                    selected = next(i for i in studio._providers if i["id"] == provider)
                    selected.update(runtimeState="installing", installMessage="Baixando o instalador oficial…")
                    studio.providersChanged.emit()
                    QTest.qWait(60)
                    assert not item("installProviderCli").isEnabled()
                    assert not item("refreshProviderRuntimes").isEnabled()
                    with patch.object(studio, "cancelProviderInstall") as cancel:
                        click("cancelProviderInstall")
                        cancel.assert_called_once_with(provider)
                    selected.update(runtimeState="error", installMessage="Não foi possível baixar o instalador oficial. Confira a conexão e tente novamente.")
                    studio.providersChanged.emit()
                    QTest.qWait(60)
                    assert item("installProviderCli").isEnabled()
                    assert "novamente" in item("installProviderCli").property("text")
                    window.grabWindow().save(str(output / f"{provider}-error.png"))
                    selected.update(runtimeState="installed", available=True, command="C:/CLI/provider.exe",
                                    installVersion="1.2.3", installMessage="CLI instalado e verificado. Entre na sua conta para usar nas conversas.")
                    studio.providersChanged.emit()
                    QTest.qWait(60)
                    assert not item("installProviderCli").isEnabled()
                    if provider != "antigravity":
                        with patch.object(studio, "openProviderLogin") as login:
                            click("providerCliLogin")
                            login.assert_called_once_with(provider)
                    window.grabWindow().save(str(output / f"{provider}-installed.png"))

                studio._providers = [dict(i) for i in items]
                studio.providersChanged.emit()
                for width, height in [(390, 844), (768, 1024)]:
                    window.setWidth(width)
                    window.setHeight(height)
                    for provider in ("codex", "claude", "antigravity"):
                        panel.setProperty("selectedProvider", provider)
                        QTest.qWait(100)
                        button = item("installProviderCli")
                        point = button.mapToScene(button.boundingRect().topRight())
                        assert point.x() <= width + 1, (provider, width, point.x())
                        window.grabWindow().save(str(output / f"{provider}-{width}.png"))
                assert not engine._qml_warnings, [w.toString() for w in engine._qml_warnings]
                print("PASS: three providers; install/cancel/login routing; busy, error and installed states; 390/768/1366px; no QML warnings")
                window.close()
                engine.deleteLater()
                QTest.qWait(30)
        finally:
            studio.close()
            chat.close()


if __name__ == "__main__":
    main()
