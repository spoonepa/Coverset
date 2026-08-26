"""Schedulable work.

A `WorkItem` is what the solver places on a day. It is deliberately not a scene: a
scene is a screenplay fact, while work is a production commitment, and the two come
apart. One scene can produce several work items across a pickup; a work item can
outlive the record it came from.

Everything the solver needs to place an item lives here and nothing else does. In
particular there is no slugline, no page count and no confidence score, because none
of those bear on when the work can happen.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["DayNight", "WorkFlags", "WorkItem", "WorkKind"]


class DayNight(StrEnum):
    """Time of day a scene plays, which bounds it against the daylight window.

    `UNKNOWN` exists because a breakdown may genuinely fail to determine it, and
    saying so is better than guessing. It cannot reach the solver: `WorkItem`
    rejects it, since work that could be day or night has no daylight bound at all
    and would be scheduled as though unconstrained.
    """

    DAY = "day"
    NIGHT = "night"
    DAWN = "dawn"
    DUSK = "dusk"
    UNKNOWN = "unknown"

    @property
    def needs_daylight(self) -> bool:
        """Whether this must fall inside the sun-above-horizon window."""
        return self is DayNight.DAY


class WorkKind(StrEnum):
    """Why this work exists. A pickup traces to a human decision; a scene does not."""

    SCENE = "scene"
    PICKUP = "pickup"


@dataclass(frozen=True, slots=True)
class WorkFlags:
    """Conditions that change how work may be scheduled, not merely how it is shot."""

    stunts: bool = False
    minors: bool = False
    vfx: bool = False

    def __str__(self) -> str:
        set_flags = [n for n in ("stunts", "minors", "vfx") if getattr(self, n)]
        return ", ".join(set_flags) or "none"

    @property
    def any_set(self) -> bool:
        return self.stunts or self.minors or self.vfx


@dataclass(frozen=True, slots=True)
class WorkItem:
    """One unit of work the solver can place on a shoot day."""

    work_id: str
    kind: WorkKind
    scene_id: str
    location_id: str
    day_night: DayNight
    estimated_duration_minutes: int
    cast_ids: tuple[str, ...] = ()
    flags: WorkFlags = WorkFlags()
    must_complete_by: dt.date | None = None
    source_record_id: str = ""
    """The `SceneRecord` or `PickupTask` this came from, for the audit trail."""

    def __post_init__(self) -> None:
        if not self.work_id.strip():
            raise ValueError("work needs a stable id")
        if not self.location_id.strip():
            raise ValueError(f"{self.work_id}: work must name where it happens")
        if self.estimated_duration_minutes <= 0:
            raise ValueError(
                f"{self.work_id}: work must have a positive duration, got "
                f"{self.estimated_duration_minutes}"
            )
        if self.day_night is DayNight.UNKNOWN:
            raise ValueError(
                f"{self.work_id}: day/night is unknown, so the work has no daylight "
                f"bound and would be scheduled as though unconstrained. Resolve it "
                f"on the scene record before converting."
            )

    @property
    def duration(self) -> dt.timedelta:
        return dt.timedelta(minutes=self.estimated_duration_minutes)

    @property
    def is_pickup(self) -> bool:
        return self.kind is WorkKind.PICKUP
