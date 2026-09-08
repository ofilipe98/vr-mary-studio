"""
Execution budget management for VR Mary Studio.

Provides thread-safe call reservation, dynamic timeout calculation,
token consumption tracking (real, estimated, unknown), and guaranteed
capacity reservation for response synthesis and validation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


class BudgetExhaustedError(RuntimeError):
    """Raised when an execution budget constraint (time, calls, tokens) is breached."""
    pass


class CallReservationError(BudgetExhaustedError):
    """Raised when no call slots remain or non-synthesis workers attempt to consume reserved synthesis slots."""
    pass


@dataclass
class TokenAccounting:
    """Tracks token consumption categorized by certainty."""
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
    """
    Thread-safe execution budget governing a full orchestration turn.

    Guarantees:
    1. Atomic call slot reservations.
    2. Dynamic timeout capped at remaining execution deadline.
    3. Mandatory reservation of calls for final synthesis & validation.
    4. Categorized token accounting (real, estimated, unknown).
    """

    def __init__(
        self,
        max_active_seconds: float = 300.0,
        max_calls: int = 15,
        max_parallel: int = 4,
        max_retries_per_worker: int = 2,
        token_limit: int | None = None,
        reserved_synthesis_calls: int = 2,
        clock: Callable[[], float] = time.monotonic,
        reserved_synthesis_seconds: float = 0.0,
    ):
        self.max_active_seconds = max(1.0, float(max_active_seconds))
        self.max_calls = max(1, int(max_calls))
        self.max_parallel = max(1, int(max_parallel))
        self.max_retries_per_worker = max(0, int(max_retries_per_worker))
        self.token_limit = token_limit
        self.reserved_synthesis_calls = max(1, int(reserved_synthesis_calls))
        self.reserved_synthesis_seconds = max(0.0, float(reserved_synthesis_seconds))
        self._clock = clock

        self._start_monotonic = self._clock()
        self._lock = threading.RLock()
        self._calls_made = 0
        self._calls_in_flight = 0
        self._tokens = TokenAccounting()
        self._exhausted_reason: str = ""

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

    def time_remaining(self) -> float:
        remaining = self.max_active_seconds - self.elapsed_seconds()
        return max(0.0, remaining)

    def is_time_exhausted(self) -> bool:
        return self.time_remaining() <= 0.0

    def remaining_calls(self) -> int:
        with self._lock:
            return max(0, self.max_calls - self._calls_made)

    def has_synthesis_capacity(self) -> bool:
        with self._lock:
            return (
                self.remaining_calls() >= self.reserved_synthesis_calls
                and not self.is_time_exhausted()
            )

    def acquire_call(
        self,
        *,
        is_synthesis: bool = False,
        requested_timeout: float | None = None,
    ) -> float:
        """
        Atomically reserve a call slot and return the allowed timeout in seconds.

        Raises CallReservationError if:
        - Total time has expired.
        - Total calls are exhausted.
        - Token limit is exceeded.
        - Non-synthesis call would encroach on reserved synthesis capacity.
        """
        with self._lock:
            rem_time = self.time_remaining()
            if rem_time <= 0.0:
                self._exhausted_reason = "Tempo máximo de execução esgotado"
                raise CallReservationError(self._exhausted_reason)

            if self.token_limit is not None and self._tokens.total_known >= self.token_limit:
                self._exhausted_reason = "Limite de tokens do orçamento excedido"
                raise CallReservationError(self._exhausted_reason)

            rem_calls = self.max_calls - self._calls_made
            if rem_calls <= 0:
                self._exhausted_reason = "Limite total de chamadas de modelo esgotado"
                raise CallReservationError(self._exhausted_reason)

            if not is_synthesis and rem_calls <= self.reserved_synthesis_calls:
                self._exhausted_reason = (
                    f"Capacidade restante ({rem_calls}) reservada exclusivamente para síntese e validação"
                )
                raise CallReservationError(self._exhausted_reason)

            if self._calls_in_flight >= self.max_parallel:
                raise CallReservationError("Limite de chamadas simultâneas atingido")

            if not is_synthesis:
                rem_time -= self.reserved_synthesis_seconds
                if rem_time <= 0:
                    raise CallReservationError("Tempo restante reservado para síntese e validação")

            self._calls_made += 1
            self._calls_in_flight += 1

            if requested_timeout is not None and requested_timeout > 0:
                return min(requested_timeout, rem_time)
            return rem_time

    def release_call(
        self,
        *,
        tokens_used: int = 0,
        token_kind: str = "real",
    ) -> None:
        """Release an in-flight call slot and record token usage."""
        with self._lock:
            self._calls_in_flight = max(0, self._calls_in_flight - 1)
            self.record_tokens(tokens_used, kind=token_kind)

    def record_tokens(self, count: int, kind: str = "real") -> None:
        """Record token usage by category."""
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
                "max_active_seconds": self.max_active_seconds,
                "max_calls": self.max_calls,
                "max_parallel": self.max_parallel,
                "max_retries_per_worker": self.max_retries_per_worker,
                "token_limit": self.token_limit,
                "reserved_synthesis_seconds": self.reserved_synthesis_seconds,
                "reserved_synthesis_calls": self.reserved_synthesis_calls,
                "calls_made": self._calls_made,
                "calls_in_flight": self._calls_in_flight,
                "remaining_calls": self.remaining_calls(),
                "elapsed_seconds": round(self.elapsed_seconds(), 2),
                "time_remaining_seconds": round(self.time_remaining(), 2),
                "tokens": self._tokens.to_dict(),
                "exhausted_reason": self._exhausted_reason,
            }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any], *, clock=time.monotonic) -> "ExecutionBudget":
        """Continue consumed active time and calls; downtime does not replenish them."""
        required = ("max_active_seconds", "max_calls", "calls_made", "elapsed_seconds", "tokens")
        if any(key not in snapshot for key in required):
            raise ValueError("Checkpoint sem orçamento completo")
        result = cls(**{key: snapshot[key] for key in (
            "max_active_seconds", "max_calls", "max_parallel", "max_retries_per_worker",
            "token_limit", "reserved_synthesis_calls", "reserved_synthesis_seconds",
        ) if key in snapshot}, clock=clock)
        result._calls_made = max(0, int(snapshot["calls_made"]))
        result._start_monotonic -= max(0.0, float(snapshot["elapsed_seconds"]))
        result._tokens = TokenAccounting(**{key: max(0, int(snapshot["tokens"].get(key, 0))) for key in ("real", "estimated", "unknown")})
        return result
