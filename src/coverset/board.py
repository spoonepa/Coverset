"""Board records: what a solve produced, and what proves it.

These types are deliberately inert. They hold no CP-SAT and no solving logic, which
is what lets `validate.py` read them without being able to reach the compiler that
produced them — the independence `SOL-007` asks for is a matter of what the modules
can import, not of anyone remembering to keep two code paths apart.

The central guard is that `Board` cannot be constructed without a passing
`ValidationReport` for the same constraint snapshot. CP-SAT guarantees a solution
satisfies *the model it was given*; it guarantees nothing about whether that model
was the production's actual problem. A miscompiled constraint yields a board the
solver will call optimal (`NNG-003`, `SOL-007`). So an unvalidated board is not a
board with a warning attached — it is not constructible.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator

from .clock import elapsed
from .constraints import Family, Policy

__all__ = [
    "Assignment",
    "Board",
    "ConstraintCheck",
    "InvalidBoard",
    "ObjectiveBreakdown",
    "ShootDay",
    "SolverStatus",
    "ValidationReport",
]


class InvalidBoard(Exception):
    """A board was assembled that must not be allowed to exist."""


class SolverStatus(StrEnum):
    """Normative status vocabulary from SPEC 5.6."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    ERROR = "error"

    @property
    def is_solved(self) -> bool:
        """Whether a solution exists at all.

        `UNKNOWN` is not a weak yes. It means the search was cut off without proving
        anything, and a schedule nobody proved is not a schedule (`SOL-007`).
        """
        return self in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)


@dataclass(frozen=True, slots=True)
class Assignment:
    """One work item placed on one shoot day, at a position within that day."""

    work_id: str
    shoot_day: dt.date
    sequence: int
    location_id: str
    planned_call_time: dt.datetime
    planned_wrap_time: dt.datetime

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise InvalidBoard(f"{self.work_id}: sequence must not be negative")
        for label, when in (
            ("call", self.planned_call_time),
            ("wrap", self.planned_wrap_time),
        ):
            if when.tzinfo is None:
                raise InvalidBoard(
                    f"{self.work_id}: {label} time is naive. A call time without a "
                    f"zone is an hour wrong across a DST boundary, and a twenty-day "
                    f"board crosses one routinely."
                )
        if self.planned_wrap_time <= self.planned_call_time:
            raise InvalidBoard(
                f"{self.work_id}: wrap {self.planned_wrap_time:%H:%M} does not follow "
                f"call {self.planned_call_time:%H:%M}"
            )

    @property
    def duration(self) -> dt.timedelta:
        return elapsed(self.planned_call_time, self.planned_wrap_time)


@dataclass(frozen=True, slots=True)
class ShootDay:
    """One day of the board: the assignments on it, in order."""

    date: dt.date
    assignments: tuple[Assignment, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assignments", tuple(sorted(self.assignments, key=lambda a: a.sequence))
        )

    def __iter__(self) -> Iterator[Assignment]:
        return iter(self.assignments)

    def __len__(self) -> int:
        return len(self.assignments)

    @property
    def call_time(self) -> dt.datetime | None:
        return min((a.planned_call_time for a in self.assignments), default=None)

    @property
    def wrap_time(self) -> dt.datetime | None:
        return max((a.planned_wrap_time for a in self.assignments), default=None)

    @property
    def length(self) -> dt.timedelta:
        call, wrap = self.call_time, self.wrap_time
        if call is None or wrap is None:
            return dt.timedelta()
        return elapsed(call, wrap)

    @property
    def location_ids(self) -> tuple[str, ...]:
        """Locations in the order the day visits them, without repeats in a run."""
        out: list[str] = []
        for a in self.assignments:
            if not out or out[-1] != a.location_id:
                out.append(a.location_id)
        return tuple(out)

    @property
    def company_moves(self) -> int:
        """Relocations within the day: one fewer than the number of location runs."""
        return max(0, len(self.location_ids) - 1)


@dataclass(frozen=True, slots=True)
class ObjectiveBreakdown:
    """What the board costs, separated by term (`SOL-009`).

    Reported per term rather than as one number because a total tells an AD nothing
    they can act on. Two boards costing the same may differ by three company moves
    against nine holding days, and that is a production decision, not a tie.
    """

    company_moves: int = 0
    holding_days: int = 0
    overtime_hours: float = 0.0
    added_shoot_days: int = 0
    weather_risk_cost: float = 0.0

    def __post_init__(self) -> None:
        for name in ("company_moves", "holding_days", "added_shoot_days"):
            if getattr(self, name) < 0:
                raise InvalidBoard(f"{name} cannot be negative")
        if self.overtime_hours < 0 or self.weather_risk_cost < 0:
            raise InvalidBoard("objective terms cannot be negative")

    def lines(self) -> tuple[str, ...]:
        """Production-readable cost lines, in the order an AD reads them."""
        return (
            f"company moves      {self.company_moves}",
            f"cast holding days  {self.holding_days}",
            f"overtime hours     {self.overtime_hours:g}",
            f"added shoot days   {self.added_shoot_days}",
            f"weather risk cost  {self.weather_risk_cost:g}",
        )


