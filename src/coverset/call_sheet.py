"""Call-sheet generation from a validated board.

A call sheet is an output artifact, not a scheduler. It reads the board the solver
already produced and packages one shoot day for the Second AD: scenes, locations,
cast calls, crew call/wrap, daylight windows, turnaround notes, permit notes, and
read-only recipients.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from .clock import elapsed
from .constraints import ConstraintRecord, Family
from .daylight import DaylightWindow, daylight_window
from .locations import LocationBook
from .people import Company, Roster

__all__ = [
    "CallSheetInputError",
    "build_call_sheet_payload",
    "render_call_sheet_text",
]


class CallSheetInputError(ValueError):
    """The board cannot produce the requested call sheet."""


@dataclass(frozen=True, slots=True)
class _DayContext:
    days: list[dict[str, Any]]
    index: int

    @property
    def current(self) -> dict[str, Any]:
        return self.days[self.index]

    @property
    def previous(self) -> dict[str, Any] | None:
        return self.days[self.index - 1] if self.index > 0 else None

    @property
    def next(self) -> dict[str, Any] | None:
        return self.days[self.index + 1] if self.index + 1 < len(self.days) else None


def build_call_sheet_payload(
    *,
    production_id: str,
    board_id: str,
    schedule_run_id: str,
    board_result: dict[str, Any],
    shoot_date: dt.date,
    generated_by: str,
    generated_by_role: str,
    roster: Roster,
    locations: LocationBook,
    active_constraints: tuple[ConstraintRecord, ...] = (),
    crew: Company | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe call-sheet payload for one solved board day."""
    day_context = _day_context(board_result, shoot_date)
    day = day_context.current
    strips = _ordered_strips(day)
    if not strips:
        raise CallSheetInputError(f"board {board_id} has no work on {shoot_date}")

    call_sheet_id = f"CS-{shoot_date:%Y%m%d}-{board_id[-6:]}"
    crew = crew or Company()
    cast_calls = _cast_calls(strips, roster)
    location_summaries = _locations_for_day(strips, locations)
    payload = {
        "call_sheet_version": call_sheet_id,
        "production_id": production_id,
        "board_id": board_id,
        "schedule_run_id": schedule_run_id,
        "schedule_version_id": str(board_result.get("schedule_version_id") or ""),
        "shoot_date": shoot_date.isoformat(),
        "generated_by": generated_by,
        "generated_by_role": generated_by_role,
        "crew_call": day.get("call_time"),
        "wrap_estimate": day.get("wrap_time"),
        "company_moves": _safe_int(day.get("company_moves"), field="company_moves"),
        "scenes": [_scene_row(strip) for strip in strips],
        "locations": location_summaries,
        "cast_calls": cast_calls,
        "daylight_windows": _daylight_windows(
            location_summaries, shoot_date, locations
        ),
        "turnaround_notes": _turnaround_notes(day_context, strips, roster, crew),
        "permit_notes": _permit_notes(active_constraints, location_summaries),
        "recipients": _read_only_recipients(cast_calls),
    }
    return payload


def _day_context(board_result: dict[str, Any], shoot_date: dt.date) -> _DayContext:
    days = sorted(
        (dict(day) for day in board_result.get("days", [])),
        key=lambda day: str(day.get("date") or ""),
    )
    for index, day in enumerate(days):
        if str(day.get("date")) == shoot_date.isoformat():
            return _DayContext(days, index)
    raise CallSheetInputError(f"board has no shoot day {shoot_date.isoformat()}")


def _ordered_strips(day: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (dict(strip) for strip in day.get("strips", [])),
        key=lambda strip: _safe_int(strip.get("sequence"), field="sequence"),
    )


