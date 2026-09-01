"""Typed constraint records.

A constraint is the only way a fact reaches the solver. Daylight arithmetic, a
retrieved permit window, an AD typing "Sarah is out until the 14th" — all of it
converges here, because the solver must not be able to tell where a bound came from
while still being able to prove where it came from afterwards.

Two properties matter more than the schema itself:

**A record carries its own provenance, and the shape of that provenance is fixed by
the family.** A daylight constraint sourced from a URL is not a daylight constraint;
it is a retrieved number wearing one, which is the exact mistake `daylight.py` exists
to prevent. `CON-008` is enforced by making the combination unconstructible rather
than by checking a flag.

**Nothing is optional in a way that fails quietly.** A constraint with no expression,
no subject, or no source cannot be built. `CON-005` extends that across the set: a
record naming a performer, place or work item that does not exist blocks the solve
rather than being skipped, because a constraint the solver never learns about is one
the board is free to violate.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from .actors import Actor
from .daylight import ALGORITHM
from .people import AvailabilityWindow

__all__ = [
    "AlgorithmSource",
    "BlackoutDates",
    "ConstraintError",
    "ConstraintRecord",
    "ConstraintSet",
    "DateWindows",
    "DaylightBound",
    "DerivedFrom",
    "Expression",
    "Family",
    "GroundedSource",
    "HumanSource",
    "MaximumDailyHours",
    "MinimumRest",
    "PinnedDay",
    "Policy",
    "Provenance",
    "Subject",
    "SubjectKind",
    "UnresolvedConstraints",
]


class ConstraintError(Exception):
    """A constraint record could not be trusted to reach the solver."""


class UnresolvedConstraints(ConstraintError):
    """Constraints referenced things the production does not have (CON-005).

    Carries every problem, not the first: the same reason `Roster.resolve` names all
    unknown cast ids at once. Someone repairing a constraint file wants the list.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        body = "\n  ".join(problems)
        super().__init__(
            f"{len(problems)} constraint problem(s); solving is blocked until they "
            f"are corrected, waived or rejected:\n  {body}"
        )


class Family(StrEnum):
    """What kind of fact this constrains. Normative list from SPEC 5.5."""

    CAST = "cast"
    LOCATION = "location"
    PERMIT = "permit"
    DAYLIGHT = "daylight"
    TURNAROUND = "turnaround"
    COMPANY_MOVE = "company_move"
    WEATHER = "weather"
    LOCK = "lock"
    BUDGET = "budget"


class Policy(StrEnum):
    """How the solver must treat this. Normative vocabulary from SPEC section 4."""

    HARD = "hard"
    SOFT_PENALTY = "soft_penalty"
    WAIVABLE_BY_ROLE = "waivable_by_role"
    OBJECTIVE_ONLY = "objective_only"
    INFORMATIONAL = "informational"

    @property
    def bounds_feasibility(self) -> bool:
        """Whether an active board is forbidden from violating this.

        `waivable_by_role` counts: it binds while unwaived, and a waiver produces an
        `ExceptionScenario` rather than a quietly relaxed board (SPEC section 4).
        """
        return self in (Policy.HARD, Policy.WAIVABLE_BY_ROLE)

    @property
    def reaches_solver(self) -> bool:
        """Whether the solver sees this at all. Informational terms are display-only."""
        return self is not Policy.INFORMATIONAL


class DerivedFrom(StrEnum):
    """Where the value physically came from, for the audit trail."""

    FULL_CONTENT = "full_content"
    EXCERPT = "excerpt"
    ALGORITHM = "algorithm"
    HUMAN_INPUT = "human_input"
    FIXTURE = "fixture"


class SubjectKind(StrEnum):
    """What a constraint is about. Typed so a cast id cannot be read as a work id."""

    CAST = "cast"
    LOCATION = "location"
    WORK = "work"
    DAY = "day"
    SCHEDULE = "schedule"


@dataclass(frozen=True, slots=True)
class Subject:
    """The thing constrained, named by kind as well as id.

    A bare string cannot say whether `SARAH` is a performer or a location, and this
    project has already been bitten once by an untyped domain reference.
    """

    kind: SubjectKind
    ref: str = ""

    def __post_init__(self) -> None:
        if self.kind is SubjectKind.SCHEDULE:
            if self.ref:
                raise ConstraintError(
                    f"a schedule-wide constraint has no specific subject, got {self.ref!r}"
                )
            return
        if not self.ref.strip():
            raise ConstraintError(f"a {self.kind} constraint must name its subject")

    def __str__(self) -> str:
        return f"{self.kind}:{self.ref}" if self.ref else str(self.kind)


