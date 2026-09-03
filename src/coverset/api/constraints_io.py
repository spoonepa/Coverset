"""Persistence conversion for grounding evidence and typed constraints."""

from __future__ import annotations

import datetime as dt
from typing import Any

from coverset.actors import Actor, Role
from coverset.constraints import (
    AlgorithmSource,
    BlackoutDates,
    ConstraintRecord,
    DateWindows,
    DaylightBound,
    DerivedFrom,
    Expression,
    Family,
    GroundedSource,
    HumanSource,
    MaximumDailyHours,
    MinimumRest,
    PinnedDay,
    Policy,
    Provenance,
    Subject,
    SubjectKind,
)
from coverset.grounding import Evidence, SourceExcerpt
from coverset.people import AvailabilityWindow


def evidence_to_json(evidence: Evidence) -> dict[str, Any]:
    return {
        "kind": evidence.kind.value,
        "location": {
            "id": evidence.location.id,
            "name": evidence.location.name,
            "place": evidence.location.place,
        },
        "date": evidence.date.isoformat(),
        "search_id": evidence.search_id,
        "session_id": evidence.session_id,
        "retrieved_at": evidence.retrieved_at.isoformat(),
        "escalated": evidence.escalated,
        "covering_urls": list(evidence.covering_urls),
        "source_urls": list(evidence.source_urls),
        "sources": [
            {
                "url": source.url,
                "title": source.title,
                "publish_date": source.publish_date,
                "excerpts": list(source.excerpts),
                "full_content": source.full_content,
            }
            for source in evidence.sources
        ],
    }


def evidence_from_json(data: dict[str, Any]) -> tuple[SourceExcerpt, ...]:
    return tuple(
        SourceExcerpt(
            url=str(source.get("url", "")),
            title=source.get("title"),
            publish_date=source.get("publish_date"),
            excerpts=tuple(str(item) for item in source.get("excerpts", ())),
            full_content=source.get("full_content"),
        )
        for source in data.get("sources", ())
    )


def constraint_to_json(record: ConstraintRecord) -> dict[str, Any]:
    return {
        "constraint_id": record.constraint_id,
        "family": record.family.value,
        "policy": record.policy.value,
        "subject": {"kind": record.subject.kind.value, "ref": record.subject.ref},
        "expression": _expression_to_json(record.expression),
        "source": _source_to_json(record.source),
        "created_by": record.created_by,
        "validated_against": record.validated_against,
        "active": record.active,
        "activated_at": record.activated_at.isoformat()
        if record.activated_at
        else None,
    }


def constraint_from_json(data: dict[str, Any]) -> ConstraintRecord:
    activated_at = None
    raw_activated = data.get("activated_at")
    if isinstance(raw_activated, str) and raw_activated:
        activated_at = dt.datetime.fromisoformat(raw_activated)
    return ConstraintRecord(
        constraint_id=str(data["constraint_id"]),
        family=Family(str(data["family"])),
        policy=Policy(str(data["policy"])),
        subject=Subject(
            SubjectKind(str(data["subject"]["kind"])),
            str(data["subject"].get("ref", "")),
        ),
        expression=_expression_from_json(dict(data["expression"])),
        source=_source_from_json(dict(data["source"])),
        created_by=str(data.get("created_by", "")),
        validated_against=str(data.get("validated_against", "")),
        active=bool(data.get("active", True)),
        activated_at=activated_at,
    )


def constraint_from_payload(
    payload: dict[str, Any], *, evidence: dict[str, Any] | None = None
) -> ConstraintRecord:
    family = Family(str(payload["family"]))
    source = _source_from_payload(family, payload, evidence=evidence)
    active = bool(payload.get("active", False))
    return ConstraintRecord(
        constraint_id=str(payload["constraint_id"]),
        family=family,
        policy=Policy(str(payload["policy"])),
        subject=Subject(
            SubjectKind(str(payload["subject_kind"])),
            str(payload.get("subject_ref", "")),
        ),
        expression=_expression_from_payload(payload),
        source=source,
        created_by=str(payload.get("actor_name") or "Direct API actor"),
        validated_against=str(payload.get("validated_against") or "coverset.api"),
        active=active,
        activated_at=dt.datetime.now(dt.UTC) if active else None,
    )


def _expression_to_json(expression: Expression) -> dict[str, Any]:
    if isinstance(expression, DateWindows):
        return {
            "type": "date_windows",
            "windows": [
                {"start": window.start.isoformat(), "end": window.end.isoformat()}
                for window in expression.windows
            ],
        }
    if isinstance(expression, BlackoutDates):
        return {
            "type": "blackout_dates",
            "dates": [day.isoformat() for day in expression.dates],
        }
    if isinstance(expression, DaylightBound):
        return {"type": "daylight_bound", "algorithm": expression.algorithm}
    if isinstance(expression, MinimumRest):
        return {"type": "minimum_rest", "hours": expression.hours}
    if isinstance(expression, MaximumDailyHours):
        return {"type": "maximum_daily_hours", "hours": expression.hours}
    if isinstance(expression, PinnedDay):
        return {"type": "pinned_day", "day": expression.day.isoformat()}
    raise TypeError(f"unsupported constraint expression: {type(expression).__name__}")


