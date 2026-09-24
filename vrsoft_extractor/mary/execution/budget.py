"""Execution telemetry kept for compatibility with Ultra checkpoints."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


class BudgetExhaustedError(RuntimeError):
    """Legacy exception type retained for imports from older integrations."""


class CallReservationError(BudgetExhaustedError):
    """Legacy exception type retained for imports from older integrations."""


@dataclass
class TokenAccounting:
    real: int = 0
    estimated: int = 0
    unknown: int = 0

    @property
    def total_known(self) -> int:
        return self.real + self.estimated

    def to_dict(self) -> dict[str, int]:
        return {
            "real": self.real,
            "estimated": self.estimated,
            "unknown": self.unknown,
            "total_known": self.total_known,
        }


class ExecutionBudget:
    """Thread-safe execution telemetry without cumulative quotas."""

    def __init__(
        self,
        max_parallel: int = 4,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_parallel = max(1, int(max_parallel))
        self._clock = clock
        self._start_monotonic = self._clock()
        self._lock = threading.RLock()
        self._calls_made = 0
        self._calls_in_flight = 0
        self._tokens = TokenAccounting()

    @property
    def start_time(self) -> float:
        return self._start_monotonic

    @property
    def calls_made(self) -> int:
        with self._lock:
            return self._calls_made

    @property
    def calls_in_flight(self) -> int:
        with self._lock:
            return self._calls_in_flight

    @property
    def tokens(self) -> TokenAccounting:
        with self._lock:
            return TokenAccounting(
                real=self._tokens.real,
                estimated=self._tokens.estimated,
                unknown=self._tokens.unknown,
            )

    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._start_monotonic)

    def time_remaining(self) -> None:
        return None

    def is_time_exhausted(self) -> bool:
        return False

    def remaining_calls(self) -> None:
        return None

    def has_synthesis_capacity(self) -> bool:
        return True

    def acquire_call(
        self,
        *,
        is_synthesis: bool = False,
        requested_timeout: float | None = None,
    ) -> None:
        with self._lock:
            self._calls_made += 1
            self._calls_in_flight += 1

    def release_call(
        self,
        *,
        tokens_used: int = 0,
        token_kind: str = "real",
    ) -> None:
        with self._lock:
            self._calls_in_flight = max(0, self._calls_in_flight - 1)
            self.record_tokens(tokens_used, kind=token_kind)

    def record_tokens(self, count: int, kind: str = "real") -> None:
        if count <= 0:
            return
        with self._lock:
            if kind == "real":
                self._tokens.real += count
            elif kind == "estimated":
                self._tokens.estimated += count
            else:
                self._tokens.unknown += count

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "unlimited": True,
                "max_parallel": self.max_parallel,
                "calls_made": self._calls_made,
                "calls_in_flight": self._calls_in_flight,
                "elapsed_seconds": round(self.elapsed_seconds(), 2),
                "tokens": self._tokens.to_dict(),
            }

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> "ExecutionBudget":
        if not isinstance(snapshot, dict):
            raise ValueError("Checkpoint sem telemetria de execução")
        required = ("calls_made", "elapsed_seconds", "tokens")
        if any(key not in snapshot for key in required):
            raise ValueError("Checkpoint sem telemetria de execução")
        result = cls(
            max_parallel=max(1, int(snapshot.get("max_parallel", 4) or 4)),
            clock=clock,
        )
        result._calls_made = max(0, int(snapshot.get("calls_made", 0) or 0))
        result._start_monotonic -= max(
            0.0, float(snapshot.get("elapsed_seconds", 0.0) or 0.0)
        )
        raw_tokens = snapshot.get("tokens") or {}
        if not isinstance(raw_tokens, dict):
            raw_tokens = {}
        result._tokens = TokenAccounting(
            **{
                key: max(0, int(raw_tokens.get(key, 0) or 0))
                for key in ("real", "estimated", "unknown")
            }
        )
        return result
