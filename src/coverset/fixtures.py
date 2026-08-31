"""Structured fixture import.

MVP-0 builds a board from pre-parsed scenes rather than from a screenplay, which
lets the scheduling spine be proved without Gemini in the path. That only helps if
the fixtures are trustworthy, so import validates rather than assumes.

Every problem in a file is reported together. An AD correcting a breakdown wants the
whole list, not one error per run — the same reason `Roster.resolve` names every
unknown cast id at once.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from enum import StrEnum
from typing import Any, TypeVar

from .actors import Actor, Role
from .constraints import (
    AlgorithmSource,
    BlackoutDates,
    ConstraintError,
    ConstraintRecord,
    ConstraintSet,
    DateWindows,
    DaylightBound,
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
from .daylight import ALGORITHM
from .locations import LocationBook
from .people import AvailabilityWindow, Roster
from .scenes import CandidateStatus, IntExt, SceneRecord
from .work import DayNight, WorkFlags

EnumT = TypeVar("EnumT", bound=StrEnum)

__all__ = ["FixtureError", "load_constraints", "load_scenes"]

REQUIRED = ("scene_id", "scene_number", "slugline", "int_ext", "day_night",
            "location_ref", "page_eighths")


class FixtureError(Exception):
    """A fixture file could not be trusted. Carries every problem found, not the first."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        body = "\n  ".join(problems)
        super().__init__(f"{len(problems)} problem(s) in scene fixtures:\n  {body}")


def _enum(value: Any, kind: type[EnumT], field: str, where: str, problems: list[str]) -> EnumT | None:
    try:
        return kind(value)
    except ValueError:
        problems.append(
            f"{where}: {field} {value!r} is not one of "
            f"{', '.join(m.value for m in kind)}"
        )
        return None


def load_scenes(
    source: pathlib.Path | str | list[dict[str, Any]],
    *,
    roster: Roster,
    locations: LocationBook,
) -> tuple[SceneRecord, ...]:
    """Load and validate scene records against the production's cast and locations.

    Cross-references are checked here rather than on `SceneRecord` itself, because a
    scene has no way to know the roster. A record that names a performer or a place
    that does not exist is the silent-scheduling failure this import exists to stop.

    Raises:
        FixtureError: listing every problem found across the whole file.
    """
    if isinstance(source, pathlib.Path):
        source = source.read_text()
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except json.JSONDecodeError as exc:
            raise FixtureError([f"not valid JSON: {exc}"]) from exc
    if not isinstance(source, list):
        raise FixtureError([f"expected a list of scenes, got {type(source).__name__}"])

    known_cast = {m.id for m in roster}
    known_places = {loc.id for loc in locations}
    problems: list[str] = []
    records: list[SceneRecord] = []
    seen: dict[str, int] = {}

    for i, raw in enumerate(source):
        where = f"scene[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{where}: expected an object, got {type(raw).__name__}")
            continue
        if sid := raw.get("scene_id"):
            where = f"scene {sid!r}"
            if sid in seen:
                problems.append(f"{where}: duplicate scene_id, first seen at index {seen[sid]}")
                continue
            seen[sid] = i

        if missing := [f for f in REQUIRED if raw.get(f) in (None, "")]:
            problems.append(f"{where}: missing required field(s) {', '.join(missing)}")
            continue

        # Independent checks do not cascade: a bad enum must not hide a bad page
        # count in the same scene, or fixing the file becomes one error per run.
        found: list[str] = []
        int_ext = _enum(raw["int_ext"], IntExt, "int_ext", where, found)
        day_night = _enum(raw["day_night"], DayNight, "day_night", where, found)
        status = _enum(raw.get("status", "candidate"), CandidateStatus, "status", where, found)

        eighths = raw["page_eighths"]
        if not isinstance(eighths, int) or isinstance(eighths, bool) or eighths <= 0:
            found.append(f"{where}: page_eighths must be a positive integer, got {eighths!r}")

        cast_ids = tuple(raw.get("cast_ids", ()))
        if unknown := sorted(set(cast_ids) - known_cast):
            found.append(f"{where}: cast not on the roster: {', '.join(unknown)}")
        if raw["location_ref"] not in known_places:
            found.append(
                f"{where}: location {raw['location_ref']!r} is not on the production's "
                f"locations"
            )

        if found:
            problems.extend(found)
            continue
        assert int_ext is not None
        assert day_night is not None
        assert status is not None

        raw_flags = raw.get("flags") or {}
        try:
            records.append(SceneRecord(
                scene_id=raw["scene_id"],
                scene_number=str(raw["scene_number"]),
                slugline=raw["slugline"],
                int_ext=int_ext,
                day_night=day_night,
                location_ref=raw["location_ref"],
                page_eighths=eighths,
                cast_ids=cast_ids,
                flags=WorkFlags(
                    stunts=bool(raw_flags.get("stunts")),
                    minors=bool(raw_flags.get("minors")),
                    vfx=bool(raw_flags.get("vfx")),
                ),
                source_page_range=raw.get("source_page_range", ""),
                confidence=raw.get("confidence"),
                status=status,
            ))
        except ValueError as exc:
            problems.append(f"{where}: {exc}")

    if problems:
        raise FixtureError(problems)
    return tuple(records)