def _scene_row(strip: dict[str, Any]) -> dict[str, Any]:
    location = dict(strip.get("location") or {})
    return {
        "work_id": str(strip.get("work_id") or ""),
        "scene_id": str(strip.get("scene_id") or ""),
        "kind": str(strip.get("kind") or ""),
        "day_night": str(strip.get("day_night") or ""),
        "location_id": str(strip.get("location_id") or location.get("id") or ""),
        "location_name": str(location.get("name") or strip.get("location_id") or ""),
        "planned_call_time": strip.get("planned_call_time"),
        "planned_wrap_time": strip.get("planned_wrap_time"),
        "duration_minutes": strip.get("duration_minutes"),
        "cast_ids": [str(cast_id) for cast_id in strip.get("cast_ids", [])],
        "cast": list(strip.get("cast", [])),
        "flags": dict(strip.get("flags") or {}),
        "requires_daylight": bool(strip.get("requires_daylight", False)),
    }


def _cast_calls(strips: list[dict[str, Any]], roster: Roster) -> list[dict[str, Any]]:
    by_cast: dict[str, dict[str, Any]] = {}
    for strip in strips:
        call = _parse_datetime(strip.get("planned_call_time"))
        wrap = _parse_datetime(strip.get("planned_wrap_time"))
        for cast_id in strip.get("cast_ids", []):
            cast_id = str(cast_id)
            member = roster[cast_id]
            row = by_cast.setdefault(
                cast_id,
                {
                    "cast_id": member.id,
                    "performer": member.name,
                    "character": member.character,
                    "is_minor": member.is_minor,
                    "minor_max_work_hours": member.max_work_hours_per_day,
                    "minimum_turnaround_hours": member.minimum_turnaround_hours,
                    "scene_ids": [],
                    "call_time": call,
                    "wrap_time": wrap,
                },
            )
            row["scene_ids"].append(str(strip.get("scene_id") or ""))
            row["call_time"] = min(row["call_time"], call)
            row["wrap_time"] = max(row["wrap_time"], wrap)
    out: list[dict[str, Any]] = []
    for row in sorted(
        by_cast.values(), key=lambda entry: (entry["call_time"], entry["character"])
    ):
        call = row.pop("call_time")
        wrap = row.pop("wrap_time")
        row["call_time"] = call.isoformat()
        row["wrap_time"] = wrap.isoformat()
        row["work_hours"] = round(elapsed(call, wrap).total_seconds() / 3600, 2)
        out.append(row)
    return out


def _locations_for_day(
    strips: list[dict[str, Any]], locations: LocationBook
) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for strip in strips:
        location_id = str(strip.get("location_id") or "")
        if not location_id or location_id in seen:
            continue
        location = locations[location_id]
        seen.add(location_id)
        out.append(
            {
                "location_id": location.id,
                "name": location.name,
                "place": location.place,
                "timezone": location.timezone or "",
            }
        )
    return out


