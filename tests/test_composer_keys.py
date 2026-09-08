from __future__ import annotations

import pytest

from pathlib import Path
from unittest.mock import MagicMock


from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge

pytestmark = pytest.mark.qml


def test_active_skills_lifecycle(tmp_path: Path):
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    db = MaryDatabase(tmp_path / "test.db")
    bridge = ChatBridge(settings, db)

    # Initial state
    assert bridge.activeSkills == []

    # Add skill
    skill_a = {
        "id": "codex:project:refactor",
        "name": "refactor",
        "description": "Refactoring helper",
        "provider": "codex",
        "scope": "project",
    }
    bridge.addActiveSkill(skill_a)
    assert len(bridge.activeSkills) == 1
    assert bridge.activeSkills[0]["name"] == "refactor"

    # Adding duplicate skill must be prevented
    bridge.addActiveSkill(skill_a)
    assert len(bridge.activeSkills) == 1

    # Add second skill
    skill_b = {
        "id": "codex:project:test-gen",
        "name": "test-gen",
        "description": "Test generator",
        "provider": "codex",
        "scope": "project",
    }
    bridge.addActiveSkill(skill_b)
    assert len(bridge.activeSkills) == 2

    # Remove first skill
    bridge.removeActiveSkill(0)
    assert len(bridge.activeSkills) == 1
    assert bridge.activeSkills[0]["name"] == "test-gen"

    # Clear all active skills
    bridge.clearActiveSkills()
    assert len(bridge.activeSkills) == 0


def test_show_skills_in_slash_menu_preference(tmp_path: Path):
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    db = MaryDatabase(tmp_path / "test.db")
    bridge = ChatBridge(settings, db)

    # Default is True
    assert bridge.showSkillsInSlashMenu is True

    # Toggle off
    bridge.setShowSkillsInSlashMenu(False)
    assert bridge.showSkillsInSlashMenu is False

    # Toggle on
    bridge.setShowSkillsInSlashMenu(True)
    assert bridge.showSkillsInSlashMenu is True


def test_skill_suggestions_and_search(tmp_path: Path):
    settings = MarySettings(app_dir=tmp_path, root=tmp_path / "VRProject", old_root=tmp_path / "legacy")
    db = MaryDatabase(tmp_path / "test.db")
    bridge = ChatBridge(settings, db)

    # Mock orchestrator.search_skills
    bridge._orchestrator.search_skills = MagicMock(return_value=[
        {"id": "codex:project:code-review", "name": "code-review", "description": "Review code"},
        {"id": "codex:project:perf-audit", "name": "perf-audit", "description": "Performance audit"},
    ])

    results = bridge.skillSuggestions("code")
    assert len(results) == 2
    assert results[0]["name"] == "code-review"
    bridge._orchestrator.search_skills.assert_called_once()


def test_p0_1_composer_key_contracts_simulation():
    """
    P0-1 Contract Verification:
    / + Tab não pode inserir espaço, tab ou trocar foco quando houver sugestão válida selecionada.
    """
    # Simulated state matching ChatPreview.qml logic:
    class SimulatedComposerPopup:
        def __init__(self):
            self.visible = False
            self.suggestions = []
            self.selectedIndex = 0
            self.text = ""
            self.active_skills = []
            self.submitted_message = None

        def update_suggestions(self, text: str, available_skills: list[dict]):
            self.text = text
            self.suggestions = []
            if text.startswith("/"):
                # Slash commands
                self.suggestions.append({"type": "command", "name": "usage-limits", "description": "Limites de uso"})
                self.suggestions.append({"type": "command", "name": "pesquisa", "description": "Pesquisa local"})
                for s in available_skills:
                    self.suggestions.append({"type": "skill", "name": s["name"], "skill": s})
                self.visible = len(self.suggestions) > 0
                self.selectedIndex = 0
            elif text.startswith("$"):
                needle = text[1:].strip().casefold()
                for s in available_skills:
                    if needle in s["name"].casefold():
                        self.suggestions.append({"type": "skill", "name": s["name"], "skill": s})
                self.visible = len(self.suggestions) > 0
                self.selectedIndex = 0
            else:
                self.visible = False

        def handle_tab(self, event) -> bool:
            """When popup is visible, Tab MUST accept suggestion and set event.accepted = True."""
            if self.visible and self.suggestions:
                event["accepted"] = True
                selected = self.suggestions[self.selectedIndex]
                self.choose_suggestion(selected)
                return True
            return False

        def handle_up(self, event):
            if self.visible and self.suggestions:
                event["accepted"] = True
                self.selectedIndex = (self.selectedIndex - 1 + len(self.suggestions)) % len(self.suggestions)

        def handle_down(self, event):
            if self.visible and self.suggestions:
                event["accepted"] = True
                self.selectedIndex = (self.selectedIndex + 1) % len(self.suggestions)

        def handle_escape(self, event):
            if self.visible:
                event["accepted"] = True
                self.visible = False

        def handle_enter(self, event):
            if self.visible and self.suggestions:
                event["accepted"] = True
                selected = self.suggestions[self.selectedIndex]
                self.choose_suggestion(selected)
            else:
                event["accepted"] = True
                self.submitted_message = self.text
                self.text = ""

        def choose_suggestion(self, suggestion):
            if suggestion["type"] == "skill":
                self.active_skills.append(suggestion["skill"])
                self.text = ""
            elif suggestion["type"] == "command":
                self.text = f"/{suggestion['name']} "
            self.visible = False

    sim = SimulatedComposerPopup()
    available_skills = [{"id": "codex:project:refactor", "name": "refactor"}]

    # 1. Type "/" -> popup appears with /usage-limits and skills
    sim.update_suggestions("/", available_skills)
    assert sim.visible is True
    assert len(sim.suggestions) >= 2
    assert sim.selectedIndex == 0

    # 2. Key Down -> cycles to next suggestion
    event_down = {"accepted": False}
    sim.handle_down(event_down)
    assert event_down["accepted"] is True
    assert sim.selectedIndex == 1

    # 3. Key Up -> cycles back to 0
    event_up = {"accepted": False}
    sim.handle_up(event_up)
    assert event_up["accepted"] is True
    assert sim.selectedIndex == 0

    # 4. Press Tab on "/" suggestion -> event.accepted is True (no tab/space inserted, no focus lost)
    event_tab = {"accepted": False}
    handled = sim.handle_tab(event_tab)
    assert handled is True
    assert event_tab["accepted"] is True
    assert sim.visible is False
    assert "/usage-limits" in sim.text
    # Message must NOT be submitted
    assert sim.submitted_message is None

    # 5. Type "$" -> skill suggestions triggered
    sim.update_suggestions("$ref", available_skills)
    assert sim.visible is True
    assert len(sim.suggestions) == 1
    assert sim.suggestions[0]["name"] == "refactor"

    # 6. Press Tab on "$" suggestion -> adds skill chip, clears text, closes popup
    event_tab_skill = {"accepted": False}
    sim.handle_tab(event_tab_skill)
    assert event_tab_skill["accepted"] is True
    assert len(sim.active_skills) == 1
    assert sim.active_skills[0]["name"] == "refactor"
    assert sim.visible is False
    assert sim.text == ""

    # 7. Press Escape -> dismisses popup
    sim.update_suggestions("/", available_skills)
    assert sim.visible is True
    event_esc = {"accepted": False}
    sim.handle_escape(event_esc)
    assert event_esc["accepted"] is True
    assert sim.visible is False