CONSTRAINT_REQUIRED = ("constraint_id", "family", "policy", "subject", "expression", "source")


def _date(value: Any, field: str, where: str, problems: list[str]) -> dt.date | None:
    if not isinstance(value, str):
        problems.append(f"{where}: {field} must be an ISO date string, got {value!r}")
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        problems.append(f"{where}: {field} {value!r} is not an ISO date (YYYY-MM-DD)")
        return None


def _hours(value: Any, field: str, where: str, problems: list[str]) -> float | None:
    # bool is an int in Python, and `"hours": true` reaching MinimumRest as 1.0 is
    # exactly the well-formed-and-wrong shape this project keeps meeting.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{where}: {field} must be a number of hours, got {value!r}")
        return None
    try:
        return float(value)
    except (OverflowError, TypeError, ValueError):
        problems.append(f"{where}: {field} must be a finite number of hours, got {value!r}")
        return None


def _text(raw: dict[str, Any], field: str, where: str, problems: list[str]) -> str | None:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where}: {field} must be a non-empty string, got {value!r}")
        return None
    return value


def _expression(raw: Any, where: str, problems: list[str]) -> Expression | None:
    """Build the typed expression, or record why it could not be built.

    Every branch names its `type` explicitly. There is no default and no fallback:
    an unrecognised type is a problem rather than a constraint that quietly governs
    nothing, because a bound that fails to apply is indistinguishable from a bound
    nobody wrote until a board violates it.
    """
    if not isinstance(raw, dict):
        problems.append(f"{where}: expression must be an object, got {type(raw).__name__}")
        return None

    kind = raw.get("type")
    before = len(problems)
    built: Expression | None = None

    match kind:
        case "date_windows":
            windows = raw.get("windows")
            if not isinstance(windows, list) or not windows:
                problems.append(
                    f"{where}: date_windows needs a non-empty 'windows' list; an empty "
                    f"one would permit every day"
                )
            else:
                spans: list[AvailabilityWindow] = []
                for j, w in enumerate(windows):
                    if not isinstance(w, dict):
                        problems.append(
                            f"{where}: windows[{j}] must be an object with 'start' and 'end'"
                        )
                        continue
                    start = _date(w.get("start"), f"windows[{j}].start", where, problems)
                    end = _date(w.get("end"), f"windows[{j}].end", where, problems)
                    if start is not None and end is not None:
                        try:
                            spans.append(AvailabilityWindow(start, end))
                        except ValueError as exc:
                            problems.append(f"{where}: windows[{j}]: {exc}")
                if len(problems) == before:
                    built = DateWindows(tuple(spans))

        case "blackout":
            dates = raw.get("dates")
            if not isinstance(dates, list) or not dates:
                problems.append(f"{where}: blackout needs a non-empty 'dates' list")
            else:
                parsed = [_date(d, f"dates[{j}]", where, problems) for j, d in enumerate(dates)]
                if len(problems) == before:
                    built = BlackoutDates(tuple(d for d in parsed if d is not None))

        case "daylight":
            # No times here by design: the window is recomputed at solve time from the
            # date and the place (DAY-008). A sunset in a fixture is a sunset for
            # whichever date someone wrote it down on.
            built = DaylightBound(algorithm=raw.get("algorithm", ALGORITHM))

        case "minimum_rest" | "maximum_daily_hours":
            hours = _hours(raw.get("hours"), "hours", where, problems)
            if hours is not None:
                built = (MinimumRest(hours) if kind == "minimum_rest"
                         else MaximumDailyHours(hours))

        case "pinned_day":
            day = _date(raw.get("day"), "day", where, problems)
            if day is not None:
                built = PinnedDay(day)

        case _:
            problems.append(
                f"{where}: expression type {kind!r} is not one of date_windows, "
                f"blackout, daylight, minimum_rest, maximum_daily_hours, pinned_day"
            )

    return built