def _daylight_windows(
    location_summaries: list[dict[str, str]],
    shoot_date: dt.date,
    locations: LocationBook,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for summary in location_summaries:
        location = locations[summary["location_id"]]
        if not location.is_locatable:
            out.append(
                _unavailable_daylight_summary(
                    location_id=location.id, name=location.name
                )
            )
            continue
        try:
            window = daylight_window(location, shoot_date)
        except ValueError:
            out.append(
                _unavailable_daylight_summary(
                    location_id=location.id, name=location.name
                )
            )
            continue
        out.append(_daylight_summary(window))
    return out


def _unavailable_daylight_summary(*, location_id: str, name: str) -> dict[str, Any]:
    return {
        "location_id": location_id,
        "location_name": name,
        "condition": "unavailable",
        "algorithm": "not_computed",
        "civil_dawn": None,
        "sunrise": None,
        "sunset": None,
        "civil_dusk": None,
        "golden_morning_end": None,
        "golden_evening_start": None,
    }


def _daylight_summary(window: DaylightWindow) -> dict[str, Any]:
    return {
        "location_id": window.location.id,
        "location_name": window.location.name,
        "condition": window.condition.value,
        "algorithm": window.algorithm,
        "civil_dawn": _optional_iso(window.civil_dawn),
        "sunrise": _optional_iso(window.sunrise),
        "sunset": _optional_iso(window.sunset),
        "civil_dusk": _optional_iso(window.civil_dusk),
        "golden_morning_end": _optional_iso(window.golden_morning_end),
        "golden_evening_start": _optional_iso(window.golden_evening_start),
    }


def _turnaround_notes(
    day_context: _DayContext,
    current_strips: list[dict[str, Any]],
    roster: Roster,
    crew: Company,
) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    current_call = _maybe_datetime(day_context.current.get("call_time"))
    current_wrap = _maybe_datetime(day_context.current.get("wrap_time"))
    if day_context.previous and current_call:
        previous_wrap = _maybe_datetime(day_context.previous.get("wrap_time"))
        if previous_wrap:
            notes.append(
                _turnaround_row(
                    subject="crew",
                    display="Crew",
                    previous_wrap=previous_wrap,
                    next_call=current_call,
                    minimum_hours=crew.minimum_turnaround_hours,
                )
            )
    if day_context.next and current_wrap:
        next_call = _maybe_datetime(day_context.next.get("call_time"))
        if next_call:
            notes.append(
                _turnaround_row(
                    subject="crew_next",
                    display="Crew to next shoot day",
                    previous_wrap=current_wrap,
                    next_call=next_call,
                    minimum_hours=crew.minimum_turnaround_hours,
                )
            )

    cast_ids = sorted(
        {
            str(cast_id)
            for strip in current_strips
            for cast_id in strip.get("cast_ids", [])
        }
    )
    for cast_id in cast_ids:
        member = roster[cast_id]
        previous_wrap = _latest_cast_wrap(
            day_context.days[: day_context.index], cast_id
        )
        if previous_wrap and current_call:
            notes.append(
                _turnaround_row(
                    subject=f"cast:{cast_id}",
                    display=f"{member.character} / {member.name}",
                    previous_wrap=previous_wrap,
                    next_call=current_call,
                    minimum_hours=member.minimum_turnaround_hours,
                )
            )
        next_call = _next_cast_call(day_context.days[day_context.index + 1 :], cast_id)
        if next_call and current_wrap:
            notes.append(
                _turnaround_row(
                    subject=f"cast_next:{cast_id}",
                    display=f"{member.character} / {member.name} to next call",
                    previous_wrap=current_wrap,
                    next_call=next_call,
                    minimum_hours=member.minimum_turnaround_hours,
                )
            )
    return notes


def _turnaround_row(
    *,
    subject: str,
    display: str,
    previous_wrap: dt.datetime,
    next_call: dt.datetime,
    minimum_hours: float,
) -> dict[str, Any]:
    rest_hours = round(elapsed(previous_wrap, next_call).total_seconds() / 3600, 2)
    return {
        "subject": subject,
        "display": display,
        "previous_wrap": previous_wrap.isoformat(),
        "next_call": next_call.isoformat(),
        "rest_hours": rest_hours,
        "minimum_hours": minimum_hours,
        "satisfied": rest_hours >= minimum_hours,
    }


def _latest_cast_wrap(days: list[dict[str, Any]], cast_id: str) -> dt.datetime | None:
    latest: dt.datetime | None = None
    for day in days:
        for strip in _ordered_strips(day):
            if cast_id not in {str(value) for value in strip.get("cast_ids", [])}:
                continue
            wrap = _parse_datetime(strip.get("planned_wrap_time"))
            latest = wrap if latest is None else max(latest, wrap)
    return latest


def _next_cast_call(days: list[dict[str, Any]], cast_id: str) -> dt.datetime | None:
    for day in days:
        calls = [
            _parse_datetime(strip.get("planned_call_time"))
            for strip in _ordered_strips(day)
            if cast_id in {str(value) for value in strip.get("cast_ids", [])}
        ]
        if calls:
            return min(calls)
    return None


def _permit_notes(
    active_constraints: tuple[ConstraintRecord, ...],
    location_summaries: list[dict[str, str]],
) -> list[dict[str, str]]:
    location_ids = {summary["location_id"] for summary in location_summaries}
    notes: list[dict[str, str]] = []
    for record in active_constraints:
        if not record.active or record.family is not Family.PERMIT:
            continue
        if record.subject.ref and record.subject.ref not in location_ids:
            continue
        notes.append(
            {
                "constraint_id": record.constraint_id,
                "subject": str(record.subject),
                "detail": str(record.expression),
                "source": record.explain(),
            }
        )
    return notes


def _read_only_recipients(cast_calls: list[dict[str, Any]]) -> list[dict[str, str]]:
    recipients = [
        {
            "recipient_type": "crew",
            "recipient_id": "crew",
            "display_name": "Crew distribution",
            "authority": "read_only",
        }
    ]
    recipients.extend(
        {
            "recipient_type": "cast",
            "recipient_id": str(row["cast_id"]),
            "display_name": f"{row['performer']} ({row['character']})",
            "authority": "read_only",
        }
        for row in cast_calls
    )
    return recipients


def render_call_sheet_text(payload: dict[str, Any]) -> str:
    """Render a compact, copyable text call sheet."""
    lines = [
        f"CALL SHEET {payload['call_sheet_version']}",
        f"Shoot date: {payload['shoot_date']}",
        f"Schedule version: {payload['schedule_version_id']}",
        f"Crew call: {_time_label(payload.get('crew_call'))}",
        f"Wrap estimate: {_time_label(payload.get('wrap_estimate'))}",
        f"Company moves: {payload.get('company_moves', 0)}",
        "",
        "Scenes",
    ]
    for scene in payload.get("scenes", []):
        flags = ", ".join(k for k, v in scene.get("flags", {}).items() if v) or "none"
        cast = ", ".join(
            member.get("character", "") for member in scene.get("cast", [])
        )
        lines.append(
            f"- {_time_label(scene.get('planned_call_time'))}-{_time_label(scene.get('planned_wrap_time'))} "
            f"{scene['scene_id']} at {scene['location_name']} ({scene['day_night']}); "
            f"cast: {cast or 'none'}; flags: {flags}"
        )

    lines.extend(["", "Cast calls"])
    for row in payload.get("cast_calls", []):
        minor = (
            f"; minor max {row['minor_max_work_hours']:g}h"
            if row.get("is_minor")
            else ""
        )
        lines.append(
            f"- {row['character']} / {row['performer']}: {_time_label(row['call_time'])} "
            f"to {_time_label(row['wrap_time'])}{minor}"
        )

    lines.extend(["", "Daylight"])
    for window in payload.get("daylight_windows", []):
        lines.append(
            f"- {window['location_name']}: sunrise {_time_label(window.get('sunrise'))}, "
            f"sunset {_time_label(window.get('sunset'))} ({window['algorithm']})"
        )

    lines.extend(["", "Turnaround"])
    for note in payload.get("turnaround_notes", []):
        mark = "ok" if note.get("satisfied") else "CHECK"
        lines.append(
            f"- {note['display']}: {note['rest_hours']:g}h rest "
            f"(minimum {note['minimum_hours']:g}h) {mark}"
        )
    if not payload.get("turnaround_notes"):
        lines.append("- No adjacent-day turnaround notes for this board day.")

    lines.extend(["", "Permit notes"])
    for note in payload.get("permit_notes", []):
        lines.append(f"- {note['constraint_id']}: {note['detail']} — {note['source']}")
    if not payload.get("permit_notes"):
        lines.append("- No active permit constraints for this day.")

    lines.extend(["", "Recipients"])
    for recipient in payload.get("recipients", []):
        lines.append(f"- {recipient['display_name']} ({recipient['authority']})")
    return "\n".join(lines) + "\n"


def _optional_iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _safe_int(value: Any, *, field: str) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError) as exc:
        raise CallSheetInputError(f"{field} must be an integer, got {value!r}") from exc


def _parse_datetime(value: Any) -> dt.datetime:
    parsed = _maybe_datetime(value)
    if parsed is None:
        raise CallSheetInputError(f"expected timezone-aware datetime, got {value!r}")
    if parsed.tzinfo is None:
        raise CallSheetInputError(f"call sheet datetime is naive: {value!r}")
    return parsed


def _maybe_datetime(value: Any) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, str):
        return dt.datetime.fromisoformat(value)
    raise CallSheetInputError(f"expected datetime string, got {type(value).__name__}")


def _time_label(value: Any) -> str:
    when = _maybe_datetime(value)
    if when is None:
        return "TBD"
    return when.strftime("%H:%M %Z")