def _expression_from_json(data: dict[str, Any]) -> Expression:
    kind = str(data["type"])
    if kind == "date_windows":
        return DateWindows(
            tuple(
                AvailabilityWindow(_date(window["start"]), _date(window["end"]))
                for window in data.get("windows", ())
            )
        )
    if kind == "blackout_dates":
        return BlackoutDates(tuple(_date(day) for day in data.get("dates", ())))
    if kind == "daylight_bound":
        return DaylightBound(str(data.get("algorithm", "NOAA sunrise/sunset")))
    if kind == "minimum_rest":
        return MinimumRest(_float(data.get("hours"), "hours"))
    if kind == "maximum_daily_hours":
        return MaximumDailyHours(_float(data.get("hours"), "hours"))
    if kind == "pinned_day":
        return PinnedDay(_date(data["day"]))
    raise ValueError(f"unsupported expression type: {kind}")


def _expression_from_payload(payload: dict[str, Any]) -> Expression:
    data = dict(payload.get("expression", {}))
    if "type" not in data:
        data["type"] = payload.get("expression_type")
    if "day" not in data and payload.get("day") is not None:
        data["day"] = payload["day"]
    if "dates" not in data and payload.get("dates") is not None:
        data["dates"] = payload["dates"]
    if "hours" not in data and payload.get("hours") is not None:
        data["hours"] = payload["hours"]
    if "windows" not in data and payload.get("windows") is not None:
        data["windows"] = payload["windows"]
    return _expression_from_json(data)


def _source_to_json(source: Provenance) -> dict[str, Any]:
    if isinstance(source, GroundedSource):
        return {
            "type": "grounded",
            "evidence_id": source.evidence_id,
            "source_urls": list(source.source_urls),
            "grounded_value_id": source.grounded_value_id,
            "derived_from": source.derived_from.value,
        }
    if isinstance(source, AlgorithmSource):
        return {"type": "algorithm", "name": source.name, "version": source.version}
    if isinstance(source, HumanSource):
        return {
            "type": "human",
            "actor_name": source.author.name,
            "actor_role": source.author.role.value,
            "statement": source.statement,
            "from_fixture": source.from_fixture,
        }
    raise TypeError(f"unsupported constraint source: {type(source).__name__}")


def _source_from_json(data: dict[str, Any]) -> Provenance:
    kind = str(data["type"])
    if kind == "grounded":
        return GroundedSource(
            evidence_id=str(data["evidence_id"]),
            source_urls=tuple(str(url) for url in data.get("source_urls", ())),
            grounded_value_id=str(data.get("grounded_value_id", "")),
            source_mode=DerivedFrom(str(data.get("derived_from") or "excerpt")),
        )
    if kind == "algorithm":
        return AlgorithmSource(
            name=str(data.get("name", "NOAA sunrise/sunset")),
            version=str(data.get("version", "noaa-1")),
        )
    if kind == "human":
        return HumanSource(
            Actor(
                str(data.get("actor_name") or "Direct API actor"),
                Role(str(data.get("actor_role") or "first_ad")),
            ),
            str(data.get("statement") or "Production entered constraint"),
            from_fixture=bool(data.get("from_fixture", False)),
        )
    raise ValueError(f"unsupported source type: {kind}")


def _source_from_payload(
    family: Family, payload: dict[str, Any], *, evidence: dict[str, Any] | None = None
) -> Provenance:
    if family is Family.DAYLIGHT:
        return AlgorithmSource()
    evidence_id = payload.get("evidence_id")
    if evidence_id:
        source_urls = tuple(
            str(url)
            for url in (evidence or {}).get(
                "source_urls", payload.get("source_urls", ())
            )
        )
        derived_from = str(
            payload.get("derived_from")
            or ("full_content" if (evidence or {}).get("escalated") else "excerpt")
        )
        return GroundedSource(
            evidence_id=str(evidence_id),
            source_urls=source_urls,
            grounded_value_id=str(payload.get("grounded_value_id", "")),
            source_mode=DerivedFrom(derived_from),
        )
    return HumanSource(
        Actor(
            str(payload.get("actor_name") or "Direct API actor"),
            Role(str(payload.get("actor_role") or "first_ad")),
        ),
        str(payload.get("statement") or "Production entered constraint"),
        from_fixture=bool(payload.get("from_fixture", False)),
    )


def _float(value: object, field: str) -> float:
    if not isinstance(value, int | float | str) or isinstance(value, bool):
        raise ValueError(f"{field} must be numeric, got {value!r}")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be numeric, got {value!r}") from exc


def _date(value: object) -> dt.date:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise ValueError(f"expected ISO date, got {value!r}")
