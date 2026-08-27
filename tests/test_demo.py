"""The UC-00 demo path: fixtures on disk to a validated stripboard.

Everything here was already unit-tested in pieces. These tests exist because the
pieces had never been run together, and a chain of individually-correct links is not
evidence that the chain holds -- MVP-0 read 47/47 while no use case was deliverable.

So the assertions are deliberately about the *whole* path and about the fixture
constraints actually reaching the finished board. A demo that produced a board while
quietly failing to apply the permit window would look exactly like a demo that worked.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from coverset.constraints import UnresolvedConstraints
from coverset.demo import LOCATIONS, ROSTER, build_problem, main, render
from coverset.fixtures import FixtureError, load_constraints
from coverset.solver import solve
from coverset.work import DayNight

SARAH_WINDOW = (dt.date(2026, 9, 14), dt.date(2026, 9, 16))
CHURCH_WINDOW = (dt.date(2026, 9, 16), dt.date(2026, 9, 17))


@pytest.fixture(scope="module")
def solved():
    """The demo problem and its board. Solved once; every assertion reads the same one."""
    problem = build_problem()
    return problem, solve(problem)


# -- the path runs -------------------------------------------------------------


@pytest.mark.req("SOL-001", "SOL-002", "SOL-007")
def test_the_fixture_production_solves_to_an_independently_validated_board(solved):
    problem, result = solved
    board = result.board  # raises rather than returning a plausible partial answer

    assert str(board.solver_status) in ("optimal", "feasible")
    assert board.validation_result.passed
    # A report that checked nothing would also "pass". The ids it was obliged to check
    # are the difference between validation and the appearance of validation.
    assert set(board.validation_result.expected_ids) == {
        r.constraint_id for r in problem.constraints.binding
    }


@pytest.mark.req("SCN-002", "SCN-003", "CST-009")
def test_every_fixture_scene_becomes_exactly_one_scheduled_strip(solved):
    problem, result = solved
    scene_ids = {w.scene_id for w in problem.work_items}
    assert len(scene_ids) == 8
    scheduled = {
        next(w for w in problem.work_items if w.work_id == a.work_id).scene_id
        for a in result.board.assignments
    }
    # Not a subset: work that silently fails to be scheduled is the failure mode.
    assert scheduled == scene_ids


@pytest.mark.req("SOL-008", "AUD-005")
def test_the_board_records_what_it_was_solved_and_validated_against(solved):
    problem, result = solved
    board = result.board
    assert board.constraint_snapshot_hash == problem.constraint_snapshot_hash
    assert board.objective_weights == str(problem.weights)
    # Seed, workers and model version: reproducing a board needs the parameters, not
    # just the problem.
    assert "seed=" in board.solver_parameters and "model=" in board.solver_parameters


@pytest.mark.req("SOL-010")
def test_the_same_seed_gives_the_same_board(solved):
    problem, _ = solved
    first = solve(problem, seed=7).board
    second = solve(problem, seed=7).board
    assert [(a.work_id, a.shoot_day, a.sequence) for a in first.assignments] \
        == [(a.work_id, a.shoot_day, a.sequence) for a in second.assignments]


# -- the fixture constraints actually bind --------------------------------------
#
# The point of the demo is not that a board came back. It is that these particular
# bounds, read out of a file, governed it.


@pytest.mark.req("CST-010")
def test_the_cast_availability_fixture_bounds_the_finished_board(solved):
    problem, result = solved
    start, end = SARAH_WINDOW
    worked = {
        a.shoot_day for a in result.board.assignments
        if "SARAH" in next(w for w in problem.work_items if w.work_id == a.work_id).cast_ids
    }
    assert worked, "SARAH is in the fixture; a board scheduling her nowhere is not a pass"
    assert all(start <= day <= end for day in worked), sorted(worked)


@pytest.mark.req("SOL-006")
def test_the_permit_window_fixture_bounds_the_finished_board(solved):
    _, result = solved
    start, end = CHURCH_WINDOW
    church = {a.shoot_day for a in result.board.assignments if a.location_id == "st-anns-church"}
    assert church, "the church scenes must be somewhere"
    assert all(start <= day <= end for day in church), sorted(church)


@pytest.mark.req("DAY-001", "DAY-003", "DAY-008", "DAY-009")
def test_sun_bound_work_finishes_before_the_computed_sunset(solved):
    """Recomputed here from the date and the place, not read off the board.

    Checking the board against a stored sunset would be checking it against the bug
    this project keeps meeting: a plausible clock time bound to the wrong date.
    """
    from coverset.daylight import daylight_window

    problem, result = solved
    checked = 0
    for a in result.board.assignments:
        item = next(w for w in problem.work_items if w.work_id == a.work_id)
        if not item.needs_daylight:
            continue
        window = daylight_window(LOCATIONS[a.location_id], a.shoot_day)
        assert window.sunrise <= a.planned_call_time
        assert a.planned_wrap_time <= window.sunset
        checked += 1
    assert checked, "no sun-bound work in the fixture would make this test vacuous"


@pytest.mark.req("SOL-006")
def test_a_shoot_day_is_a_day_shoot_or_a_night_shoot_and_never_both(solved):
    problem, result = solved
    by_id = {w.work_id: w for w in problem.work_items}
    for day in result.board.days:
        kinds = {by_id[a.work_id].day_night for a in day}
        assert kinds in ({DayNight.DAY}, {DayNight.NIGHT}), (day.date, kinds)


# -- the output ----------------------------------------------------------------


@pytest.mark.req("OUT-003", "AUD-001")
def test_the_rendered_artifact_carries_the_board_and_its_reasoning(solved):
    problem, result = solved
    text = render(problem, result)

    for scene_id in (w.scene_id for w in problem.work_items):
        assert f"sc {scene_id}" in text
    assert "Brooklyn Bridge Park" in text and "St. Ann's Church" in text
    assert "MAYA" in text  # characters, not cast ids
    assert problem.constraint_snapshot_hash[:12] in text
    # Every constraint is shown with what produced it, not merely named.
    assert "Dana Whitfield" in text and "NOAA solar position algorithm" in text
    assert "Bounded by:" in text


@pytest.mark.req("SOL-009")
def test_the_artifact_states_the_cost_in_production_terms(solved):
    problem, result = solved
    text = render(problem, result)
    for term in ("company moves", "cast holding days", "overtime hours", "added shoot days"):
        assert term in text


@pytest.mark.req("SOL-007")
def test_the_demo_exits_non_zero_when_no_board_is_returned(tmp_path, capsys):
    """A demo that exits 0 having produced no board is one that gets remembered as passing."""
    (tmp_path / "scenes.json").write_text(
        (build_problem.__globals__["FIXTURES"] / "scenes.json").read_text()
    )
    # One scene longer than any day the company allows: infeasible before any
    # constraint applies, so the run must fail loudly rather than print four days.
    scenes = json.loads((tmp_path / "scenes.json").read_text())
    scenes[0]["page_eighths"] = 200
    (tmp_path / "scenes.json").write_text(json.dumps(scenes))
    (tmp_path / "constraints.json").write_text(
        (build_problem.__globals__["FIXTURES"] / "constraints.json").read_text()
    )

    assert main(["--fixtures", str(tmp_path)]) == 1
    assert "NO BOARD" in capsys.readouterr().out


# -- constraint fixture import --------------------------------------------------


@pytest.mark.req("CON-004")
def test_a_constraint_fixture_file_loads_into_a_typed_set():
    records = load_constraints((build_problem.__globals__["FIXTURES"] / "constraints.json"))
    assert {r.constraint_id for r in records} == {
        "C-DAYLIGHT", "C-SARAH-AVAILABILITY", "C-CHURCH-PERMIT",
        "C-TURNAROUND", "C-COMPANY-DAY",
    }
    # Provenance survives import. A bound whose author was dropped cannot be queried
    # by the person who has to renegotiate it.
    assert records["C-SARAH-AVAILABILITY"].source.describe().startswith("Dana Whitfield")


@pytest.mark.req("CON-004")
def test_constraint_import_reports_every_problem_at_once():
    """One error per run turns repairing a constraint file into a guessing game."""
    with pytest.raises(FixtureError) as exc:
        load_constraints(json.dumps([
            {"constraint_id": "C-1", "family": "cast", "policy": "invented",
             "subject": {"kind": "cast", "ref": "X"},
             "expression": {"type": "minimum_rest", "hours": "twelve"},
             "source": {"type": "human", "author": {"name": "D", "role": "gaffer"},
                        "statement": "x"}},
            {"constraint_id": "C-2", "family": "cast", "policy": "hard",
             "subject": {"kind": "cast", "ref": "Y"},
             "expression": {"type": "telepathy"}, "source": {"type": "algorithm"}},
        ]))
    problems = "\n".join(exc.value.problems)
    assert "policy 'invented'" in problems
    assert "hours must be a number" in problems
    assert "role 'gaffer'" in problems          # independent checks do not cascade
    assert "expression type 'telepathy'" in problems


@pytest.mark.req("CON-004")
def test_a_date_window_constraint_with_no_windows_is_refused_rather_than_read_as_unrestricted():
    with pytest.raises(FixtureError) as exc:
        load_constraints(json.dumps([{
            "constraint_id": "C-1", "family": "cast", "policy": "hard",
            "subject": {"kind": "cast", "ref": "X"},
            "expression": {"type": "date_windows", "windows": []},
            "source": {"type": "algorithm"},
        }]))
    assert "non-empty" in "\n".join(exc.value.problems)


@pytest.mark.req("CON-008")
def test_a_fixture_cannot_smuggle_a_retrieved_sunset_in_as_a_daylight_constraint():
    """The file format offers grounded provenance; the record type refuses it here.

    A retrieved sunset was wrong for the shoot date in 8 of 8 live sources, so this
    stays unrepresentable rather than checked at the loader -- the loader is one more
    place someone could add an exception.
    """
    with pytest.raises(FixtureError) as exc:
        load_constraints(json.dumps([{
            "constraint_id": "C-DAYLIGHT", "family": "daylight", "policy": "hard",
            "subject": {"kind": "schedule"}, "expression": {"type": "daylight"},
            "source": {"type": "grounded", "evidence_id": "E1",
                       "source_urls": ["https://example.invalid/sunset"]},
        }]))
    assert "CON-008" in "\n".join(exc.value.problems)


@pytest.mark.req("CON-005")
def test_a_constraint_naming_someone_off_the_roster_blocks_the_solve(tmp_path):
    """Not a no-op: a bound that fails to apply is how a board violates a live rule."""
    (tmp_path / "scenes.json").write_text(
        (build_problem.__globals__["FIXTURES"] / "scenes.json").read_text()
    )
    records = json.loads(
        (build_problem.__globals__["FIXTURES"] / "constraints.json").read_text()
    )
    for r in records:
        if r["constraint_id"] == "C-SARAH-AVAILABILITY":
            r["subject"]["ref"] = "SARA"  # the typo that schedules nobody
    (tmp_path / "constraints.json").write_text(json.dumps(records))

    with pytest.raises(UnresolvedConstraints) as exc:
        build_problem(tmp_path)
    assert "SARA" in str(exc.value)


@pytest.mark.req("CST-001", "CST-003")
def test_cast_are_typed_entities_and_silence_means_available():
    assert ROSTER["TOM"].character == "DEV"
    assert not ROSTER["TOM"].availability
    assert ROSTER["TOM"].is_available_on(dt.date(2026, 9, 18))
    # SARAH's restriction is a constraint record, not a field on the performer: it is
    # a bound on the schedule, so it reaches the solver with an id and provenance.
    assert not ROSTER["SARAH"].availability
