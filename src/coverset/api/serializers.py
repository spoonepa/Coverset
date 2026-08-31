"""Conversion helpers between persisted JSON and Coverset domain objects."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from typing import Any

from coverset.board import Assignment, Board
from coverset.locations import Location, LocationBook
from coverset.people import CastMember, Company, Roster
from coverset.scenes import CandidateStatus, IntExt, SceneRecord
from coverset.solver import ProductionCalendar
from coverset.work import DayNight, WorkFlags

from .models import (  # type: ignore[import-not-found]
    CastMemberModel,
    LocationAliasModel,
    LocationModel,
)


def flags_to_json(flags: WorkFlags) -> dict[str, bool]:
    return {"stunts": flags.stunts, "minors": flags.minors, "vfx": flags.vfx}


def flags_from_json(data: dict[str, Any] | None) -> WorkFlags:
    data = data or {}
    return WorkFlags(
        stunts=bool(data.get("stunts", False)),
        minors=bool(data.get("minors", False)),
        vfx=bool(data.get("vfx", False)),
    )


def scene_to_json(scene: SceneRecord) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "scene_number": scene.scene_number,
        "slugline": scene.slugline,
        "int_ext": scene.int_ext.value,
        "day_night": scene.day_night.value,
        "location_ref": scene.location_ref,
        "page_eighths": scene.page_eighths,
        "cast_ids": list(scene.cast_ids),
        "flags": flags_to_json(scene.flags),
        "source_page_range": scene.source_page_range,
        "confidence": scene.confidence,
        "status": scene.status.value,
        "number_synthesized": scene.number_synthesized,
    }


def _required_int(data: dict[str, Any], key: str) -> int:
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"scene JSON field {key!r} must be an integer") from exc


def scene_from_json(data: dict[str, Any]) -> SceneRecord:
    return SceneRecord(
        scene_id=str(data["scene_id"]),
        scene_number=str(data["scene_number"]),
        slugline=str(data["slugline"]),
        int_ext=IntExt(str(data["int_ext"])),
        day_night=DayNight(str(data["day_night"])),
        location_ref=str(data["location_ref"]),
        page_eighths=_required_int(data, "page_eighths"),
        cast_ids=tuple(str(c) for c in data.get("cast_ids", ())),
        flags=flags_from_json(data.get("flags")),
        source_page_range=str(data.get("source_page_range", "")),
        confidence=data.get("confidence"),
        status=CandidateStatus(str(data.get("status", CandidateStatus.CANDIDATE.value))),
        number_synthesized=bool(data.get("number_synthesized", False)),
    )


def roster_from_models(rows: list[CastMemberModel]) -> Roster:
    return Roster(tuple(
        CastMember(row.cast_id, row.performer, row.character, is_minor=row.is_minor)
        for row in rows
    ))


def locations_from_models(rows: list[LocationModel]) -> LocationBook:
    return LocationBook(tuple(
        Location(
            row.name,
            row.city,
            row.state,
            id=row.location_id,
            latitude=row.latitude,
            longitude=row.longitude,
            timezone=(
                row.timezone
                if row.latitude is not None and row.longitude is not None
                else None
            ),
        )
        for row in rows
    ))


def aliases_from_models(rows: list[LocationAliasModel]) -> dict[str, str]:
    return {row.alias: row.location_id for row in rows}


def default_calendar(start: dt.date | None = None, *, days: int = 5) -> ProductionCalendar:
    start = start or dt.date(2026, 9, 14)
    return ProductionCalendar(tuple(start + dt.timedelta(days=i) for i in range(days)))


def company_from_settings() -> Company:
    return Company()


def assignment_to_json(assignment: Assignment) -> dict[str, Any]:
    return {
        "work_id": assignment.work_id,
        "shoot_day": assignment.shoot_day.isoformat(),
        "sequence": assignment.sequence,
        "location_id": assignment.location_id,
        "planned_call_time": assignment.planned_call_time.isoformat(),
        "planned_wrap_time": assignment.planned_wrap_time.isoformat(),
    }


def board_to_json(board: Board) -> dict[str, Any]:
    return {
        "schedule_version_id": board.schedule_version_id,
        "solver_status": str(board.solver_status),
        "solver_objective_value": board.solver_objective_value,
        "solver_best_bound": board.solver_best_bound,
        "optimality_gap": board.optimality_gap,
        "objective_weights": board.objective_weights,
        "solver_parameters": board.solver_parameters,
        "constraint_snapshot_hash": board.constraint_snapshot_hash,
        "shoot_day_count": board.shoot_day_count,
        "objective_breakdown": asdict(board.objective_breakdown),
        "validation_summary": board.validation_result.summary(),
        "assignments": [assignment_to_json(assignment) for assignment in board.assignments],
        "days": [
            {
                "date": day.date.isoformat(),
                "call_time": day.call_time.isoformat() if day.call_time else None,
                "wrap_time": day.wrap_time.isoformat() if day.wrap_time else None,
                "company_moves": day.company_moves,
                "assignments": [assignment_to_json(assignment) for assignment in day.assignments],
            }
            for day in board.days
        ],
    }