# -- expressions ---------------------------------------------------------------
#
# Each expression answers one question about one day, and answers it the same way
# for the compiler and for the validator. That shared, tiny surface is deliberate:
# it is the only thing the two independent readings of a record have in common, so
# a disagreement between them is a real miscompile rather than a definition drift.


@dataclass(frozen=True, slots=True)
class DateWindows:
    """The subject may be scheduled only inside these windows.

    Cast availability and permitted shooting windows are the same shape. Empty is
    rejected rather than read as "unrestricted": a window list that lost its contents
    somewhere upstream would otherwise silently widen the feasible region.
    """

    windows: tuple[AvailabilityWindow, ...]

    def __post_init__(self) -> None:
        if not self.windows:
            raise ConstraintError(
                "a date-window constraint with no windows would permit every day; "
                "state the windows, or do not create the constraint"
            )

    def allows(self, day: dt.date) -> bool:
        return any(w.covers(day) for w in self.windows)

    def __str__(self) -> str:
        return "within " + ", ".join(str(w) for w in self.windows)


@dataclass(frozen=True, slots=True)
class BlackoutDates:
    """The subject may not be scheduled on these dates. A permit denial, typically."""

    dates: tuple[dt.date, ...]

    def __post_init__(self) -> None:
        if not self.dates:
            raise ConstraintError("a blackout with no dates constrains nothing")
        object.__setattr__(self, "dates", tuple(sorted(set(self.dates))))

    def allows(self, day: dt.date) -> bool:
        return day not in self.dates

    def __str__(self) -> str:
        return "not on " + ", ".join(d.isoformat() for d in self.dates)


@dataclass(frozen=True, slots=True)
class DaylightBound:
    """Work needing sun must fit inside the computed window on its day.

    Carries no times. The window is recomputed at solve time from the date and the
    location (`DAY-008`), because a stored sunset is a sunset for whichever date it
    was stored on — which is precisely the bug that produced this module's rule.
    """

    algorithm: str = ALGORITHM

    def __post_init__(self) -> None:
        if not self.algorithm.strip():
            raise ConstraintError("a daylight bound must name the algorithm computing it")

    def __str__(self) -> str:
        return f"inside the daylight window ({self.algorithm})"


@dataclass(frozen=True, slots=True)
class MinimumRest:
    """Hours that must elapse between one day's wrap and the next day's call.

    Separate type from `MaximumDailyHours` rather than one hours field with a mode
    flag, because the two bound opposite directions. A flag read the wrong way turns
    a floor into a ceiling and produces a board that is well-formed, plausible and
    exactly wrong -- the failure this codebase keeps meeting.
    """

    hours: float

    def __post_init__(self) -> None:
        if not 0 < self.hours <= 24:
            raise ConstraintError(f"rest hours must fall in (0, 24], got {self.hours}")

    @property
    def minutes(self) -> int:
        return round(self.hours * 60)

    def __str__(self) -> str:
        return f"at least {self.hours:g}h rest"


@dataclass(frozen=True, slots=True)
class MaximumDailyHours:
    """The longest day the subject may work. A company day, or a minor's legal limit."""

    hours: float

    def __post_init__(self) -> None:
        if not 0 < self.hours <= 24:
            raise ConstraintError(f"daily hours must fall in (0, 24], got {self.hours}")

    @property
    def minutes(self) -> int:
        return round(self.hours * 60)

    def __str__(self) -> str:
        return f"at most {self.hours:g}h per day"


@dataclass(frozen=True, slots=True)
class PinnedDay:
    """This work happens on this day and no other. A lock, or a fixed external date."""

    day: dt.date

    def __str__(self) -> str:
        return f"on {self.day.isoformat()}"


Expression: TypeAlias = (
    DateWindows
    | BlackoutDates
    | DaylightBound
    | MinimumRest
    | MaximumDailyHours
    | PinnedDay
)


