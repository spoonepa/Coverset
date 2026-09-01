"""Monitoring records that detect changed facts without deciding schedules.

The monitor boundary is deliberately weaker than the human review boundary: it can
observe a source, normalize a changed fact, and request that alternatives be
computed. It cannot select one of those alternatives. Board selection remains a
First AD decision in :mod:`coverset.review`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "ChangeEvent",
    "FindingStatus",
    "Materiality",
    "MonitoredSource",
    "ReplanRequest",
    "fingerprint_value",
]


class FindingStatus(StrEnum):
    """Lifecycle for monitor-created findings."""

    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NON_MATERIAL = "non_material"


@dataclass(frozen=True, slots=True)
class Materiality:
    """Whether a changed source is schedule-relevant."""

    material: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("materiality must explain the decision")


@dataclass(frozen=True, slots=True)
class MonitoredSource:
    """A source URL watched on behalf of a solved schedule."""

    id: str
    schedule_version_id: str
    evidence_id: str
    url: str
    fact_kind: str
    affected_work_ids: tuple[str, ...]
    fingerprint: str
    monitor_subscription_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "schedule_version_id",
            "evidence_id",
            "url",
            "fact_kind",
            "fingerprint",
            "monitor_subscription_id",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"monitored source must set {field_name}")
        if not self.affected_work_ids:
            raise ValueError("monitored source must name affected work ids")


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """A normalized page/source change, before any human decision."""

    id: str
    monitored_source_id: str
    url: str
    old_fingerprint: str
    new_fingerprint: str
    materiality: Materiality
    old_value: dict[str, Any] = field(default_factory=dict)
    new_value: dict[str, Any] = field(default_factory=dict)
    detected_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def __post_init__(self) -> None:
        for field_name in ("id", "monitored_source_id", "url"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"change event must set {field_name}")
        if self.old_fingerprint == self.new_fingerprint and self.materiality.material:
            raise ValueError("unchanged fingerprints cannot be material")


@dataclass(frozen=True, slots=True)
class ReplanRequest:
    """A request to compute alternatives, not to select a board."""

    id: str
    production_id: str
    trigger_event_id: str
    current_board_id: str
    locked_day_ids: tuple[str, ...]
    affected_work_ids: tuple[str, ...]
    requester_component: str
    status: str = "requested"
    selected_board_id: str | None = None
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def __post_init__(self) -> None:
        if self.selected_board_id is not None:
            raise ValueError("a replan request cannot select a board")
        for field_name in (
            "id",
            "production_id",
            "trigger_event_id",
            "current_board_id",
            "requester_component",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"replan request must set {field_name}")


def fingerprint_value(value: dict[str, Any]) -> str:
    """Return a stable fingerprint for a normalized fact value."""
    import hashlib
    import json

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
