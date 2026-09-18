import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge


@pytest.fixture
def chat_factory(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "workspace", old_root=tmp_path / "old")
    database = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    bridges = []

    def create():
        preferences = QSettings(str(tmp_path / "preferences.ini"), QSettings.IniFormat)
        chat = ChatBridge(settings, database, preferences)
        bridges.append(chat)
        return chat

    yield create
    for chat in reversed(bridges):
        chat.close()
    app.processEvents()


@pytest.mark.parametrize("customization", [{"kind": "layers"}, {"emoji": "\U0001f680"}, {"text": "AB"}, {}])
def test_picker_replaces_uploaded_image_and_persists(chat_factory, tmp_path, monkeypatch, customization):
    chat = chat_factory()
    project = tmp_path / "Client"
    project.mkdir()
    chat.browseProjectFolder(str(project))
    chat.addCurrentProjectFolder()
    index = chat.currentProjectIndex
    image = str(tmp_path / "icon.png")
    monkeypatch.setattr(
        "vrsoft_extractor.mary.frontend.bridges.conversations.QFileDialog.getOpenFileName",
        lambda *args: (image, ""),
    )
    assert chat.chooseProjectIcon(index) == image
    assert chat.projectItems[index]["icon"] == image
    assert chat.applyProjectIcon(index, **customization)
    assert chat.projectItems[index]["icon"] == ""
    assert chat.renameProject(index, "Renamed")
    restored = chat_factory()
    item = next(item for item in restored.projectItems if item["path"] == str(project))
    assert item["label"] == "Renamed"
    assert item["icon"] == ""
    for field in ("kind", "emoji", "text"):
        assert item["icon" + field.title()] == customization.get(field, "")


def test_set_project_icon_emoji_clears_conflicts(chat_factory, tmp_path, monkeypatch):
    chat = chat_factory()
    project = tmp_path / "Demo"
    project.mkdir()
    chat.browseProjectFolder(str(project))
    chat.addCurrentProjectFolder()
    index = chat.currentProjectIndex
    image = str(tmp_path / "custom.png")
    monkeypatch.setattr(
        "vrsoft_extractor.mary.frontend.bridges.conversations.QFileDialog.getOpenFileName",
        lambda *args: (image, ""),
    )
    chat.chooseProjectIcon(index)
    assert chat.projectItems[index]["icon"] == image

    # Setting emoji clears image, kind and text
    assert chat.setProjectIconEmoji(index, "\U0001f600")
    assert chat.projectItems[index]["icon"] == ""
    assert chat.projectItems[index]["iconEmoji"] == "\U0001f600"
    assert chat.projectItems[index]["iconKind"] == ""
    assert chat.projectItems[index]["iconText"] == ""

    # Setting kind clears emoji
    assert chat.setProjectIconKind(index, "cube")
    assert chat.projectItems[index]["iconKind"] == "cube"
    assert chat.projectItems[index]["iconEmoji"] == ""

    # Setting text clears kind
    assert chat.setProjectIconText(index, "VR")
    assert chat.projectItems[index]["iconText"] == "VR"
    assert chat.projectItems[index]["iconKind"] == ""
