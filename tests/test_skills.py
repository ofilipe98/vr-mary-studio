from __future__ import annotations

from pathlib import Path

import pytest

from vrsoft_extractor.mary.skills.models import SkillDefinition
from vrsoft_extractor.mary.skills.adapters.base import assert_safe_skill_path, validate_skill_name, SkillSecurityError
from vrsoft_extractor.mary.skills.adapters.codex import CodexSkillAdapter
from vrsoft_extractor.mary.skills.adapters.claude import ClaudeSkillAdapter
from vrsoft_extractor.mary.skills.adapters.antigravity import AntigravitySkillAdapter
from vrsoft_extractor.mary.skills.adapters.opencode import OpenCodeSkillAdapter
from vrsoft_extractor.mary.skills.registry import SkillRegistry
from vrsoft_extractor.mary.db import MaryDatabase


def test_skill_definition_from_md_with_frontmatter():
    content = """---
name: code-reviewer
description: Analisador de código estático e revisor de PR
user-invocable: true
agent-invocable: true
metadata:
  version: "1.0"
---
# Instruções do Revisor
Analise o código procurando potenciais bugs.
"""
    skill = SkillDefinition.from_skill_md(
        skill_path="/test/.agents/skills/code-reviewer/SKILL.md",
        raw_content=content,
        provider="codex",
        scope="project",
    )
    assert skill.name == "code-reviewer"
    assert skill.description == "Analisador de código estático e revisor de PR"
    assert skill.user_invocable is True
    assert skill.agent_invocable is True
    assert skill.metadata.get("metadata", {}).get("version") == "1.0"
    assert "# Instruções do Revisor" in skill.instructions


def test_harness_isolation_p0_7():
    """P0-7: Skills não podem furar o isolamento entre General Harness e VR Harness."""
    vr_skill = SkillDefinition(
        id="vr:vr-expert",
        name="vr-expert",
        description="VR specific skill",
        instructions="# VR instructions",
        provider="app",
        scope="vr",
    )
    general_skill = SkillDefinition(
        id="app:general-helper",
        name="general-helper",
        description="General skill",
        instructions="# General instructions",
        provider="app",
        scope="project",
    )

    # VR skill must NOT be usable in General Harness
    assert not vr_skill.can_use_in_harness("general")
    assert vr_skill.can_use_in_harness("vr")

    # General skill can be used in both
    assert general_skill.can_use_in_harness("general")
    assert general_skill.can_use_in_harness("vr")

    # In registry filter
    registry = SkillRegistry()
    filtered_general = registry._filter_by_vr_mode([vr_skill, general_skill], vr_mode="off")
    assert len(filtered_general) == 1
    assert filtered_general[0].name == "general-helper"

    filtered_vr = registry._filter_by_vr_mode([vr_skill, general_skill], vr_mode="on")
    assert len(filtered_vr) == 2


def test_path_traversal_protection_p0_8(tmp_path: Path):
    """P0-8: Criação/edição de Skills deve bloquear path traversal e escrita fora das roots permitidas."""
    allowed_root = tmp_path / "workspace"
    allowed_root.mkdir()

    # Valid name passes
    assert validate_skill_name("valid-skill-1") == "valid-skill-1"
    assert validate_skill_name("another_skill") == "another_skill"

    # Path traversal attempts in name
    with pytest.raises(ValueError, match="inválido"):
        validate_skill_name("../sneaky")
    with pytest.raises(ValueError, match="inválido"):
        validate_skill_name("..\\sneaky")
    with pytest.raises(ValueError, match="inválido"):
        validate_skill_name("/etc/passwd")

    # Safe path validation
    target_inside = allowed_root / "skills" / "my-skill" / "SKILL.md"
    assert_safe_skill_path(target_inside, [allowed_root])

    # Path outside allowed roots must fail
    outside = tmp_path / "other" / "SKILL.md"
    with pytest.raises(SkillSecurityError, match="bloqueada"):
        assert_safe_skill_path(outside, [allowed_root])


