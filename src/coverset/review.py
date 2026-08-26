"""Coverage review, human decision, and pickup work.

Gemini may look at a scene's coverage and say something looks wrong. It may not act
on that. The AD or Director decides, and only then does the solver get new work.

That boundary is enforced by construction rather than by convention, for the same
reason the board comes from CP-SAT rather than a model: a rule that lives only in a
docstring is a rule that gets bypassed under deadline pressure, and this one has real
money behind it. A pickup day costs a crew day.

The mechanics:

- `ReviewFinding` has no disposition field. There is nothing on it to set, so it
  cannot express an outcome even in principle -- the only transition it can cause is
  to `NEEDS_REVIEW`.
- `ReviewDecision` requires an `Actor` holding a human production role with the
  authority to rule on coverage. `Role` has no member for an automated agent, so the
  refusal is structural rather than a name check.
- `PickupTask` cannot be constructed without a decision that authorises one.

Each of those is a separate lock, because the interesting failure is not someone
deliberately bypassing the rule. It is a well-meaning refactor that quietly wires the
advisory path into the acting path.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .actors import Actor
from .locations import Location

__all__ = [
    "CoverageItem",
    "CoverageStatus",
    "CoverageType",
    "Disposition",
    "InvalidTransition",
    "PickupTask",
    "ReviewDecision",
    "ReviewError",
    "ReviewFinding",
]

class ReviewError(Exception):
    """Base for review-workflow violations."""


class InvalidTransition(ReviewError):
    """A coverage item was moved between states in an order that cannot happen."""


class CoverageType(StrEnum):
    """A planned shot within a scene's coverage."""

    ESTABLISHING = "establishing"
    WIDE = "wide"
    CLOSE_UP = "close_up"
    REVERSE = "reverse"
    INSERT = "insert"


class CoverageStatus(StrEnum):
    """Where a coverage item sits in the shoot-and-review lifecycle."""

    PLANNED = "planned"
    SHOT = "shot"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PICKUP_REQUESTED = "pickup_requested"


class Disposition(StrEnum):
    """What the AD or Director decided about a flagged item."""

    ACCEPT = "accept"
    REJECT = "reject"
    REQUEST_PICKUP = "request_pickup"

    @property
    def creates_pickup(self) -> bool:
        """Rejecting coverage and requesting a pickup both mean the work recurs."""
        return self in (Disposition.REJECT, Disposition.REQUEST_PICKUP)


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    """Something Gemini noticed about a coverage item. Advisory, and only advisory.

    Deliberately has no disposition, no severity that maps to an action, and no
    method that changes anything. It reports; it does not conclude. The strongest
    effect it can have is putting the item in front of a human.
    """

    id: str
    coverage_item_id: str
    summary: str
    detail: str = ""
    raised_by: str = "gemini"
    confidence: float | None = None
    raised_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("a review finding must say what it noticed")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """The AD or Director's ruling on a finding. The only thing that can act."""

    finding_id: str
    coverage_item_id: str
    disposition: Disposition
    decided_by: Actor
    note: str = ""
    decided_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def __post_init__(self) -> None:
        # Raises unless the actor's role carries creative authority over coverage.
        # An advisory agent cannot reach this check at all -- it cannot be an Actor.
        self.decided_by.require("rule_on_coverage")