def _source(raw: Any, where: str, problems: list[str]) -> Provenance | None:
    """Build the provenance, or record why it could not be built."""
    if not isinstance(raw, dict):
        problems.append(f"{where}: source must be an object, got {type(raw).__name__}")
        return None

    kind = raw.get("type")
    match kind:
        case "human":
            author = raw.get("author")
            if not isinstance(author, dict):
                problems.append(
                    f"{where}: a human source needs an 'author' object naming who said it"
                )
                return None
            name = _text(author, "name", f"{where} author", problems)
            role = _enum(author.get("role"), Role, "role", f"{where} author", problems)
            statement = _text(raw, "statement", where, problems)
            if name is None or role is None or statement is None:
                return None
            # from_fixture marks the derivation FIXTURE rather than HUMAN_INPUT: this
            # was read out of a file, not said to anyone, and the audit trail should
            # not claim otherwise.
            return HumanSource(Actor(name, role), statement, from_fixture=True)

        case "algorithm":
            return AlgorithmSource(
                name=raw.get("name", ALGORITHM), version=raw.get("version", "noaa-1")
            )

        case "grounded":
            evidence_id = _text(raw, "evidence_id", where, problems)
            urls = raw.get("source_urls")
            if not isinstance(urls, list) or not urls:
                problems.append(
                    f"{where}: a grounded source needs at least one entry in "
                    f"'source_urls'; without one the value is a guess with a citation field"
                )
                return None
            if evidence_id is None:
                return None
            return GroundedSource(
                evidence_id=evidence_id,
                source_urls=tuple(str(u) for u in urls),
                grounded_value_id=raw.get("grounded_value_id", ""),
            )

        case _:
            problems.append(
                f"{where}: source type {kind!r} is not one of human, algorithm, grounded"
            )
            return None


def load_constraints(
    source: pathlib.Path | str | list[dict[str, Any]],
) -> ConstraintSet:
    """Load and validate typed constraint fixtures into a `ConstraintSet` (`CON-004`).

    The counterpart to `load_scenes`, and the only file-shaped way a fixture bound
    reaches the solver. Scenes had one and constraints did not, which made "structured
    fixtures" half true: the work was data and the bounds on it were Python.

    Reference checking is deliberately *not* done here. A constraint naming a
    performer who is not on the roster is caught by `ConstraintSet.resolve`, which
    `ScheduleProblem` calls with the roster, the locations, the work ids and the
    calendar it actually has (`CON-005`). Repeating the check here would create a
    second definition of the same rule, and two definitions of one rule is how they
    drift apart.

    What is checked here is shape: that every field is present, that enums come from
    the declared vocabularies, that dates are dates, and that the record satisfies
    `ConstraintRecord`'s own invariants -- including the one that refuses a daylight
    constraint carrying URL provenance (`CON-008`).

    Every problem in the file is reported together, for the same reason `load_scenes`
    does it: someone repairing a constraint file wants the list, not one error per run.

    Raises:
        FixtureError: listing every problem found across the whole file.
    """
    if isinstance(source, pathlib.Path):
        source = source.read_text()
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except json.JSONDecodeError as exc:
            raise FixtureError([f"not valid JSON: {exc}"]) from exc
    if not isinstance(source, list):
        raise FixtureError(
            [f"expected a list of constraints, got {type(source).__name__}"]
        )

    problems: list[str] = []
    records: list[ConstraintRecord] = []
    seen: dict[str, int] = {}

    for i, raw in enumerate(source):
        where = f"constraint[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{where}: expected an object, got {type(raw).__name__}")
            continue
        if cid := raw.get("constraint_id"):
            where = f"constraint {cid!r}"
            if cid in seen:
                problems.append(
                    f"{where}: duplicate constraint_id, first seen at index {seen[cid]}"
                )
                continue
            seen[cid] = i

        if missing := [f for f in CONSTRAINT_REQUIRED if raw.get(f) in (None, "")]:
            problems.append(f"{where}: missing required field(s) {', '.join(missing)}")
            continue

        # Independent checks do not cascade: a bad policy must not hide a bad date in
        # the same record, or repairing the file becomes one error per run.
        found: list[str] = []
        family = _enum(raw["family"], Family, "family", where, found)
        policy = _enum(raw["policy"], Policy, "policy", where, found)

        subject = None
        raw_subject = raw["subject"]
        if not isinstance(raw_subject, dict):
            found.append(
                f"{where}: subject must be an object with 'kind' and (unless "
                f"schedule-wide) 'ref', got {type(raw_subject).__name__}"
            )
        elif (kind := _enum(raw_subject.get("kind"), SubjectKind, "subject.kind",
                            where, found)) is not None:
            try:
                subject = Subject(kind, raw_subject.get("ref", ""))
            except ConstraintError as exc:
                found.append(f"{where}: {exc}")

        expression = _expression(raw["expression"], where, found)
        provenance = _source(raw["source"], where, found)

        if found:
            problems.extend(found)
            continue
        assert family is not None and policy is not None  # guarded by `found`
        assert subject is not None and expression is not None and provenance is not None

        try:
            records.append(ConstraintRecord(
                constraint_id=raw["constraint_id"],
                family=family,
                policy=policy,
                subject=subject,
                expression=expression,
                source=provenance,
                created_by=raw.get("created_by", ""),
                validated_against=raw.get("validated_against", ""),
                active=raw.get("active", True),
            ))
        except ConstraintError as exc:
            problems.append(f"{where}: {exc}")

    if problems:
        raise FixtureError(problems)

    try:
        return ConstraintSet(tuple(records))
    except ConstraintError as exc:  # duplicate ids are caught above; this is belt-and-braces
        raise FixtureError([str(exc)]) from exc
