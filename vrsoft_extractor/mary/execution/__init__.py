"""
Execution subsystem for VR Mary Studio.

Provides non-Qt contracts and runners for parallel research fan-out,
stage execution, response synthesis, budget enforcement, cancellation,
and structured persistence for safe resumption.
"""

from __future__ import annotations

from .budget import (
    BudgetExhaustedError,
    CallReservationError,
    ExecutionBudget,
    TokenAccounting,
)
from .cancellation import (
    CancellationToken,
    ExecutionCancelledError,
)
from .contracts import (
    ExecutionContext,
    ResearchFanoutPlan,
    ResearchFanoutResult,
    ResearchStagePlan,
    StageExecutionResult,
    StageStatus,
    UltraSourceFanoutPlan,
    UltraSourceFanoutResult,
)
from .repository import (
    CONTRACT_VERSION,
    ResearchRepository,
    compute_step_input_hash,
)
from .runner import ExecutionRunner

__all__ = [
    "CONTRACT_VERSION",
    "BudgetExhaustedError",
    "CallReservationError",
    "CancellationToken",
    "ExecutionBudget",
    "ExecutionContext",
    "ExecutionCancelledError",
    "ExecutionRunner",
    "ResearchFanoutPlan",
    "ResearchFanoutResult",
    "ResearchRepository",
    "ResearchStagePlan",
    "StageExecutionResult",
    "StageStatus",
    "TokenAccounting",
    "UltraSourceFanoutPlan",
    "UltraSourceFanoutResult",
    "compute_step_input_hash",
]
