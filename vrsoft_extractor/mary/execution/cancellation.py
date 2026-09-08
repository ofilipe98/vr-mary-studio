"""
Cooperative cancellation token for VR Mary Studio execution runs.

Allows checking cancellation status, waiting with interruptibility,
and registering callbacks to be invoked immediately upon cancellation.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

LOGGER = logging.getLogger(__name__)


class ExecutionCancelledError(RuntimeError):
    """Raised when an execution or stage is cancelled."""
    pass


class CancellationToken:
    """
    Thread-safe cancellation token.

    Allows workers to observe cancellation, execute interruptible waits,
    and trigger registered cancellation hooks (e.g. aborting ongoing HTTP/subprocess calls).
    """

    def __init__(self):
        self._event = threading.Event()
        self._reason: str = ""
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "user_cancelled") -> None:
        """Mark the token as cancelled and notify all registered listeners."""
        with self._lock:
            if self._event.is_set():
                return
            self._reason = reason
            self._event.set()
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb()
            except Exception as exc:
                LOGGER.warning("Error in cancellation callback: %s", exc)

    def register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback to be called on cancellation. If already cancelled, calls immediately."""
        with self._lock:
            already = self._event.is_set()
            if not already:
                self._callbacks.append(callback)
        if already:
            try:
                callback()
            except Exception as exc:
                LOGGER.warning("Error in immediate cancellation callback: %s", exc)
        def unregister() -> None:
            with self._lock:
                if callback in self._callbacks:
                    self._callbacks.remove(callback)
        return unregister

    def check_cancelled(self) -> None:
        """Raise ExecutionCancelledError if cancellation has been requested."""
        if self._event.is_set():
            raise ExecutionCancelledError(f"Execução cancelada: {self._reason or 'interrupção do usuário'}")

    def wait(self, timeout_seconds: float) -> bool:
        """
        Wait for timeout_seconds or until cancelled.
        Returns True if cancelled during wait, False if timeout expired normally.
        """
        return self._event.wait(max(0.0, timeout_seconds))
