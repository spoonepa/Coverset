"""Deterministic plain-English-to-constraint candidate translation."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from .constraints import Family, Policy, SubjectKind

__all__ = [
    "ConstraintCandidate",
    "ConstraintTranslationError",
    "translate_plain_english_constraints",
]


class ConstraintTranslationError(ValueError):
    """Raised when a sentence cannot be converted into a safe candidate."""


@dataclass(frozen=True, slots=True)
class ConstraintCandidate:
    """A typed constraint proposal awaiting human acceptance."""

    id: str
    source_text: str
    constraint_payload: dict[str, Any]
    confidence: float
    requires_human_acceptance: bool = True
    validation_errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def accepted(self) -> bool:
        return bool(self.constraint_payload.get("active", False))

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_text": self.source_text,
            "constraint_payload": self.constraint_payload,
            "confidence": self.confidence,
            "requires_human_acceptance": self.requires_human_acceptance,
            "validation_errors": list(self.validation_errors),
        }


def translate_plain_english_constraints(
    production_id: str,
    text: str,
    *,
    created_by: str = "Developer",
) -> tuple[ConstraintCandidate, ...]:
    """Convert recognizable sentences into inactive typed constraint candidates.

    This translator intentionally recognizes a small controlled language. Unknown
    sentences fail closed as validation errors instead of becoming solver state.
    """
    candidates: list[ConstraintCandidate] = []
    for index, sentence in enumerate(_sentences(text), start=1):
        candidate_id = f"cand-{production_id}-{index}"
        try:
            payload = _payload_from_sentence(
                sentence,
                constraint_id=f"CON-{production_id}-{index}",
                created_by=created_by,
            )
            candidates.append(
                ConstraintCandidate(
                    id=candidate_id,
                    source_text=sentence,
                    constraint_payload=payload,
                    confidence=0.8,
                )
            )
        except ConstraintTranslationError as exc:
            candidates.append(
                ConstraintCandidate(
                    id=candidate_id,
                    source_text=sentence,
                    constraint_payload={
                        "constraint_id": f"CON-{production_id}-{index}",
                        "active": False,
                    },
                    confidence=0.0,
                    validation_errors=(str(exc),),
                )
            )
    return tuple(candidates)


def _payload_from_sentence(
    sentence: str,
    *,
    constraint_id: str,
    created_by: str,
) -> dict[str, Any]:
    lowered = sentence.lower().strip()
    if match := re.search(
        r"(?:cast|actor|performer)\s+(?P<id>[a-z0-9_-]+)\s+"
        r"(?:is\s+)?(?:only\s+)?available\s+(?:from\s+)?"
        r"(?P<start>\d{4}-\d{2}-\d{2})\s+(?:to|through|until|-|–)\s+"
        r"(?P<end>\d{4}-\d{2}-\d{2})",
        lowered,
    ):
        return _date_windows_payload(
            constraint_id,
            Family.CAST,
            SubjectKind.CAST,
            match.group("id"),
            match.group("start"),
            match.group("end"),
            created_by,
        )
    if match := re.search(
        r"(?:location|place)\s+(?P<id>[a-z0-9_-]+)\s+"
        r"(?:is\s+)?(?:available|permitted|permit(?:ted)?|open)\s+(?:from\s+)?"
        r"(?P<start>\d{4}-\d{2}-\d{2})\s+(?:to|through|until|-|–)\s+"
        r"(?P<end>\d{4}-\d{2}-\d{2})",
        lowered,
    ):
        return _date_windows_payload(
            constraint_id,
            Family.PERMIT if "permit" in lowered else Family.LOCATION,
            SubjectKind.LOCATION,
            match.group("id"),
            match.group("start"),
            match.group("end"),
            created_by,
        )
    if match := re.search(
        r"(?:location|place)\s+(?P<id>[a-z0-9_-]+).*"
        r"(?:closed|blackout|unavailable|denied).*"
        r"(?P<date>\d{4}-\d{2}-\d{2})",
        lowered,
    ):
        return _blackout_payload(
            constraint_id,
            Family.PERMIT if "permit" in lowered or "denied" in lowered else Family.LOCATION,
            SubjectKind.LOCATION,
            match.group("id"),
            match.group("date"),
            created_by,
        )
    if match := re.search(
        r"(?:work|scene)\s+(?P<id>[a-z0-9_-]+).*"
        r"(?:pin|pinned|lock|locked).*"
        r"(?P<date>\d{4}-\d{2}-\d{2})",
        lowered,
    ):
        return _pinned_day_payload(
            constraint_id,
            match.group("id"),
            match.group("date"),
            created_by,
        )
    if match := re.search(r"(?:minimum|min)\s+rest\s+(?P<hours>\d+(?:\.\d+)?)", lowered):
        return _hours_payload(
            constraint_id,
            Family.TURNAROUND,
            "minimum_rest",
            _hours(match.group("hours")),
            created_by,
        )
    if match := re.search(
        r"(?:maximum|max)\s+(?:daily\s+)?(?:shoot\s+)?hours\s+(?P<hours>\d+(?:\.\d+)?)",
        lowered,
    ):
        return _hours_payload(
            constraint_id,
            Family.BUDGET,
            "maximum_daily_hours",
            _hours(match.group("hours")),
            created_by,
        )
    raise ConstraintTranslationError(
        "no supported constraint pattern found; use cast/location availability, "
        "permit blackouts, pinned work, minimum rest, or maximum daily hours"
    )


def _date_windows_payload(
    constraint_id: str,
    family: Family,
    subject_kind: SubjectKind,
    subject_ref: str,
    start: str,
    end: str,
    created_by: str,
) -> dict[str, Any]:
    start_date = _date(start)
    end_date = _date(end)
    if end_date < start_date:
        raise ConstraintTranslationError("constraint end date precedes start date")
    return {
        "constraint_id": constraint_id,
        "family": family.value,
        "policy": Policy.HARD.value,
        "subject_kind": subject_kind.value,
        "subject_ref": subject_ref,
        "expression_type": "date_windows",
        "windows": [{"start": start_date.isoformat(), "end": end_date.isoformat()}],
        "actor_name": created_by,
        "source_type": "human",
        "source_statement": f"{subject_ref} available {start_date.isoformat()} through {end_date.isoformat()}",
        "validated_against": "coverset.constraint_translation",
        "active": False,
    }


def _blackout_payload(
    constraint_id: str,
    family: Family,
    subject_kind: SubjectKind,
    subject_ref: str,
    date_text: str,
    created_by: str,
) -> dict[str, Any]:
    day = _date(date_text)
    return {
        "constraint_id": constraint_id,
        "family": family.value,
        "policy": Policy.HARD.value,
        "subject_kind": subject_kind.value,
        "subject_ref": subject_ref,
        "expression_type": "blackout_dates",
        "dates": [day.isoformat()],
        "actor_name": created_by,
        "source_type": "human",
        "source_statement": f"{subject_ref} unavailable {day.isoformat()}",
        "validated_against": "coverset.constraint_translation",
        "active": False,
    }


def _pinned_day_payload(
    constraint_id: str,
    work_id: str,
    date_text: str,
    created_by: str,
) -> dict[str, Any]:
    day = _date(date_text)
    return {
        "constraint_id": constraint_id,
        "family": Family.LOCK.value,
        "policy": Policy.HARD.value,
        "subject_kind": SubjectKind.WORK.value,
        "subject_ref": work_id,
        "expression_type": "pinned_day",
        "day": day.isoformat(),
        "actor_name": created_by,
        "source_type": "human",
        "source_statement": f"{work_id} pinned to {day.isoformat()}",
        "validated_against": "coverset.constraint_translation",
        "active": False,
    }


def _hours_payload(
    constraint_id: str,
    family: Family,
    expression_type: str,
    hours: float,
    created_by: str,
) -> dict[str, Any]:
    if hours <= 0:
        raise ConstraintTranslationError("hours must be positive")
    return {
        "constraint_id": constraint_id,
        "family": family.value,
        "policy": Policy.HARD.value,
        "subject_kind": SubjectKind.SCHEDULE.value,
        "subject_ref": "",
        "expression_type": expression_type,
        "hours": hours,
        "actor_name": created_by,
        "source_type": "human",
        "source_statement": f"{expression_type} {hours:g} hours",
        "validated_against": "coverset.constraint_translation",
        "active": False,
    }


def _sentences(text: str) -> tuple[str, ...]:
    sentences = tuple(
        part.strip()
        for part in re.split(r"[\n.;]+", text)
        if part.strip()
    )
    if not sentences:
        raise ConstraintTranslationError("no constraint text supplied")
    return sentences


def _hours(value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ConstraintTranslationError(f"invalid hour value: {value}") from exc


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ConstraintTranslationError(f"invalid ISO date: {value}") from exc
