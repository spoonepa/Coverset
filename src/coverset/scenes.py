"""Screenplay scene records.

A `SceneRecord` is what a breakdown produces: the screenplay's own facts about a
scene, plus enough structure to schedule it. It is not yet schedulable work — that
is `WorkItem`, and the conversion is deliberately narrow.

Records may be derived by a language model, so they arrive as *candidates*. Only an
active record converts to work. A candidate, a rejected record, or one flagged for
review cannot reach the solver, for the same reason an advisory review finding
cannot create a pickup: the model proposes and a person or a validator disposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .work import DayNight, WorkFlags, WorkItem, WorkKind

__all__ = [
    "MINUTES_PER_EIGHTH",
    "CandidateStatus",
    "IntExt",
    "NotSchedulable",
    "SceneRecord",
]

MINUTES_PER_EIGHTH = 7.5
"""Planning heuristic: one script page takes roughly an hour to shoot, and a page is
eight eighths.

A rate, not a measurement. Real shooting time varies enormously — a page of dialogue
between two people in a single setup is far quicker than a page of a stunt, and both
are quicker than a page of VFX plate work. Production overrides this per scene where
it matters; the default exists so a fixture board can be built without inventing a
number for every scene. Durations round to the nearest minute (BRK-005).
"""


class NotSchedulable(Exception):
    """A record was asked to become work before it was fit to.

    Raised rather than converting quietly. A candidate scene that reaches the solver
    is a scene the board commits a crew day to on a model's unreviewed say-so.
    """


class IntExt(StrEnum):
    """Where the scene plays, which decides whether daylight bounds it at all."""

    INT = "int"
    EXT = "ext"
    INT_EXT = "int_ext"
    UNKNOWN = "unknown"


class CandidateStatus(StrEnum):
    """How far a record has got from proposal to production fact."""

    CANDIDATE = "candidate"
    NEEDS_REVIEW = "needs_review"
    ACTIVE = "active"
    REJECTED = "rejected"

    @property
    def is_schedulable(self) -> bool:
        return self is CandidateStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class SceneRecord:
    """One scene, as broken down from the screenplay."""

    scene_id: str
    scene_number: str
    """The screenplay's own numbering, which is not always numeric -- `12A` is normal."""
    slugline: str
    int_ext: IntExt
    day_night: DayNight
    location_ref: str
    page_eighths: int
    cast_ids: tuple[str, ...] = ()
    flags: WorkFlags = WorkFlags()
    source_page_range: str = ""
    """Where in the script this came from, so a disputed breakdown can be checked."""
    confidence: float | None = None
    """Present for model-derived records, absent for hand-entered ones."""
    status: CandidateStatus = CandidateStatus.CANDIDATE

    def __post_init__(self) -> None:
        if not self.scene_id.strip():
            raise ValueError("a scene needs a stable id")
        if not self.scene_number.strip():
            raise ValueError(f"{self.scene_id}: scene number is required")
        if not self.location_ref.strip():
            raise ValueError(f"{self.scene_id}: scene must name where it plays")
        if self.page_eighths <= 0:
            raise ValueError(
                f"{self.scene_id}: page eighths must be positive, got {self.page_eighths}"
            )
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"{self.scene_id}: confidence out of range: {self.confidence}"
            )

    @property
    def is_exterior(self) -> bool:
        return self.int_ext in (IntExt.EXT, IntExt.INT_EXT)

    @property
    def needs_daylight(self) -> bool:
        """Whether the sun must be up for this scene.

        Exterior and DAY. An interior day scene on a stage needs no daylight window;
        a practical interior with windows arguably does, which production knows and
        this model does not — such scenes are marked `INT_EXT` in practice.
        """
        return self.is_exterior and self.day_night.needs_daylight

    @property
    def estimated_minutes(self) -> int:
        """Shooting time implied by page count, at the declared planning rate."""
        return max(1, round(self.page_eighths * MINUTES_PER_EIGHTH))

    def to_work_item(self, *, minutes: int | None = None) -> WorkItem:
        """Convert an active record into work the solver can place.

        Raises:
            NotSchedulable: the record is not active, or its day/night is unresolved.
        """
        if not self.status.is_schedulable:
            raise NotSchedulable(
                f"{self.scene_id} is {self.status}, not active; only an accepted "
                f"record may become scheduled work"
            )
        if self.day_night is DayNight.UNKNOWN:
            raise NotSchedulable(
                f"{self.scene_id}: day/night is unresolved, so the work would carry "
                f"no daylight bound. Resolve it before scheduling."
            )
        return WorkItem(
            work_id=f"W-{self.scene_id}",
            kind=WorkKind.SCENE,
            scene_id=self.scene_id,
            location_id=self.location_ref,
            day_night=self.day_night,
            estimated_duration_minutes=minutes or self.estimated_minutes,
            cast_ids=self.cast_ids,
            flags=self.flags,
            source_record_id=self.scene_id,
        )