@dataclass(frozen=True, slots=True)
class ConstraintCheck:
    """One constraint, re-evaluated against a finished board."""

    constraint_id: str
    family: Family
    policy: Policy
    satisfied: bool
    detail: str = ""

    def __str__(self) -> str:
        mark = "ok" if self.satisfied else "VIOLATED"
        return f"{self.constraint_id} [{self.family}] {mark}{': ' + self.detail if self.detail else ''}"


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The independent re-check of a board against every constraint that binds it.

    `expected_ids` is not bookkeeping. Without it an empty report passes vacuously,
    and a validator that silently checked nothing is worse than no validator at all —
    it converts an unexamined board into one carrying a clean bill of health. Naming
    the constraints that *must* appear makes the vacuous report unconstructible.
    """

    checks: tuple[ConstraintCheck, ...]
    expected_ids: frozenset[str]
    constraint_snapshot_hash: str
    validator_version: str = "independent-1"

    def __post_init__(self) -> None:
        checked = {c.constraint_id for c in self.checks}
        if missing := sorted(self.expected_ids - checked):
            raise InvalidBoard(
                f"validation is incomplete: {len(missing)} binding constraint(s) were "
                f"never evaluated against the board ({', '.join(missing)}). An "
                f"unchecked constraint is one the board is free to violate."
            )

    @property
    def violations(self) -> tuple[ConstraintCheck, ...]:
        return tuple(c for c in self.checks if not c.satisfied)

    @property
    def passed(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        if self.passed:
            return f"{len(self.checks)} constraint(s) re-checked, none violated"
        return (
            f"{len(self.violations)} of {len(self.checks)} constraint(s) violated: "
            + "; ".join(str(v) for v in self.violations)
        )


@dataclass(frozen=True, slots=True)
class Board:
    """A validated schedule. Unconstructible unless it was proven, not merely solved."""

    board_id: str
    schedule_version_id: str
    assignments: tuple[Assignment, ...]
    objective_breakdown: ObjectiveBreakdown
    constraint_snapshot_hash: str
    solver_status: SolverStatus
    solver_objective_value: float
    validation_result: ValidationReport
    solver_best_bound: float = 0.0
    """The best cost the solver could prove no board can beat.

    Meaningful only alongside `solver_objective_value`: together they bracket where
    the true optimum lies."""
    optimality_gap: float = 0.0
    """How far this board may be from optimal, relative (`0.05` is five percent).

    A `feasible` board is a board the solver found but did not prove best. Reporting
    it without this number invites a First AD to trade a company move against three
    holding days on the assumption the options are meaningfully different, when the
    solver may simply not have looked long enough to tell them apart (`SOL-013`)."""
    solver_parameters: str = ""
    """Seed and worker count. Two runs of the same problem under different parameters
    return different, equally optimal boards -- so reproducing a board needs these,
    not just the problem."""
    objective_weights: str = ""
    """The declared weights this was solved under. Boards are only comparable across
    identical weights (SPEC 4.1)."""
    required_approvals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.solver_status.is_solved:
            raise InvalidBoard(
                f"{self.board_id}: solver status is {self.solver_status}, so no "
                f"solution was proven. UNKNOWN and unvalidated solutions are not "
                f"schedules (SOL-007)."
            )
        if not self.validation_result.passed:
            raise InvalidBoard(
                f"{self.board_id}: independent validation failed, so the solver "
                f"optimised a model that does not match the production's constraints. "
                f"{self.validation_result.summary()}"
            )
        if self.validation_result.constraint_snapshot_hash != self.constraint_snapshot_hash:
            raise InvalidBoard(
                f"{self.board_id}: validated against constraint snapshot "
                f"{self.validation_result.constraint_snapshot_hash[:12]} but solved "
                f"against {self.constraint_snapshot_hash[:12]}. The board was checked "
                f"against a different problem than it answers."
            )
        if not self.assignments:
            raise InvalidBoard(f"{self.board_id}: a board with no assignments is not a board")
        if self.optimality_gap < 0:
            raise InvalidBoard(
                f"{self.board_id}: a negative optimality gap means the board beats a "
                f"bound the solver proved unbeatable, so one of the two is wrong"
            )
        if self.solver_status is SolverStatus.OPTIMAL and self.optimality_gap > 1e-9:
            raise InvalidBoard(
                f"{self.board_id}: claims {self.solver_status} while carrying a gap of "
                f"{self.optimality_gap:.4f}. Optimal means proven, so the two cannot "
                f"both be true."
            )

    @property
    def days(self) -> tuple[ShootDay, ...]:
        """Assignments grouped into ordered shoot days."""
        by_date: dict[dt.date, list[Assignment]] = {}
        for a in self.assignments:
            by_date.setdefault(a.shoot_day, []).append(a)
        return tuple(
            ShootDay(date=d, assignments=tuple(by_date[d])) for d in sorted(by_date)
        )

    @property
    def is_proven_optimal(self) -> bool:
        """Whether no better board exists, as distinct from none having been found."""
        return self.solver_status is SolverStatus.OPTIMAL

    @property
    def cost_bracket(self) -> str:
        """What this board costs, and what it might have cost at best."""
        if self.is_proven_optimal:
            return f"{self.solver_objective_value:g} (proven optimal)"
        return (
            f"{self.solver_objective_value:g}, best possible "
            f"{self.solver_best_bound:g} — within {self.optimality_gap:.1%} of optimal"
        )

    @property
    def shoot_day_count(self) -> int:
        return len({a.shoot_day for a in self.assignments})

    def day_of(self, work_id: str) -> dt.date:
        for a in self.assignments:
            if a.work_id == work_id:
                return a.shoot_day
        raise KeyError(f"{work_id} is not on this board")
