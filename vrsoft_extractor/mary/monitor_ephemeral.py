"""In-memory execution boundary for the future VRMonitor adapter.

This module deliberately has no database, filesystem, logging, provider adapter,
or orchestration dependencies.  It does not make a provider safe by itself; it
only defines the Studio-side contract that an approved provider must satisfy.
The runtime identifier is local correlation metadata, not a Monitor identity or
authorization session. Central credentials, users, clients and targets never
enter the provider request surface.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from vrsoft_extractor.mary.models import ConversationOptions


EPHEMERAL_CONTRACT_VERSION = 1
_PROVIDER_FAILED = object()


class MonitorEphemeralError(RuntimeError):
    """Closed error whose text never includes provider or payload details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _SecretBuffer:
    """Mutable payload storage which can be overwritten when its owner closes."""

    __slots__ = ("_buffer", "_closed")

    def __init__(self, value: str | bytes | bytearray, *, limit: int, code: str) -> None:
        if isinstance(value, str):
            buffer = bytearray(value, "utf-8")
        elif isinstance(value, (bytes, bytearray)):
            buffer = bytearray(value)
        else:
            raise MonitorEphemeralError(code)
        if len(buffer) > limit or not self._valid_utf8(buffer):
            buffer[:] = b"\x00" * len(buffer)
            raise MonitorEphemeralError(code)
        self._buffer = buffer
        self._closed = False

    @staticmethod
    def _valid_utf8(buffer: bytearray) -> bool:
        try:
            buffer.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True

    @property
    def size(self) -> int:
        return len(self._buffer)

    def read_text(self) -> str:
        if self._closed:
            raise MonitorEphemeralError("monitor_payload_closed")
        return self._buffer.decode("utf-8")

    def close(self) -> None:
        if self._closed:
            return
        self._buffer[:] = b"\x00" * len(self._buffer)
        self._closed = True

    def __repr__(self) -> str:
        return f"_SecretBuffer(size={len(self._buffer)}, closed={self._closed})"


class MonitorTurnRequest:
    """Single-turn provider request with no central identity or authority."""

    __slots__ = ("correlation_id", "runtime_id", "_payload")

    def __init__(self, runtime_id: str, correlation_id: str, payload: _SecretBuffer) -> None:
        self.runtime_id = runtime_id
        self.correlation_id = correlation_id
        self._payload = payload

    @property
    def input_bytes(self) -> int:
        return self._payload.size

    def read_payload(self) -> str:
        return self._payload.read_text()

    def close(self) -> None:
        self._payload.close()

    def __repr__(self) -> str:
        return (
            "MonitorTurnRequest("
            f"runtime_id={self.runtime_id!r}, correlation_id={self.correlation_id!r}, "
            f"input_bytes={self.input_bytes})"
        )


class MonitorTurnResult:
    """Transient result which the transport must close after delivering it."""

    __slots__ = ("correlation_id", "runtime_id", "_payload")

    def __init__(self, runtime_id: str, correlation_id: str, payload: _SecretBuffer) -> None:
        self.runtime_id = runtime_id
        self.correlation_id = correlation_id
        self._payload = payload

    @property
    def output_bytes(self) -> int:
        return self._payload.size

    def read_text(self) -> str:
        return self._payload.read_text()

    def close(self) -> None:
        self._payload.close()

    def __enter__(self) -> MonitorTurnResult:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            "MonitorTurnResult("
            f"runtime_id={self.runtime_id!r}, correlation_id={self.correlation_id!r}, "
            f"output_bytes={self.output_bytes})"
        )


@dataclass(frozen=True)
class MonitorTurnEvent:
    """Content-free lifecycle event suitable for operational counters."""

    kind: str
    runtime_id: str
    correlation_id: str
    input_bytes: int = 0
    output_bytes: int = 0
    code: str = ""


class MonitorEphemeralProvider(Protocol):
    """Provider contract required by :class:`MonitorEphemeralSession`."""

    ephemeral_contract_version: int
    persists_content: bool
    supports_resume: bool

    def run_turn(
        self,
        request: MonitorTurnRequest,
        cancel_event: threading.Event,
    ) -> bytes | bytearray:
        """Execute one isolated turn and return mutable or copyable UTF-8 bytes."""


MonitorEventSink = Callable[[MonitorTurnEvent], None]


