"""Production-readable diffs between two board snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ScheduleDiff", "build_schedule_diff", "render_schedule_diff_text"]


@dataclass(frozen=True, slots=True)
class ScheduleDiff:
    """Delta between two solved boards, expressed in production terms."""

    base_board_id: str
    revised_board_id: str
    added_days: tuple[str, ...] = ()
    removed_days: tuple[str, ...] = ()
    moved_scenes: tuple[dict[str, str], ...] = ()
    changed_call_times: tuple[dict[str, str], ...] = ()
    added_pickups: tuple[str, ...] = ()
    removed_work: tuple[str, ...] = ()
    company_move_delta: int = 0
    cast_holding_delta: int = 0
    overtime_delta_hours: float = 0.0
    turnaround_delta_hours: float = 0.0
    required_approvals: tuple[str, ...] = ()
    cost_delta: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, Any]:
        return {
            "base_board_id": self.base_board_id,
            "revised_board_id": self.revised_board_id,
            "added_days": list(self.added_days),
            "removed_days": list(self.removed_days),
            "moved_scenes": list(self.moved_scenes),
            "changed_call_times": list(self.changed_call_times),
            "added_pickups": list(self.added_pickups),
            "removed_work": list(self.removed_work),
            "company_move_delta": self.company_move_delta,
            "cast_holding_delta": self.cast_holding_delta,
            "overtime_delta_hours": self.overtime_delta_hours,
            "turnaround_delta_hours": self.turnaround_delta_hours,
            "required_approvals": list(self.required_approvals),
            "cost_delta": self.cost_delta,
            "notes": list(self.notes),
        }


def build_schedule_diff(
    *,
    base_board_id: str,
    revised_board_id: str,
    base: dict[str, Any],
    revised: dict[str, Any],
) -> ScheduleDiff:
    """Compare two serialized board results from ``board_to_json``."""
    base_days = _day_ids(base)
    revised_days = _day_ids(revised)
    base_strips = _strips_by_work(base)
    revised_strips = _strips_by_work(revised)

    moved: list[dict[str, str]] = []
    changed_calls: list[dict[str, str]] = []
    for work_id, revised_strip in revised_strips.items():
        base_strip = base_strips.get(work_id)
        if base_strip is None:
            continue
        base_day = str(base_strip.get("shoot_day") or "")
        revised_day = str(revised_strip.get("shoot_day") or "")
        base_sequence = str(base_strip.get("sequence") or 0)
        revised_sequence = str(revised_strip.get("sequence") or 0)
        if base_day != revised_day or base_sequence != revised_sequence:
            moved.append(
                {
                    "work_id": work_id,
                    "scene_id": str(revised_strip.get("scene_id") or ""),
                    "from_day": base_day,
                    "to_day": revised_day,
                    "from_sequence": base_sequence,
                    "to_sequence": revised_sequence,
                }
            )
        call_fields = (
            "planned_call_time",
            "planned_wrap_time",
        )
        if any(base_strip.get(field_name) != revised_strip.get(field_name) for field_name in call_fields):
            changed_calls.append(
                {
                    "work_id": work_id,
                    "scene_id": str(revised_strip.get("scene_id") or ""),
                    "from_call": str(base_strip.get("planned_call_time") or ""),
                    "to_call": str(revised_strip.get("planned_call_time") or ""),
                    "from_wrap": str(base_strip.get("planned_wrap_time") or ""),
                    "to_wrap": str(revised_strip.get("planned_wrap_time") or ""),
                }
            )

    added_work = sorted(set(revised_strips) - set(base_strips))
    added_pickups = tuple(
        work_id
        for work_id in added_work
        if str(revised_strips[work_id].get("kind") or "") == "pickup"
    )
    company_move_delta = _objective_int(revised, "company_moves") - _objective_int(
        base, "company_moves"
    )
    cast_holding_delta = _objective_int(revised, "holding_days") - _objective_int(
        base, "holding_days"
    )
    overtime_delta = _objective_float(revised, "overtime_hours") - _objective_float(
        base, "overtime_hours"
    )
    cost_delta = _production_cost_delta(
        added_days=len(revised_days - base_days),
        company_move_delta=company_move_delta,
        cast_holding_delta=cast_holding_delta,
        overtime_delta_hours=overtime_delta,
        added_pickups=len(added_pickups),
    )
    approvals: list[str] = []
    if added_pickups:
        approvals.append("director_or_first_ad_pickup_authorization")
    if cost_delta > 0 or revised_days - base_days:
        approvals.append("upm_or_line_producer_cost_approval")

    return ScheduleDiff(
        base_board_id=base_board_id,
        revised_board_id=revised_board_id,
        added_days=tuple(sorted(revised_days - base_days)),
        removed_days=tuple(sorted(base_days - revised_days)),
        moved_scenes=tuple(moved),
        changed_call_times=tuple(changed_calls),
        added_pickups=added_pickups,
        removed_work=tuple(sorted(set(base_strips) - set(revised_strips))),
        company_move_delta=company_move_delta,
        cast_holding_delta=cast_holding_delta,
        overtime_delta_hours=round(overtime_delta, 2),
        turnaround_delta_hours=0.0,
        required_approvals=tuple(dict.fromkeys(approvals)),
        cost_delta=cost_delta,
        notes=_notes(moved, changed_calls, added_pickups),
    )


def render_schedule_diff_text(diff: ScheduleDiff) -> str:
    lines = [f"SCHEDULE DIFF {diff.base_board_id} -> {diff.revised_board_id}"]
    lines.append(f"Added days: {', '.join(diff.added_days) or 'none'}")
    lines.append(f"Removed days: {', '.join(diff.removed_days) or 'none'}")
    lines.append(f"Added pickups: {', '.join(diff.added_pickups) or 'none'}")
    lines.append(f"Company move delta: {diff.company_move_delta:+d}")
    lines.append(f"Cast holding delta: {diff.cast_holding_delta:+d}")
    lines.append(f"Overtime delta: {diff.overtime_delta_hours:+g}h")
    lines.append(f"Required approvals: {', '.join(diff.required_approvals) or 'none'}")
    if diff.moved_scenes:
        lines.append("Moved/resequenced scenes:")
        for row in diff.moved_scenes:
            lines.append(
                f"- {row['work_id']}: {row['from_day']}#{row['from_sequence']} "
                f"-> {row['to_day']}#{row['to_sequence']}"
            )
    if diff.changed_call_times:
        lines.append("Changed call/wrap times:")
        for row in diff.changed_call_times:
            lines.append(f"- {row['work_id']}: {row['from_call']} -> {row['to_call']}")
    return "\n".join(lines) + "\n"


def _day_ids(board: dict[str, Any]) -> set[str]:
    return {str(day.get("date") or "") for day in board.get("days", []) if day.get("date")}


def _strips_by_work(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(strip.get("work_id")): dict(strip)
        for strip in board.get("strips", [])
        if strip.get("work_id")
    }


def _objective(board: dict[str, Any]) -> dict[str, Any]:
    value = board.get("objective_breakdown")
    return dict(value) if isinstance(value, dict) else {}


def _objective_int(board: dict[str, Any], key: str) -> int:
    try:
        return int(_objective(board).get(key) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"objective {key} must be numeric") from exc


def _objective_float(board: dict[str, Any], key: str) -> float:
    try:
        return float(_objective(board).get(key) or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"objective {key} must be numeric") from exc


def _production_cost_delta(
    *,
    added_days: int,
    company_move_delta: int,
    cast_holding_delta: int,
    overtime_delta_hours: float,
    added_pickups: int,
) -> float:
    """A transparent planning estimate, not an accounting ledger."""
    return round(
        max(0, added_days) * 10_000
        + max(0, company_move_delta) * 1_500
        + max(0, cast_holding_delta) * 500
        + max(0.0, overtime_delta_hours) * 750
        + max(0, added_pickups) * 1_000,
        2,
    )


def _notes(
    moved: list[dict[str, str]],
    changed_calls: list[dict[str, str]],
    added_pickups: tuple[str, ...],
) -> tuple[str, ...]:
    notes: list[str] = []
    if moved:
        notes.append(f"{len(moved)} work item(s) moved or resequenced")
    if changed_calls:
        notes.append(f"{len(changed_calls)} call/wrap window(s) changed")
    if added_pickups:
        notes.append(f"{len(added_pickups)} pickup task(s) added")
    return tuple(notes)
