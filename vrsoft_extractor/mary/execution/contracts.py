"""
Execution contracts for the VR Mary Studio core.

These contracts model execution context, execution stages, and results
without any Qt/QML dependency.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..models import (
    EvidenceBundle,
)
from ..research_fanout import ModuleResearch
from ..supervision import MergedEvidence, ResponseViolation
from .budget import ExecutionBudget
from .cancellation import CancellationToken


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class ExecutionContext:
    """Context holding identifiers, workspace and state for a single execution."""

    conversation_id: str
    run_id: str
    workspace: Path
    owner_message_id: int | None = None
    started_monotonic: float = field(default_factory=time.monotonic)
    cancelled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    cancellation: CancellationToken = field(default_factory=CancellationToken)

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_monotonic

    def check_cancelled(self) -> None:
        if self.cancelled:
            self.cancellation.cancel()
        self.cancellation.check_cancelled()


@dataclass(frozen=True, slots=True)
class ResearchStagePlan:
    """Plan definition for an individual research or synthesis stage."""

    id: str
    agent_id: str
    label: str
    role: str
    module: str
    source: str
    task: str
    reason: str
    model: dict[str, Any]
    effort: str
    final: bool
    required: bool
    priority: int
    parent_id: str = "vr_fanout"
    worker_id: str = ""
    worker_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent": f"vr_{self.agent_id}",
            "label": self.label,
            "role": self.role,
            "module": self.module,
            "source": self.source,
            "task": self.task,
            "reason": self.reason,
            "model": self.model,
            "effort": self.effort,
            "final": self.final,
            "required": self.required,
            "priority": self.priority,
            "parent_id": self.parent_id,
            "worker_id": self.worker_id or self.id,
            "worker_name": self.worker_name or self.label,
        }
        if self.metadata:
            d.update(self.metadata)
        return d


@dataclass(frozen=True, slots=True)
class StageExecutionResult:
    """Result of an executed stage within a fanout or pipeline."""

    stage_id: str
    worker_id: str
    role: str
    status: StageStatus
    output: Any = None
    error: str = ""
    duration_seconds: float = 0.0
    attempts: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == StageStatus.COMPLETED


@dataclass(frozen=True, slots=True)
class ResearchFanoutPlan:
    """Consolidated plan for fanout research stages."""

    run_id: str
    modules: tuple[str, ...]
    runtime_stages: list[dict[str, Any]]
    max_parallel: int


@dataclass(frozen=True, slots=True)
class ResearchFanoutResult:
    """Consolidated outcome of the parallel research and synthesis pipeline."""

    run_id: str
    ordered: list[ModuleResearch]
    merged: MergedEvidence
    synthesis_bundle: EvidenceBundle
    code_status: str
    draft: Any | None = None
    violations: tuple[ResponseViolation, ...] = ()
    started_payload: dict[str, Any] = field(default_factory=dict)
    completed_payload: dict[str, Any] = field(default_factory=dict)
