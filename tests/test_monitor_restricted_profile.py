from __future__ import annotations

import pytest

from vrsoft_extractor.mary.models import ConversationOptions, approval_preset
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.provider_adapters.antigravity import AntigravityProvider
from vrsoft_extractor.mary.provider_adapters.base import ProviderError, _opencode_environment
from vrsoft_extractor.mary.provider_adapters.claude import ClaudeProvider
from vrsoft_extractor.mary.provider_adapters.codex import CodexProvider
from vrsoft_extractor.mary.provider_adapters.opencode import OpenCodeProvider


def monitor_options() -> ConversationOptions:
    return ConversationOptions(
        approval_profile=ConversationOptions.MONITOR_APPROVAL_PROFILE,
        monitor_mode=True,
    )


def test_unknown_profile_fails_closed_without_full_access() -> None:
    options = ConversationOptions(approval_profile="future-or-misspelled")
    assert options.approval_profile == "supervised"

    with pytest.raises(ValueError, match="Unsupported approval profile"):
        approval_preset("future-or-misspelled")
    with pytest.raises(ValueError, match="Unsupported approval profile"):
        _opencode_environment("future-or-misspelled")


def test_monitor_profile_requires_explicit_non_persisted_mode() -> None:
    with pytest.raises(ValueError, match="requires monitor mode"):
        ConversationOptions(approval_profile=ConversationOptions.MONITOR_APPROVAL_PROFILE)
    with pytest.raises(ValueError, match="requires the monitor_restricted"):
        ConversationOptions(monitor_mode=True)
    with pytest.raises(ValueError, match="requires monitor mode"):
        ConversationOptions.from_mapping(
            {"approval_profile": ConversationOptions.MONITOR_APPROVAL_PROFILE}
        )

    assert monitor_options().monitor_mode is True


@pytest.mark.parametrize(
    "provider",
    [CodexProvider(), ClaudeProvider(), OpenCodeProvider(), AntigravityProvider()],
    ids=["codex", "claude", "opencode", "antigravity"],
)
def test_standard_providers_refuse_monitor_profile_before_startup(provider, tmp_path) -> None:
    with pytest.raises(ProviderError, match="adapter dedicado"):
        provider.start_conversation(
            "monitor-conversation",
            "model",
            "medium",
            tmp_path,
            monitor_options(),
        )


def test_monitor_profile_has_no_generic_provider_preset() -> None:
    with pytest.raises(ValueError, match="dedicated Monitor adapter"):
        approval_preset(ConversationOptions.MONITOR_APPROVAL_PROFILE)


def test_persistence_normalizes_unknown_and_rejects_monitor_profile(tmp_path) -> None:
    database = MaryDatabase(tmp_path / "mary.db", root=tmp_path)
    conversation_id = database.create_conversation(
        "Profile boundary",
        "codex",
        "model",
        tmp_path,
        approval_profile="misspelled-profile",
    )
    assert database.get_conversation(conversation_id)["approval_profile"] == "supervised"

    database.update_conversation(conversation_id, approval_profile="full_access")
    with pytest.raises(ValueError, match="requires monitor mode"):
        database.update_conversation(
            conversation_id,
            approval_profile=ConversationOptions.MONITOR_APPROVAL_PROFILE,
        )
    assert database.get_conversation(conversation_id)["approval_profile"] == "full_access"
