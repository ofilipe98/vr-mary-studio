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
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from vrsoft_extractor.mary.models import ConversationOptions
from vrsoft_extractor.mary.monitor_egress import (
    MonitorEgressAttestation,
    egress_attested,
)
from vrsoft_extractor.mary.monitor_isolation import (
    MonitorIsolationAttestation,
    isolation_attested,
)


EPHEMERAL_CONTRACT_VERSION = 2
MAX_MONITOR_INPUT_BYTES = 64 * 1024
MAX_MONITOR_OUTPUT_BYTES = 1024 * 1024
MAX_MONITOR_OUTPUT_CHUNK_BYTES = 64 * 1024
MAX_MONITOR_TURN_SECONDS = 300.0
MAX_MONITOR_CANCEL_GRACE_SECONDS = 5.0


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


class MonitorOutputSink:
    """Thread-safe output collector which rejects data before exceeding its cap."""

    __slots__ = ("_buffer", "_cancel_event", "_chunk_limit", "_closed", "_limit", "_lock")

    def __init__(
        self,
        *,
        limit: int,
        chunk_limit: int,
        cancel_event: threading.Event,
    ) -> None:
        self._buffer = bytearray()
        self._limit = limit
        self._chunk_limit = chunk_limit
        self._cancel_event = cancel_event
        self._closed = False
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._buffer)

    def write(self, chunk: bytes | bytearray) -> None:
        if not isinstance(chunk, (bytes, bytearray)) or not chunk:
            self._reject()
        if len(chunk) > self._chunk_limit:
            self._reject()
        with self._lock:
            if self._closed or len(self._buffer) + len(chunk) > self._limit:
                self._cancel_event.set()
                raise MonitorEphemeralError("monitor_output_rejected")
            self._buffer.extend(chunk)

    def take(self) -> bytearray:
        with self._lock:
            if self._closed:
                raise MonitorEphemeralError("monitor_output_rejected")
            value = self._buffer
            self._buffer = bytearray()
            self._closed = True
            return value

    def close(self) -> None:
        with self._lock:
            self._buffer[:] = b"\x00" * len(self._buffer)
            self._closed = True

    def _reject(self) -> None:
        self._cancel_event.set()
        raise MonitorEphemeralError("monitor_output_rejected")

    def __repr__(self) -> str:
        return f"MonitorOutputSink(size={self.size}, closed={self._closed})"


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
    provider_id: str
    model_id: str
    egress_manifest_digest: str
    isolation_manifest_digest: str
    persists_content: bool
    supports_resume: bool

    def run_turn(
        self,
        request: MonitorTurnRequest,
        output: MonitorOutputSink,
        cancel_event: threading.Event,
    ) -> None:
        """Stream bounded UTF-8 bytes into ``output`` and retain no content."""

    def terminate_turn(self, correlation_id: str) -> None:
        """Force termination of the brokered process for one correlation id."""


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
        "_max_output_chunk_bytes",
        "_max_output_bytes",
        "_provider",
        "_state_lock",
        "_terminate_grace_seconds",
        "_turn_gate",
        "_turn_timeout_seconds",
        "_turns_completed",
        "runtime_id",
    )

    def __init__(
        self,
        provider: MonitorEphemeralProvider,
        options: ConversationOptions,
        isolation: MonitorIsolationAttestation,
        egress: MonitorEgressAttestation,
        *,
        event_sink: MonitorEventSink | None = None,
        max_input_bytes: int = MAX_MONITOR_INPUT_BYTES,
        max_output_bytes: int = MAX_MONITOR_OUTPUT_BYTES,
        max_output_chunk_bytes: int = MAX_MONITOR_OUTPUT_CHUNK_BYTES,
        turn_timeout_seconds: float = 30.0,
        terminate_grace_seconds: float = 1.0,
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
            or not callable(getattr(provider, "run_turn", None))
            or not callable(getattr(provider, "terminate_turn", None))
        ):
            raise MonitorEphemeralError("monitor_provider_contract_rejected")
        if not isolation_attested(isolation):
            raise MonitorEphemeralError("monitor_isolation_required")
        if (
            getattr(provider, "isolation_manifest_digest", "")
            != isolation.manifest_digest
        ):
            raise MonitorEphemeralError("monitor_isolation_required")
        if not egress_attested(egress):
            raise MonitorEphemeralError("monitor_egress_required")
        if (
            getattr(provider, "provider_id", "") != egress.provider_id
            or getattr(provider, "model_id", "") != egress.model_id
            or getattr(provider, "egress_manifest_digest", "")
            != egress.manifest_digest
        ):
            raise MonitorEphemeralError("monitor_egress_required")
        if not 0 < max_input_bytes <= MAX_MONITOR_INPUT_BYTES:
            raise ValueError("Monitor input limit exceeds the hard ceiling.")
        if not 0 < max_output_bytes <= MAX_MONITOR_OUTPUT_BYTES:
            raise ValueError("Monitor output limit exceeds the hard ceiling.")
        if not 0 < max_output_chunk_bytes <= min(
            MAX_MONITOR_OUTPUT_CHUNK_BYTES, max_output_bytes
        ):
            raise ValueError("Monitor output chunk limit exceeds the hard ceiling.")
        if not 0 < turn_timeout_seconds <= MAX_MONITOR_TURN_SECONDS:
            raise ValueError("Monitor turn timeout exceeds the hard ceiling.")
        if not 0 < terminate_grace_seconds <= MAX_MONITOR_CANCEL_GRACE_SECONDS:
            raise ValueError("Monitor termination grace exceeds the hard ceiling.")

        self.runtime_id = secrets.token_hex(16)
        self._provider = provider
        self._event_sink = event_sink
        self._max_input_bytes = max_input_bytes
        self._max_output_bytes = max_output_bytes
        self._max_output_chunk_bytes = max_output_chunk_bytes
        self._turn_timeout_seconds = turn_timeout_seconds
        self._terminate_grace_seconds = terminate_grace_seconds
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
        raw_output: bytearray | None = None
        output: _SecretBuffer | None = None
        cancel_event = threading.Event()
        output_sink = MonitorOutputSink(
            limit=self._max_output_bytes,
            chunk_limit=self._max_output_chunk_bytes,
            cancel_event=cancel_event,
        )
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
            self._call_provider(request, output_sink, cancel_event)
            raw_output = output_sink.take()
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
            if raw_output is not None:
                raw_output[:] = b"\x00" * len(raw_output)
            output_sink.close()
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
        output: MonitorOutputSink,
        cancel_event: threading.Event,
    ) -> None:
        completed = threading.Event()
        failure: list[str] = []

        def invoke() -> None:
            try:
                result = self._provider.run_turn(request, output, cancel_event)
                if result is not None:
                    failure.append("monitor_output_rejected")
            except MonitorEphemeralError as exc:
                failure.append(
                    exc.code
                    if exc.code == "monitor_output_rejected"
                    else "monitor_unavailable"
                )
            except Exception:
                failure.append("monitor_unavailable")
            finally:
                completed.set()

        worker = threading.Thread(target=invoke, daemon=True, name="monitor-provider-turn")
        worker.start()
        deadline = time.monotonic() + self._turn_timeout_seconds
        stop_code = ""
        while not completed.wait(0.01):
            if cancel_event.is_set():
                stop_code = "monitor_cancelled"
                break
            if time.monotonic() >= deadline:
                cancel_event.set()
                stop_code = "monitor_timeout"
                break

        if stop_code:
            self._terminate_provider(request.correlation_id)
            completed.wait(self._terminate_grace_seconds)
            raise MonitorEphemeralError(stop_code)
        if failure:
            raise MonitorEphemeralError(failure[0])
        if cancel_event.is_set():
            raise MonitorEphemeralError("monitor_cancelled")

    def _terminate_provider(self, correlation_id: str) -> None:
        try:
            self._provider.terminate_turn(correlation_id)
        except Exception:
            pass

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
