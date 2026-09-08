"""Capabilities implemented by the concrete transports; no inferred token ceilings."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    native_resume: bool
    interrupt: bool
    intermediate_messages: bool
    image_input: str
    token_usage: str
    automatic_side_effect_replay: bool = False


CAPABILITIES = {
    "codex": ProviderCapabilities(True, True, True, "native", "reported"),
    "claude": ProviderCapabilities(True, True, True, "file_reference", "reported"),
    "opencode": ProviderCapabilities(True, True, True, "file_reference", "reported"),
    "antigravity": ProviderCapabilities(True, True, True, "native", "context_only"),
}