@dataclass(frozen=True, slots=True)
class CoverageItem:
    """One planned shot, carrying what the solver needs to place or re-place it."""

    id: str
    scene_id: str
    coverage_type: CoverageType
    location: Location
    required_cast: tuple[str, ...] = ()
    estimated_eighths: int = 1
    status: CoverageStatus = CoverageStatus.PLANNED
    finding: ReviewFinding | None = None
    decision: ReviewDecision | None = None

    def __post_init__(self) -> None:
        if self.estimated_eighths <= 0:
            raise ValueError(
                f"{self.id}: coverage must have a duration; got "
                f"{self.estimated_eighths} eighths"
            )

    # -- transitions -------------------------------------------------------
    # Each returns a new item. Nothing mutates, so the history of a decision is
    # not overwritten by the next one.

    def mark_shot(self) -> CoverageItem:
        """Record that the item was photographed on the day."""
        if self.status is not CoverageStatus.PLANNED:
            raise InvalidTransition(
                f"{self.id}: only planned coverage can be marked shot "
                f"(currently {self.status})"
            )
        return replace(self, status=CoverageStatus.SHOT)

    def flag_for_review(self, finding: ReviewFinding) -> CoverageItem:
        """Put the item in front of the AD or Director. The most a finding can do.

        Note what this does *not* accept: a disposition. There is no parameter here
        through which an advisory finding could express an outcome.
        """
        if finding.coverage_item_id != self.id:
            raise ReviewError(
                f"finding {finding.id} concerns {finding.coverage_item_id}, "
                f"not {self.id}"
            )
        if self.status is CoverageStatus.PLANNED:
            raise InvalidTransition(
                f"{self.id}: nothing to review -- the item has not been shot yet"
            )
        return replace(self, status=CoverageStatus.NEEDS_REVIEW, finding=finding)

    def decide(self, decision: ReviewDecision) -> tuple[CoverageItem, PickupTask | None]:
        """Apply the human ruling, returning the updated item and any pickup work.

        Accepting returns no task. Rejecting or requesting a pickup returns exactly
        one, authorised by this decision.
        """
        if self.status is not CoverageStatus.NEEDS_REVIEW:
            raise InvalidTransition(
                f"{self.id}: nothing awaiting decision (currently {self.status})"
            )
        if decision.coverage_item_id != self.id:
            raise ReviewError(
                f"decision concerns {decision.coverage_item_id}, not {self.id}"
            )
        if self.finding is None or decision.finding_id != self.finding.id:
            raise ReviewError(
                f"{self.id}: decision must respond to the finding that raised it "
                f"({self.finding.id if self.finding else 'none'})"
            )

        status = {
            Disposition.ACCEPT: CoverageStatus.ACCEPTED,
            Disposition.REJECT: CoverageStatus.REJECTED,
            Disposition.REQUEST_PICKUP: CoverageStatus.PICKUP_REQUESTED,
        }[decision.disposition]
        decided = replace(self, status=status, decision=decision)

        if not decision.disposition.creates_pickup:
            return decided, None
        return decided, PickupTask.from_decision(decided, decision)

    @property
    def awaits_decision(self) -> bool:
        return self.status is CoverageStatus.NEEDS_REVIEW


@dataclass(frozen=True, slots=True)
class PickupTask:
    """Re-shoot work admitted to the schedule, authorised by a named human.

    Constructing one requires a decision that warrants it. There is no path from a
    finding to a pickup that does not pass through a person.
    """

    id: str
    scene_id: str
    coverage_item_id: str
    coverage_type: CoverageType
    location: Location
    decision: ReviewDecision
    required_cast: tuple[str, ...] = ()
    estimated_eighths: int = 1
    must_complete_by: dt.date | None = None
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def __post_init__(self) -> None:
        if not self.decision.disposition.creates_pickup:
            raise ReviewError(
                f"{self.decision.disposition} does not authorise a pickup -- only "
                f"a rejection or an explicit pickup request does"
            )
        if self.decision.coverage_item_id != self.coverage_item_id:
            raise ReviewError("pickup task and its authorising decision disagree")
        if self.estimated_eighths <= 0:
            raise ValueError(f"{self.id}: pickup work must have a duration")

    @classmethod
    def from_decision(
        cls,
        item: CoverageItem,
        decision: ReviewDecision,
        *,
        must_complete_by: dt.date | None = None,
    ) -> PickupTask:
        """Derive the re-shoot from the item it replaces and the ruling that ordered it."""
        return cls(
            id=f"PU-{item.id}",
            scene_id=item.scene_id,
            coverage_item_id=item.id,
            coverage_type=item.coverage_type,
            location=item.location,
            decision=decision,
            required_cast=item.required_cast,
            estimated_eighths=item.estimated_eighths,
            must_complete_by=must_complete_by,
        )

    @property
    def authorised_by(self) -> Actor:
        """The person accountable for this appearing on the board."""
        return self.decision.decided_by

    def audit_trail(self, finding: ReviewFinding | None = None) -> str:
        """One line tracing this work back through the decision to what prompted it."""
        chain = (
            f"{self.id} ({self.coverage_type} for scene {self.scene_id}) "
            f"<- {self.decision.disposition} by {self.decision.decided_by} "
            f"at {self.decision.decided_at:%Y-%m-%d %H:%M}Z"
        )
        if finding is not None:
            chain += f" <- finding {finding.id} raised by {finding.raised_by}: {finding.summary}"
        return chain
