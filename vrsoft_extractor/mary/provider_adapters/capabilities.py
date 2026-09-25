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
    # VR-only: whether the transport makes the knowledge root readable by the
    # provider's native file tools. When false, the VR prompt keeps the
    # vr_sources/vr_search/vr_read contract and never announces the folder.
    vr_direct_file_access: bool = True


CAPABILITIES = {
    "codex": ProviderCapabilities(True, True, True, "native", "reported", vr_direct_file_access=False),
    "claude": ProviderCapabilities(True, True, True, "file_reference", "reported"),
    "opencode": ProviderCapabilities(True, True, True, "file_reference", "reported"),
    "antigravity": ProviderCapabilities(True, True, True, "native", "context_only", vr_direct_file_access=False),
}
