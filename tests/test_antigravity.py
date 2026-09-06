import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vrsoft_extractor.mary.antigravity import AntigravityProvider, google_account_environment
from vrsoft_extractor.mary.providers import ProviderError, provider_registry


class Process:
    def __init__(self, events, code=0):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("\n".join(json.dumps(x) for x in events))
        self.stderr = io.StringIO()
        self.code = code

    def wait(self):
        return self.code

    def poll(self):
        return self.code


def test_stream_resume_usage_and_no_duplicate_final():
    provider = AntigravityProvider()
    process = Process([
        {"event": "init", "conversation_id": "native-google-id"},
        {"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "OK"}},
        {"event": "result", "result": {"status": "SUCCESS", "response": "OK", "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}},
    ])
    provider._active["chat"] = process
    events = []
    provider._consume("chat", process, "Hi", events.append)
    assert [e.text for e in events if e.kind == "assistant_delta"] == ["OK"]
    assert next(e for e in events if e.kind == "native_session_started").payload["native_id"] == "native-google-id"
    assert next(e for e in events if e.kind == "token_usage").payload["tokenUsage"]["last"]["totalTokens"] == 12
    assert events[-1].kind == "turn_completed"
    assert not provider._active


@pytest.mark.parametrize("events", [[], [{"event": "result", "result": {"status": "ERROR", "error": "authentication required"}}]])
def test_failed_stream_is_not_success(events):
    output = []
    AntigravityProvider()._consume("chat", Process(events), "Hi", output.append)
    assert any(e.kind == "error" for e in output)
    assert output[-1].kind == "turn_completed"


def test_empty_success_recovers_once_without_repeating_denied_tool():
    output = []
    process = Process([
        {"event": "result", "result": {"status": "SUCCESS", "response": "", "usage": {"total_tokens": 10}}},
        {"event": "result", "result": {"status": "SUCCESS", "response": "Resposta com fontes.", "usage": {"total_tokens": 30}}},
    ])
    AntigravityProvider()._consume("chat", process, "Pergunta", output.append)
    assert [e.text for e in output if e.kind == "assistant_delta"] == ["Resposta com fontes."]
    assert not any(e.kind == "error" for e in output)
    assert sum(e.kind == "turn_completed" for e in output) == 1
    usage = [e.payload['tokenUsage']['last']['totalTokens'] for e in output if e.kind == 'token_usage']
    assert usage == [30]  # CLI usage is cumulative across the recovery turns.


def test_repeated_empty_success_reports_error_instead_of_silent_completion():
    output = []
    process = Process([{"event": "result", "result": {"status": "SUCCESS", "response": ""}}] * 2)
    AntigravityProvider()._consume("chat", process, "Pergunta", output.append)
    assert any(e.kind == "error" and "recuperação" in e.text for e in output)


def test_google_account_rejects_api_configuration(tmp_path):
    config = tmp_path / ".gemini/antigravity-cli/settings.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"modelProvider": "gemini"}')
    with patch.object(Path, "home", return_value=tmp_path), pytest.raises(ProviderError):
        google_account_environment()


def test_google_environment_removes_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    with patch.object(Path, "home", return_value=tmp_path):
        assert "GEMINI_API_KEY" not in google_account_environment()


def test_registered_and_new_session_has_no_fabricated_id():
    providers = provider_registry()
    assert isinstance(providers["antigravity"], AntigravityProvider)
    assert providers["antigravity"].start_conversation("chat", "default", "medium", Path.cwd()) == ""
    for provider in providers.values():
        provider.close()


def test_model_catalog_groups_effort_variants():
    from types import SimpleNamespace
    provider = AntigravityProvider()
    output = 'gemini-3.8-flash-high\tGemini 3.8 Flash (High)\ngemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)\ngemini-3.8-flash-low\tGemini 3.8 Flash (Low)\ngemini-3.1-pro-high\tGemini 3.1 Pro (High)\ngemini-3.1-pro-low\tGemini 3.1 Pro (Low)\nclaude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)'
    with patch.object(provider, 'available', return_value=True), patch('vrsoft_extractor.mary.antigravity.google_account_environment', return_value={}), patch('vrsoft_extractor.mary.antigravity.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=output)):
        catalog = provider.list_models()
    assert [m['displayName'] for m in catalog[1:]] == ['Gemini 3.8 Flash', 'Gemini 3.1 Pro', 'Claude Sonnet 4.6 (Thinking)']
    assert [x['reasoningEffort'] for x in catalog[2]['supportedReasoningEfforts']] == ['low', 'high']
    assert provider._model_variants['gemini-3.8-flash-high']['low'] == 'gemini-3.8-flash-low'


@pytest.mark.parametrize('effort,expected_model', [('low', 'gemini-3.8-flash-low'), ('high', 'gemini-3.8-flash-high'), ('auto', 'gemini-3.8-flash-high')])
def test_send_resolves_effort_to_native_model(effort, expected_model):
    provider = AntigravityProvider()
    provider.command = 'agy'
    provider._model_variants = {'gemini-3.8-flash-high': {'low': 'gemini-3.8-flash-low', 'high': 'gemini-3.8-flash-high'}}
    with patch.object(provider, 'available', return_value=True), patch('vrsoft_extractor.mary.antigravity.google_account_environment', return_value={}), patch('vrsoft_extractor.mary.antigravity.subprocess.Popen') as launch, patch('vrsoft_extractor.mary.antigravity.threading.Thread'):
        provider.send_message('chat', '', 'gemini-3.8-flash-high', effort, Path.cwd(), 'Hi', lambda event: None)
    command = launch.call_args.args[0]
    assert command[command.index('--model') + 1] == expected_model
    assert ('--effort' in command) == (effort != 'auto')
