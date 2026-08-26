"""Structured fixture import.

MVP-0 builds a board from pre-parsed scenes rather than from a screenplay, which
lets the scheduling spine be proved without Gemini in the path. That only helps if
the fixtures are trustworthy, so import validates rather than assumes.

Every problem in a file is reported together. An AD correcting a breakdown wants the
whole list, not one error per run — the same reason `Roster.resolve` names every
unknown cast id at once.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .locations import LocationBook
from .people import Roster
from .scenes import CandidateStatus, IntExt, SceneRecord
from .work import DayNight, WorkFlags

__all__ = ["FixtureError", "load_scenes"]

REQUIRED = ("scene_id", "scene_number", "slugline", "int_ext", "day_night",
            "location_ref", "page_eighths")


class FixtureError(Exception):
    """A fixture file could not be trusted. Carries every problem found, not the first."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        body = "\n  ".join(problems)
        super().__init__(f"{len(problems)} problem(s) in scene fixtures:\n  {body}")


def _enum(value: Any, kind: type, field: str, where: str, problems: list[str]):
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