# -- provenance ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GroundedSource:
    """A value retrieved from the web, carrying what proves it.

    Both the evidence id and at least one URL are required. A grounded value whose
    sources were dropped is indistinguishable from a guess.
    """

    evidence_id: str
    source_urls: tuple[str, ...]
    grounded_value_id: str = ""
    source_mode: DerivedFrom = DerivedFrom.EXCERPT

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ConstraintError("a grounded constraint must cite its evidence")
        if not self.source_urls:
            raise ConstraintError(
                "a grounded constraint must cite at least one source URL; without one "
                "the value is a guess with a citation field"
            )
        if self.source_mode not in (DerivedFrom.FULL_CONTENT, DerivedFrom.EXCERPT):
            raise ConstraintError(
                "a grounded constraint must say whether it came from full content "
                "or excerpts"
            )

    @property
    def derived_from(self) -> DerivedFrom:
        return self.source_mode

    def describe(self) -> str:
        return f"evidence {self.evidence_id} ({len(self.source_urls)} source(s))"


@dataclass(frozen=True, slots=True)
class AlgorithmSource:
    """A value computed by a named, versioned algorithm.

    This is what stands where a URL stands for a retrieved fact. It is stronger, not
    weaker, provenance: the computation can be rerun and checked against published
    tables, whereas a retrieval can only be compared against another retrieval.
    """

    name: str = ALGORITHM
    version: str = "noaa-1"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ConstraintError("an algorithmic constraint must name its algorithm")
        if not self.version.strip():
            raise ConstraintError(
                "an algorithmic constraint must state a version; a board solved under "
                "one version of the arithmetic is not comparable to one solved under "
                "another"
            )

    @property
    def derived_from(self) -> DerivedFrom:
        return DerivedFrom.ALGORITHM

    def describe(self) -> str:
        return f"{self.name} v{self.version}"


@dataclass(frozen=True, slots=True)
class HumanSource:
    """A production rule someone stated. The author is required, so it can be queried."""

    author: Actor
    statement: str
    from_fixture: bool = False

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise ConstraintError(
                "a human-entered constraint must record what was actually stated, so a "
                "disputed bound can be taken back to the person who set it"
            )

    @property
    def derived_from(self) -> DerivedFrom:
        return DerivedFrom.FIXTURE if self.from_fixture else DerivedFrom.HUMAN_INPUT

    def describe(self) -> str:
        return f"{self.author}: {self.statement!r}"


Provenance: TypeAlias = GroundedSource | AlgorithmSource | HumanSource