def test_adapter_discovery_and_creation(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Codex adapter
    codex_adapter = CodexSkillAdapter()
    created = codex_adapter.create_skill(
        name="test-codex-skill",
        description="Codex skill desc",
        instructions="# Codex instructions",
        workspace=ws,
        scope="project",
    )
    assert created.name == "test-codex-skill"
    assert (ws / ".agents" / "skills" / "test-codex-skill" / "SKILL.md").exists()

    discovered = codex_adapter.discover_skills(ws, force_reload=True)
    assert any(s.name == "test-codex-skill" for s in discovered)

    # Claude adapter
    claude_adapter = ClaudeSkillAdapter()
    claude_skill = claude_adapter.create_skill(
        name="test-claude-skill",
        description="Claude skill desc",
        instructions="# Claude instructions",
        workspace=ws,
        scope="project",
    )
    assert claude_skill.name == "test-claude-skill"
    assert (ws / ".claude" / "skills" / "test-claude-skill" / "SKILL.md").exists()

    # Antigravity adapter
    ag_adapter = AntigravitySkillAdapter()
    ag_skill = ag_adapter.create_skill(
        name="test-ag-skill",
        description="AG skill desc",
        instructions="# AG instructions",
        workspace=ws,
        scope="project",
    )
    assert ag_skill.name == "test-ag-skill"
    assert (ws / ".gemini" / "skills" / "test-ag-skill" / "SKILL.md").exists()

    # OpenCode adapter
    oc_adapter = OpenCodeSkillAdapter()
    oc_skill = oc_adapter.create_skill(
        name="test-oc-skill",
        description="OC skill desc",
        instructions="# OC instructions",
        workspace=ws,
        scope="project",
    )
    assert oc_skill.name == "test-oc-skill"
    assert (ws / ".opencode" / "skills" / "test-oc-skill" / "SKILL.md").exists()


def test_skill_registry_crud_and_search(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    registry = SkillRegistry(app_skills_dir=ws / "app_skills")
    created = registry.create_skill(
        provider_name="codex",
        name="sql-helper",
        description="Auxiliar de queries SQL otimizadas",
        instructions="# SQL Instructions",
        workspace=ws,
        scope="project",
    )
    assert created.name == "sql-helper"

    # Search
    res = registry.search_skills("sql", provider_name="codex", workspace=ws)
    assert len(res) == 1
    assert res[0].name == "sql-helper"

    # Update
    updated = registry.update_skill(
        skill_id=created.id,
        instructions="# Updated SQL Instructions",
        description="Nova descrição SQL",
        provider_name="codex",
        workspace=ws,
    )
    assert updated.description == "Nova descrição SQL"
    assert "# Updated SQL Instructions" in updated.instructions


def test_database_message_skills_persistence(tmp_path: Path):
    db_file = tmp_path / "test_skills.db"
    db = MaryDatabase(db_file)

    # Create conversation and turn with skills
    cid = db.create_conversation("Teste Skills", "codex", "gpt-4o", workspace=tmp_path)

    skill_ref = {
        "id": "codex:project:refactor",
        "name": "refactor",
        "description": "Refactoring assistant",
        "provider": "codex",
        "scope": "project",
        "path": "/ws/.agents/skills/refactor/SKILL.md",
    }

    user_msg_id = db.begin_user_turn(
        conversation_id=cid,
        content="Refatore esta classe",
        skills=[skill_ref],
    )

    # Verify message skills retrieved
    skills = db.get_message_skills(user_msg_id)
    assert len(skills) == 1
    assert skills[0]["skill_name"] == "refactor"
    assert skills[0]["skill_id"] == "codex:project:refactor"
    assert skills[0]["provider"] == "codex"
    assert skills[0]["scope"] == "project"

    # Verify conversation message skills dict
    conv_skills = db.get_conversation_message_skills(cid)
    assert user_msg_id in conv_skills
    assert conv_skills[user_msg_id][0]["name"] == "refactor"