class MonitorEphemeralSession:
    """One-at-a-time, memory-only Monitor execution session.

    The session retains identifiers and counters only. Requests are invalidated
    after each turn, results are owned by the caller, and no resume/history API
    exists. Provider-side retention remains a separate integration gate.
    """

    __slots__ = (
        "_closed",
        "_current_cancel",
        "_event_sink",
        "_max_input_bytes",
        "_max_output_bytes",
        "_provider",
        "_state_lock",
        "_turn_gate",
        "_turns_completed",
        "runtime_id",
    )

    def __init__(
        self,
        provider: MonitorEphemeralProvider,
        options: ConversationOptions,
        *,
        event_sink: MonitorEventSink | None = None,
        max_input_bytes: int = 64 * 1024,
        max_output_bytes: int = 1024 * 1024,
    ) -> None:
        if not options.monitor_mode or (
            options.approval_profile != ConversationOptions.MONITOR_APPROVAL_PROFILE
        ):
            raise MonitorEphemeralError("monitor_profile_required")
        if (
            getattr(provider, "ephemeral_contract_version", None)
            != EPHEMERAL_CONTRACT_VERSION
            or getattr(provider, "persists_content", None) is not False
            or getattr(provider, "supports_resume", None) is not False
        ):
            raise MonitorEphemeralError("monitor_provider_contract_rejected")
        if max_input_bytes <= 0 or max_output_bytes <= 0:
            raise ValueError("Monitor byte limits must be positive.")

        self.runtime_id = secrets.token_hex(16)
        self._provider = provider
        self._event_sink = event_sink
        self._max_input_bytes = max_input_bytes
        self._max_output_bytes = max_output_bytes
        self._turn_gate = threading.Lock()
        self._state_lock = threading.Lock()
        self._current_cancel: threading.Event | None = None
        self._closed = False
        self._turns_completed = 0

    @property
    def turns_completed(self) -> int:
        with self._state_lock:
            return self._turns_completed

    def run_turn(self, payload: str) -> MonitorTurnResult:
        if not self._turn_gate.acquire(blocking=False):
            raise MonitorEphemeralError("monitor_busy")

        request: MonitorTurnRequest | None = None
        raw_output: bytes | bytearray | None = None
        output: _SecretBuffer | None = None
        cancel_event = threading.Event()
        correlation_id = secrets.token_hex(16)
        try:
            with self._state_lock:
                if self._closed:
                    raise MonitorEphemeralError("monitor_session_closed")
                self._current_cancel = cancel_event

            request = MonitorTurnRequest(
                self.runtime_id,
                correlation_id,
                _SecretBuffer(
                    payload,
                    limit=self._max_input_bytes,
                    code="monitor_input_rejected",
                ),
            )
            if not self._emit(
                MonitorTurnEvent(
                    "started",
                    self.runtime_id,
                    correlation_id,
                    input_bytes=request.input_bytes,
                )
            ):
                raise MonitorEphemeralError("monitor_event_sink_failed")
            provider_output = self._call_provider(request, cancel_event)
            if provider_output is _PROVIDER_FAILED:
                raise MonitorEphemeralError("monitor_unavailable")
            if not isinstance(provider_output, (bytes, bytearray)):
                raise MonitorEphemeralError("monitor_output_rejected")
            raw_output = provider_output
            if cancel_event.is_set():
                raise MonitorEphemeralError("monitor_cancelled")
            output = _SecretBuffer(
                raw_output,
                limit=self._max_output_bytes,
                code="monitor_output_rejected",
            )
            if not self._emit(
                MonitorTurnEvent(
                    "finished",
                    self.runtime_id,
                    correlation_id,
                    input_bytes=request.input_bytes,
                    output_bytes=output.size,
                )
            ):
                raise MonitorEphemeralError("monitor_event_sink_failed")
            with self._state_lock:
                self._turns_completed += 1
            result = MonitorTurnResult(self.runtime_id, correlation_id, output)
            output = None
            return result
        except MonitorEphemeralError as exc:
            kind = "cancelled" if exc.code == "monitor_cancelled" else "failed"
            self._emit(
                MonitorTurnEvent(
                    kind,
                    self.runtime_id,
                    correlation_id,
                    input_bytes=request.input_bytes if request else 0,
                    code=exc.code,
                )
            )
            raise
        except Exception:
            self._emit(
                MonitorTurnEvent(
                    "failed",
                    self.runtime_id,
                    correlation_id,
                    input_bytes=request.input_bytes if request else 0,
                    code="monitor_unavailable",
                )
            )
            raise MonitorEphemeralError("monitor_unavailable") from None
        finally:
            if request is not None:
                request.close()
            if isinstance(raw_output, bytearray):
                raw_output[:] = b"\x00" * len(raw_output)
            if output is not None:
                output.close()
            with self._state_lock:
                self._current_cancel = None
            self._turn_gate.release()

    def cancel(self) -> None:
        with self._state_lock:
            if self._current_cancel is not None:
                self._current_cancel.set()

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            if self._current_cancel is not None:
                self._current_cancel.set()

    def _call_provider(
        self,
        request: MonitorTurnRequest,
        cancel_event: threading.Event,
    ) -> bytes | bytearray | object:
        try:
            return self._provider.run_turn(request, cancel_event)
        except Exception:
            return _PROVIDER_FAILED

    def _emit(self, event: MonitorTurnEvent) -> bool:
        if self._event_sink is None:
            return True
        try:
            self._event_sink(event)
        except Exception:
            return False
        return True

    def __repr__(self) -> str:
        return (
            "MonitorEphemeralSession("
            f"runtime_id={self.runtime_id!r}, turns_completed={self.turns_completed}, "
            f"closed={self._closed})"
        )