# -- the record ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConstraintRecord:
    """One typed bound on the schedule, with its provenance and its policy."""

    constraint_id: str
    family: Family
    policy: Policy
    subject: Subject
    expression: Expression
    source: Provenance
    created_by: str = ""
    """Actor string or system component that produced the record."""
    validated_against: str = ""
    """What checked it: a fact-family validator, a schema, an almanac table."""
    active: bool = True
    activated_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        if not self.constraint_id.strip():
            raise ConstraintError("a constraint needs a stable id")

        # CON-008, made unrepresentable rather than checked. A daylight bound backed
        # by a URL is a retrieved sunset, and a retrieved sunset was wrong for the
        # shoot date in 8 of 8 live sources.
        if self.family is Family.DAYLIGHT and not isinstance(self.source, AlgorithmSource):
            raise ConstraintError(
                f"{self.constraint_id}: a daylight constraint must cite the "
                f"deterministic algorithm, not "
                f"{type(self.source).__name__.replace('Source', '').lower()} "
                f"provenance. Daylight is computed; retrieving it was tried and was "
                f"wrong in the worst way (CON-008)."
            )
        if self.family is Family.DAYLIGHT and not isinstance(self.expression, DaylightBound):
            raise ConstraintError(
                f"{self.constraint_id}: a daylight constraint's expression must be a "
                f"DaylightBound, got {type(self.expression).__name__}"
            )
        if not isinstance(
            self.expression, (DaylightBound, MinimumRest, MaximumDailyHours)
        ) and (
            self.subject.kind is SubjectKind.SCHEDULE
        ):
            raise ConstraintError(
                f"{self.constraint_id}: {type(self.expression).__name__} constrains a "
                f"specific subject, but none was named"
            )

    @property
    def derived_from(self) -> DerivedFrom:
        return self.source.derived_from

    @property
    def binds(self) -> bool:
        """Active and feasibility-bounding: the solver must not produce a violation."""
        return self.active and self.policy.bounds_feasibility

    def deactivate(self) -> ConstraintRecord:
        """Return a copy that no longer binds. The original is untouched.

        Transitions return new instances so the record that bound a past board still
        exists to explain it.
        """
        from dataclasses import replace

        return replace(self, active=False)

    def canonical(self) -> dict[str, object]:
        """A stable, order-independent dict for hashing. Excludes nothing that binds."""
        return {
            "constraint_id": self.constraint_id,
            "family": str(self.family),
            "policy": str(self.policy),
            "subject": str(self.subject),
            "expression": f"{type(self.expression).__name__}({self.expression})",
            "source": self.source.describe(),
            "derived_from": str(self.derived_from),
            "active": self.active,
        }

    def __str__(self) -> str:
        state = "" if self.active else " [inactive]"
        return (
            f"{self.constraint_id} {self.policy} {self.family} "
            f"{self.subject} {self.expression}{state}"
        )

    def explain(self) -> str:
        """One line an AD can read, tracing the bound back to what produced it."""
        return f"{self} — from {self.source.describe()}"


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    """Every constraint on a problem, hashable as a snapshot.

    The hash is what makes a board auditable after the fact (`AUD-005`): it pins the
    exact set the board was solved and validated against, so a board that outlived a
    constraint change can be identified as stale rather than quietly trusted.
    """

    records: tuple[ConstraintRecord, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for r in self.records:
            if r.constraint_id in seen:
                raise ConstraintError(f"duplicate constraint id: {r.constraint_id}")
            seen.add(r.constraint_id)

    def __iter__(self) -> Iterator[ConstraintRecord]:
        yield from self.records

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, constraint_id: str) -> ConstraintRecord:
        for r in self.records:
            if r.constraint_id == constraint_id:
                return r
        raise KeyError(f"no constraint {constraint_id!r}")

    @property
    def active(self) -> tuple[ConstraintRecord, ...]:
        return tuple(r for r in self.records if r.active)

    @property
    def binding(self) -> tuple[ConstraintRecord, ...]:
        """Active constraints an accepted board may not violate."""
        return tuple(r for r in self.records if r.binds)

    def of_family(self, *families: Family) -> tuple[ConstraintRecord, ...]:
        return tuple(r for r in self.records if r.family in families)

    @property
    def snapshot_hash(self) -> str:
        """SHA-256 over the canonical form of every record, order-independent.

        Sorted by id so two sets differing only in ordering hash alike — otherwise a
        board would appear stale because a file was re-serialised.
        """
        payload = json.dumps(
            [r.canonical() for r in sorted(self.records, key=lambda r: r.constraint_id)],
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def resolve(
        self,
        *,
        cast_ids: frozenset[str],
        location_ids: frozenset[str],
        work_ids: frozenset[str],
        calendar: tuple[dt.date, ...] = (),
    ) -> None:
        """Check every reference against what the production actually has (CON-005).

        Raises on the whole list rather than the first problem. A constraint naming a
        performer who does not exist is not a no-op — it is a bound that silently
        fails to apply, which is how a board comes to violate a rule nobody removed.

        Raises:
            UnresolvedConstraints: listing every unresolved reference found.
        """
        known = {
            SubjectKind.CAST: (cast_ids, "the roster"),
            SubjectKind.LOCATION: (location_ids, "the production's locations"),
            SubjectKind.WORK: (work_ids, "the problem's work items"),
        }
        problems: list[str] = []
        for r in self.active:
            if (entry := known.get(r.subject.kind)) is not None:
                ids, where = entry
                if r.subject.ref not in ids:
                    problems.append(
                        f"{r.constraint_id}: {r.subject.kind} {r.subject.ref!r} is not "
                        f"on {where}"
                    )
            if calendar and isinstance(r.expression, PinnedDay):
                if r.expression.day not in calendar:
                    problems.append(
                        f"{r.constraint_id}: pinned to {r.expression.day.isoformat()}, "
                        f"which is not a shooting day on the calendar"
                    )
            if calendar and isinstance(r.expression, DateWindows):
                if not any(r.expression.allows(d) for d in calendar):
                    problems.append(
                        f"{r.constraint_id}: {r.expression} excludes every day on the "
                        f"calendar, so nothing it governs can ever be scheduled"
                    )
        if problems:
            raise UnresolvedConstraints(problems)
