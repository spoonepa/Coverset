"""Tests for CP-SAT scheduling, independent validation, and board output.

The failure this suite is really written against is the one CP-SAT cannot detect for
itself: a model that is solved perfectly and is not the production's problem. So the
assertions are mostly about what the solver is *not* allowed to get away with —
returning an unvalidated board, reporting a conflict padded with constraints that are
not load-bearing, or agreeing with itself about what a board costs.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import inspect

import pytest

from coverset.actors import Actor, Role
from coverset.board import (
    Assignment,
    Board,
    ConstraintCheck,
    InvalidBoard,
    ObjectiveBreakdown,
    SolverStatus,
    ValidationReport,
)
from coverset.daylight import daylight_window
from coverset.constraints import (
    AlgorithmSource,
    BlackoutDates,
    ConstraintRecord,
    ConstraintSet,
    DateWindows,
    DaylightBound,
    Family,
    HumanSource,
    MaximumDailyHours,
    MinimumRest,
    PinnedDay,
    Policy,
    Subject,
    SubjectKind,
)
from coverset.locations import Location, LocationBook
from coverset.people import AvailabilityWindow, CastMember, Company, Roster
from coverset.scenes import CandidateStatus, IntExt, SceneRecord
from coverset.solver import (
    DECLARED_WEIGHTS,
    MODEL_VERSION,
    ObjectiveWeights,
    ProductionCalendar,
    ScheduleProblem,
    SolverError,
    UndeclaredWeight,
    solve,
)
from coverset.stripboard import explain_assignment, stripboard
from coverset.validate import UncheckableConstraint, validate_board
from coverset.work import DayNight

AD = Actor("Dana Whitfield", Role.FIRST_AD)

PARK = Location("Brooklyn Bridge Park", "Brooklyn", "NY",
                latitude=40.7002, longitude=-73.9967, timezone="America/New_York")
STUDIO = Location("Silvercup Studios", "Queens", "NY",
                  latitude=40.7423, longitude=-73.9382, timezone="America/New_York")
PLACES = LocationBook((PARK, STUDIO))
ROSTER = Roster((
    CastMember("SARAH", "S. Idowu", "MAYA"),
    CastMember("TOM", "D. Whitfield", "DEV"),
))

D1, D2, D3 = dt.date(2026, 9, 14), dt.date(2026, 9, 15), dt.date(2026, 9, 16)


def scene(scene_id, location, day_night, eighths, cast, int_ext=IntExt.EXT):
    return SceneRecord(
        scene_id=scene_id, scene_number=scene_id, slugline=f"SC {scene_id}",
        int_ext=int_ext, day_night=day_night, location_ref=location.id,
        page_eighths=eighths, cast_ids=cast, status=CandidateStatus.ACTIVE,
    )


DAYLIGHT_RULE = ConstraintRecord(
    constraint_id="C-DAYLIGHT", family=Family.DAYLIGHT, policy=Policy.HARD,
    subject=Subject(SubjectKind.SCHEDULE), expression=DaylightBound(),
    source=AlgorithmSource(), created_by="coverset.daylight",
)


def human(cid, family, subject, expression, said="production rule"):
    return ConstraintRecord(
        constraint_id=cid, family=family, policy=Policy.HARD, subject=subject,
        expression=expression, source=HumanSource(AD, said, from_fixture=True),
    )


def two_day_problem(*, constraints=(DAYLIGHT_RULE,), days=(D1, D2), weights=DECLARED_WEIGHTS,
                    company=Company(), problem_id="SOL010"):
    """The `SOL-010` acceptance fixture: two scenes, two days, one day and one night."""
    work = (
        scene("S1", PARK, DayNight.DAY, 16, ("SARAH",)).to_work_item(),
        scene("S2", STUDIO, DayNight.NIGHT, 24, ("SARAH", "TOM"), IntExt.INT).to_work_item(),
    )
    return ScheduleProblem(
        problem_id=problem_id,
        production_calendar=ProductionCalendar(days),
        work_items=work,
        constraints=ConstraintSet(constraints),
        roster=ROSTER,
        locations=PLACES,
        company=company,
        weights=weights,
    )


PIER = Location("Pier 59", "Manhattan", "NY",
                latitude=40.7466, longitude=-74.0083, timezone="America/New_York")


def crowded_problem(*, weights=DECLARED_WEIGHTS, days=8):
    """A problem too big to presolve, so the search really is cut off mid-flight.

    `two_day_problem` is decided before the objective does any work, which hides
    anything that only holds once CP-SAT has driven a counter to its bound. This one
    has enough placements to come back `FEASIBLE`.
    """
    places = LocationBook((PARK, STUDIO, PIER))
    roster = Roster(tuple(CastMember(f"C{i}", f"Perf {i}", f"ROLE{i}") for i in range(6)))
    where = (PARK, STUDIO, PIER)
    work = tuple(
        scene(f"S{i}", where[i % 3], DayNight.NIGHT if i % 5 == 0 else DayNight.DAY,
              12, tuple(f"C{(i + k) % 6}" for k in range(2)),
              IntExt.INT if where[i % 3] is STUDIO else IntExt.EXT).to_work_item()
        for i in range(14)
    )
    return ScheduleProblem(
        problem_id="CROWD",
        production_calendar=ProductionCalendar(
            tuple(D1 + dt.timedelta(days=k) for k in range(days))
        ),
        work_items=work, constraints=ConstraintSet(()),
        roster=roster, locations=places, weights=weights,
    )


# -- SOL-001: the schedule comes from CP-SAT ------------------------------------


@pytest.mark.req("SOL-001")
def test_the_board_is_produced_by_cp_sat():
    result = solve(two_day_problem())
    assert result.status is SolverStatus.OPTIMAL
    assert MODEL_VERSION in result.board.solver_parameters


@pytest.mark.req("SOL-001")
def test_no_language_model_sits_in_the_scheduling_path():
    """Structural, not aspirational: the solver cannot reach a model client at all.

    A docstring saying "no LLM emits a schedule" is the kind of rule a refactor
    removes. An import that does not exist is not.
    """
    import coverset.solver as solver_module

    source = inspect.getsource(solver_module)
    for forbidden in ("google.generativeai", "genai", "openai", "anthropic", "gemini"):
        assert forbidden not in source.lower(), (
            f"{forbidden!r} appears in the solver; no language model may emit a schedule"
        )


# -- SOL-010: the acceptance fixture --------------------------------------------


@pytest.mark.req("SOL-010")
def test_two_day_two_scene_fixture_schedules_and_validates_cleanly():
    result = solve(two_day_problem())
    board = result.board
    assert board.shoot_day_count == 2
    assert len(board.assignments) == 2
    assert board.validation_result.passed
    assert board.validation_result.constraint_snapshot_hash == board.constraint_snapshot_hash


@pytest.mark.req("SOL-010")
def test_the_same_problem_and_seed_produces_the_same_board():
    """Determinism is per seed. Probing showed two seeds give different, equally
    optimal boards, which is why the seed is recorded rather than assumed."""
    first = solve(two_day_problem(), seed=7).board
    second = solve(two_day_problem(), seed=7).board
    assert first.assignments == second.assignments
    assert first.solver_objective_value == second.solver_objective_value
    assert "seed=7" in first.solver_parameters


@pytest.mark.req("SOL-010")
def test_a_night_scene_is_called_at_sunset_and_a_day_scene_at_sunrise():
    board = solve(two_day_problem()).board
    by_work = {a.work_id: a for a in board.assignments}
    assert by_work["W-S2"].planned_call_time.hour >= 18, "night work should call at dusk"
    assert by_work["W-S1"].planned_call_time.hour <= 8, "daylight work should call at sunrise"


# -- SOL-002 / SOL-007: nothing unvalidated escapes ------------------------------


@pytest.mark.req("SOL-002")
def test_every_binding_constraint_is_re_checked_on_the_returned_board():
    availability = human(
        "C-SARAH", Family.CAST, Subject(SubjectKind.CAST, "SARAH"),
        DateWindows((AvailabilityWindow(D1, D3),)),
    )
    board = solve(two_day_problem(constraints=(DAYLIGHT_RULE, availability))).board
    checked = {c.constraint_id for c in board.validation_result.checks}
    # `SYN-COMPANY-DAY` is here because the production's maximum day is a constraint
    # like any other. It used to be compiled straight from `Company`, which meant it
    # was re-checked by nobody — the whole point of this assertion.
    assert checked == {"C-DAYLIGHT", "C-SARAH", "SYN-COMPANY-DAY"}
    assert board.validation_result.passed


@pytest.mark.req("SOL-007")
def test_a_board_cannot_be_constructed_from_an_unproven_solve():
    report = ValidationReport(checks=(), expected_ids=frozenset(), constraint_snapshot_hash="h")
    good = solve(two_day_problem()).board
    with pytest.raises(InvalidBoard, match="no solution was proven"):
        dataclasses.replace(good, solver_status=SolverStatus.UNKNOWN, validation_result=report,
                            constraint_snapshot_hash="h")


@pytest.mark.req("SOL-007")
def test_a_board_cannot_be_constructed_when_validation_fails():
    good = solve(two_day_problem()).board
    failed = ValidationReport(
        checks=(ConstraintCheck("C-X", Family.CAST, Policy.HARD, satisfied=False,
                                detail="scheduled outside availability"),),
        expected_ids=frozenset({"C-X"}),
        constraint_snapshot_hash=good.constraint_snapshot_hash,
    )
    with pytest.raises(InvalidBoard, match="independent validation failed"):
        dataclasses.replace(good, validation_result=failed)


@pytest.mark.req("SOL-007")
def test_a_board_validated_against_a_different_snapshot_is_rejected():
    good = solve(two_day_problem()).board
    stale = dataclasses.replace(good.validation_result, constraint_snapshot_hash="0" * 64)
    with pytest.raises(InvalidBoard, match="different problem"):
        dataclasses.replace(good, validation_result=stale)


@pytest.mark.req("SOL-007")
def test_a_validation_report_that_skipped_a_binding_constraint_cannot_be_built():
    """A vacuous report is worse than none: it certifies a board nobody examined."""
    with pytest.raises(InvalidBoard, match="never evaluated"):
        ValidationReport(
            checks=(), expected_ids=frozenset({"C-SARAH"}), constraint_snapshot_hash="h"
        )


@pytest.mark.req("SOL-007")
def test_unknown_status_is_not_reported_as_a_schedule():
    """A budget of zero cuts the search off before anything is proven."""
    result = solve(two_day_problem(), budget=0.0)
    assert result.status is SolverStatus.UNKNOWN
    assert result.viable_boards == ()
    with pytest.raises(SolverError):
        result.board


@pytest.mark.req("SOL-007")
def test_the_models_own_cost_counters_are_exact_at_every_status():
    """The cost cross-check is a second reading only if the first one is exact.

    `moves` and `held` used to be pinned by one-sided bounds that only the objective
    closed, so a solve stopped before proven optimality left them slack above the
    truth. `solve` then compared that slack against the count measured off the board
    and returned ERROR -- discarding a board that had already passed independent
    validation, and blaming a miscompile that was not there.

    Cutting the deterministic budget short is what exercises it: a board is found but
    nothing is proven optimal, which is the ordinary case on a real production.
    """
    problem = crowded_problem()
    seen = set()
    for budget in (0.05, 0.1, 0.25, 0.5, 1.0, 2.0):
        result = solve(problem, budget=budget)
        assert result.status is not SolverStatus.ERROR, (
            f"budget {budget}: {result.diagnostics}"
        )
        seen.add(result.status)
    assert SolverStatus.FEASIBLE in seen, (
        "no budget produced an unproven board, so nothing here exercised the case"
    )


@pytest.mark.req("SOL-007")
def test_a_zero_weight_does_not_unpin_the_term_it_weights():
    """A weight of zero removes the only pressure a one-sided counter had.

    Worse than the truncated budget above, because it does not depend on where the
    search stopped: the term is unpinned for the whole solve, so even a proven
    optimal board reported a cost the board did not contain.
    """
    for weights in (
        ObjectiveWeights(company_move=50.0, cast_holding_day=0.0, overtime_hour=0.5),
        ObjectiveWeights(company_move=0.0, cast_holding_day=0.0, overtime_hour=0.5),
    ):
        result = solve(crowded_problem(weights=weights, days=6))
        assert result.status is not SolverStatus.ERROR, (
            f"{weights}: {result.diagnostics}"
        )
        board = result.board
        # Reaching a board at all means the model and the measurement agreed. Count
        # the moves a third time, off `board.days`, rather than trusting that: within
        # each day, plus every wrap that does not call where it left off.
        days_in_order = board.days
        within = sum(d.company_moves for d in days_in_order)
        overnight = sum(
            1 for before, after in zip(days_in_order, days_in_order[1:])
            if before.location_ids[-1] != after.location_ids[0]
        )
        assert board.objective_breakdown.company_moves == within + overnight


# -- SOL-013: how far from optimal ----------------------------------------------


@pytest.mark.req("SOL-013")
def test_a_proven_optimal_board_records_a_matching_bound_and_no_gap():
    board = solve(two_day_problem()).board
    assert board.is_proven_optimal
    assert board.optimality_gap == 0.0
    assert board.solver_best_bound == board.solver_objective_value
    assert "proven optimal" in board.cost_bracket


@pytest.mark.req("SOL-013")
def test_a_board_cannot_claim_optimal_while_carrying_a_gap():
    """Optimal means proven. The two cannot both be true."""
    good = solve(two_day_problem()).board
    with pytest.raises(InvalidBoard, match="cannot"):
        dataclasses.replace(good, optimality_gap=0.2)


@pytest.mark.req("SOL-013")
def test_a_negative_gap_is_refused():
    good = solve(two_day_problem()).board
    with pytest.raises(InvalidBoard, match="negative optimality gap"):
        dataclasses.replace(good, solver_status=SolverStatus.FEASIBLE, optimality_gap=-0.1)


@pytest.mark.req("SOL-013")
def test_an_unproven_board_states_how_far_from_optimal_it_may_be():
    good = solve(two_day_problem()).board
    unproven = dataclasses.replace(
        good, solver_status=SolverStatus.FEASIBLE,
        solver_objective_value=500.0, solver_best_bound=400.0, optimality_gap=0.2,
    )
    assert not unproven.is_proven_optimal
    assert "within 20.0% of optimal" in unproven.cost_bracket


@pytest.mark.req("SOL-013")
def test_the_gap_is_defined_when_a_board_costs_nothing():
    """A small fixture reaches zero cost easily; the gap must not divide by zero."""
    from coverset.solver import _relative_gap

    assert _relative_gap(0.0, 0.0) == 0.0
    assert _relative_gap(0.0, -0.0) == 0.0
    assert _relative_gap(100.0, 80.0) == pytest.approx(0.2)
    assert _relative_gap(100.0, 100.000001) == 0.0, "float noise is not a negative gap"


@pytest.mark.req("SOL-010")
def test_the_solve_budget_is_deterministic_rather_than_wall_clock():
    """A wall-clock cutoff makes the board depend on machine speed, which defeats
    recording the seed for reproducibility."""
    import inspect

    import coverset.solver as solver_module

    source = inspect.getsource(solver_module.solve)
    assert "max_deterministic_time" in source
    assert "max_time_in_seconds" not in source
    assert "det" in solve(two_day_problem()).board.solver_parameters


# -- SOL-003 / SOL-011: infeasibility is explained irreducibly -------------------


def conflicting_problem():
    """One scene needing two performers whose availability windows are disjoint."""
    work = (scene("S2", STUDIO, DayNight.NIGHT, 24, ("SARAH", "TOM"), IntExt.INT).to_work_item(),)
    constraints = (
        human("C-SARAH", Family.CAST, Subject(SubjectKind.CAST, "SARAH"),
              DateWindows((AvailabilityWindow(D1, D1),))),
        human("C-TOM", Family.CAST, Subject(SubjectKind.CAST, "TOM"),
              DateWindows((AvailabilityWindow(D2, D2),))),
        human("C-STUDIO", Family.LOCATION, Subject(SubjectKind.LOCATION, STUDIO.id),
              DateWindows((AvailabilityWindow(D1, D2),))),
    )
    return ScheduleProblem(
        problem_id="CONFLICT",
        production_calendar=ProductionCalendar((D1, D2)),
        work_items=work,
        constraints=ConstraintSet(constraints),
        roster=ROSTER,
        locations=PLACES,
    )


@pytest.mark.req("SOL-011")
def test_impossible_cast_availability_returns_the_expected_conflict_ids():
    result = solve(conflicting_problem())
    assert result.status is SolverStatus.INFEASIBLE
    assert result.conflict_set is not None
    assert set(result.conflict_set.constraint_ids) == {"C-SARAH", "C-TOM"}


@pytest.mark.req("SOL-003")
def test_the_conflict_set_is_irreducible():
    """Removing any one member must make the conflict no longer provable."""
    result = solve(conflicting_problem())
    conflict = result.conflict_set
    assert conflict.irreducible

    from coverset.solver import _infeasible_with

    problem = conflicting_problem()
    assert _infeasible_with(problem, conflict.constraint_ids)
    for drop in conflict.constraint_ids:
        remainder = [c for c in conflict.constraint_ids if c != drop]
        assert not _infeasible_with(problem, remainder), (
            f"{drop} is not load-bearing, so the reported conflict is not irreducible"
        )


@pytest.mark.req("SOL-003")
def test_constraints_unrelated_to_the_conflict_are_filtered_out():
    """CP-SAT's raw core includes the studio window here; it is not load-bearing.

    Handing an AD a constraint to renegotiate when relaxing it would change nothing
    is a confident wrong answer, which is the class of failure this project designs
    against rather than the class it tolerates.
    """
    result = solve(conflicting_problem())
    assert "C-STUDIO" not in result.conflict_set.constraint_ids
    assert "reduced from" in result.conflict_set.detail


# -- SOL-005: declared weights ---------------------------------------------------


@pytest.mark.req("SOL-005")
def test_the_declared_weights_match_the_specification():
    assert (DECLARED_WEIGHTS.company_move, DECLARED_WEIGHTS.cast_holding_day,
            DECLARED_WEIGHTS.overtime_hour) == (3.0, 1.0, 0.5)


@pytest.mark.req("SOL-005")
def test_weights_have_no_defaults_and_negatives_are_refused():
    with pytest.raises(TypeError):
        ObjectiveWeights()  # type: ignore[call-arg]
    with pytest.raises(UndeclaredWeight, match="must not be negative"):
        ObjectiveWeights(company_move=-1.0, cast_holding_day=1.0, overtime_hour=0.5)


@pytest.mark.req("SOL-005")
def test_the_declared_ratio_survives_as_exact_integer_coefficients():
    """Rounding a weight quietly changes which board wins, invisibly in the breakdown."""
    move, hold, per_minute = DECLARED_WEIGHTS.integer_coefficients()
    assert move / hold == 3.0
    assert (per_minute * 60) / hold == 0.5


@pytest.mark.req("SOL-005")
def test_changing_the_weights_changes_which_board_wins():
    """Three scenes, two locations: cluster by location, or release cast early."""
    work = (
        scene("A1", PARK, DayNight.DAY, 8, ("SARAH",)).to_work_item(),
        scene("A2", STUDIO, DayNight.DAY, 8, ("TOM",), IntExt.INT).to_work_item(),
        scene("A3", PARK, DayNight.DAY, 8, ("SARAH",)).to_work_item(),
    )

    def board_for(weights):
        return solve(ScheduleProblem(
            problem_id="W", production_calendar=ProductionCalendar((D1, D2, D3)),
            work_items=work, constraints=ConstraintSet((DAYLIGHT_RULE,)),
            roster=ROSTER, locations=PLACES, weights=weights,
        )).board

    move_averse = board_for(ObjectiveWeights(company_move=50.0, cast_holding_day=1.0,
                                             overtime_hour=0.5))
    cast_averse = board_for(ObjectiveWeights(company_move=0.0, cast_holding_day=50.0,
                                             overtime_hour=0.5))
    assert move_averse.objective_breakdown.company_moves <= (
        cast_averse.objective_breakdown.company_moves
    )


# -- SOL-006: the MVP constraint families are modelled ---------------------------


@pytest.mark.req("SOL-006")
def test_cast_availability_moves_the_board():
    """Sarah is in both scenes, and both are hers to be available for."""
    not_the_first_day = human(
        "C-SARAH", Family.CAST, Subject(SubjectKind.CAST, "SARAH"),
        DateWindows((AvailabilityWindow(D2, D3),)),
    )
    board = solve(two_day_problem(
        constraints=(DAYLIGHT_RULE, not_the_first_day), days=(D1, D2, D3)
    )).board
    assert board.day_of("W-S1") in (D2, D3)
    assert board.day_of("W-S2") in (D2, D3)


@pytest.mark.req("SOL-006")
def test_a_location_blackout_moves_the_board():
    closed = human(
        "C-PARK", Family.PERMIT, Subject(SubjectKind.LOCATION, PARK.id),
        BlackoutDates((D2,)),
    )
    board = solve(two_day_problem(constraints=(DAYLIGHT_RULE, closed))).board
    assert board.day_of("W-S1") == D1


@pytest.mark.req("SOL-006")
def test_a_lock_pins_work_to_its_day():
    pinned = human(
        "C-LOCK", Family.LOCK, Subject(SubjectKind.WORK, "W-S1"), PinnedDay(D1),
    )
    board = solve(two_day_problem(constraints=(DAYLIGHT_RULE, pinned))).board
    assert board.day_of("W-S1") == D1


@pytest.mark.req("SOL-006")
def test_a_company_move_is_counted_and_costs_shooting_time():
    """Two locations in one day is one move; it also consumes the day."""
    work = (
        scene("B1", PARK, DayNight.DAY, 8, ("SARAH",)).to_work_item(),
        scene("B2", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item(),
    )
    board = solve(ScheduleProblem(
        problem_id="MOVE", production_calendar=ProductionCalendar((D1,)),
        work_items=work, constraints=ConstraintSet((DAYLIGHT_RULE,)),
        roster=ROSTER, locations=PLACES,
    )).board
    assert board.objective_breakdown.company_moves == 1
    day = board.days[0]
    gap = day.length - sum((dt.timedelta(minutes=60), dt.timedelta(minutes=60)), dt.timedelta())
    assert gap >= dt.timedelta(minutes=60), "a move must consume shooting time"


@pytest.mark.req("SOL-006")
def test_a_day_shoot_and_a_night_shoot_do_not_share_a_day():
    """Split days are post-MVP, so mixing them is refused rather than approximated."""
    board = solve(two_day_problem()).board
    for day in board.days:
        kinds = {a.planned_call_time.hour >= 18 for a in day}
        assert len(kinds) == 1


@pytest.mark.req("SOL-006")
def test_a_maximum_day_length_constrains_the_board():
    long_scene = scene("L1", STUDIO, DayNight.DAY, 90, ("SARAH",), IntExt.INT).to_work_item()
    short = scene("L2", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item()
    problem = ScheduleProblem(
        problem_id="LEN", production_calendar=ProductionCalendar((D1, D2)),
        work_items=(long_scene, short), constraints=ConstraintSet((DAYLIGHT_RULE,)),
        roster=ROSTER, locations=PLACES, company=Company(maximum_day_hours=12.0),
    )
    board = solve(problem).board
    for day in board.days:
        assert day.length <= dt.timedelta(hours=12)


# -- CST-010 / DAY-009: constraints are independently evaluable ------------------


@pytest.mark.req("CST-010")
def test_a_cast_availability_constraint_is_evaluable_against_a_finished_board():
    availability = human(
        "C-SARAH", Family.CAST, Subject(SubjectKind.CAST, "SARAH"),
        DateWindows((AvailabilityWindow(D1, D1),)),
    )
    problem = ScheduleProblem(
        problem_id="CST010",
        production_calendar=ProductionCalendar((D1, D2)),
        work_items=(
            scene("S1", PARK, DayNight.DAY, 16, ("SARAH",)).to_work_item(),
            scene("S2", STUDIO, DayNight.NIGHT, 24, ("TOM",), IntExt.INT).to_work_item(),
        ),
        constraints=ConstraintSet((DAYLIGHT_RULE, availability)),
        roster=ROSTER, locations=PLACES,
    )
    board = solve(problem).board
    assert board.day_of("W-S1") == D1

    honest = validate_board(
        board.assignments, constraints=problem.constraints, work_items=problem.work_items,
        locations=PLACES, roster=ROSTER,
    )
    assert honest.passed

    # The same check, run against a board that moves Sarah outside her window, must fail.
    moved = tuple(
        dataclasses.replace(
            a,
            shoot_day=D2,
            planned_call_time=a.planned_call_time.replace(day=D2.day),
            planned_wrap_time=a.planned_wrap_time.replace(day=D2.day),
        )
        if a.work_id == "W-S1" else a
        for a in board.assignments
    )
    caught = validate_board(
        moved, constraints=problem.constraints, work_items=problem.work_items,
        locations=PLACES, roster=ROSTER,
    )
    assert not caught.passed
    assert "C-SARAH" in {v.constraint_id for v in caught.violations}


@pytest.mark.req("CST-010")
def test_a_minor_work_hour_limit_is_evaluable_against_a_finished_board():
    limit = human(
        "C-MINOR", Family.CAST, Subject(SubjectKind.CAST, "SARAH"), MaximumDailyHours(1.0),
    )
    problem = two_day_problem(constraints=(DAYLIGHT_RULE,))
    board = solve(problem).board
    report = validate_board(
        board.assignments, constraints=ConstraintSet((limit,)),
        work_items=problem.work_items, locations=PLACES, roster=ROSTER,
    )
    assert not report.passed, "a two-hour strip must breach a one-hour daily limit"


@pytest.mark.req("DAY-009")
def test_a_daylight_constraint_is_evaluable_against_a_finished_board():
    problem = two_day_problem()
    board = solve(problem).board
    report = validate_board(
        board.assignments, constraints=problem.constraints, work_items=problem.work_items,
        locations=PLACES, roster=ROSTER,
    )
    assert report.passed

    after_dark = tuple(
        dataclasses.replace(
            a,
            planned_call_time=a.planned_call_time.replace(hour=21, minute=0),
            planned_wrap_time=a.planned_wrap_time.replace(hour=23, minute=0),
        )
        if a.work_id == "W-S1" else a
        for a in board.assignments
    )
    caught = validate_board(
        after_dark, constraints=problem.constraints, work_items=problem.work_items,
        locations=PLACES, roster=ROSTER,
    )
    assert not caught.passed
    assert "outside daylight" in caught.violations[0].detail


@pytest.mark.req("DAY-009")
def test_the_validator_cannot_reach_the_compiler_it_is_checking():
    """The independence is a matter of imports, not of anyone remembering.

    A validator that reuses the compiler checks a method against another instance of
    itself — the mistake `daylight.py` was written to document.
    """
    import ast

    import coverset.validate as validator

    tree = ast.parse(inspect.getsource(validator))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("ortools" in name for name in imported), imported
    assert not any(name.endswith("solver") for name in imported), imported


@pytest.mark.req("DAY-009")
def test_a_constraint_the_validator_cannot_read_refuses_to_certify_the_board():
    """Skipping an unknown constraint would certify a board nobody examined."""
    odd = human(
        "C-ODD", Family.TURNAROUND, Subject(SubjectKind.LOCATION, PARK.id), MinimumRest(12),
    )
    problem = two_day_problem()
    board = solve(problem).board
    with pytest.raises(UncheckableConstraint, match="C-ODD"):
        validate_board(
            board.assignments, constraints=ConstraintSet((odd,)),
            work_items=problem.work_items, locations=PLACES, roster=ROSTER,
        )


# -- DAY-008: daylight is recomputed at solve time -------------------------------


@pytest.mark.req("DAY-008")
def test_daylight_is_recomputed_per_date_rather_than_stored():
    """A stored sunset is a sunset for whichever date it was stored on."""
    september = solve(two_day_problem(days=(D1, D2))).board
    december = solve(two_day_problem(days=(dt.date(2026, 12, 14), dt.date(2026, 12, 15)))).board
    sept_call = min(a.planned_call_time.time() for a in september.assignments
                    if a.work_id == "W-S1")
    dec_call = min(a.planned_call_time.time() for a in december.assignments
                   if a.work_id == "W-S1")
    assert sept_call != dec_call, "sunrise must differ between September and December"


@pytest.mark.req("DAY-008")
def test_a_daylight_bound_carries_no_times_of_its_own():
    assert not any(
        isinstance(getattr(DaylightBound(), f), (dt.time, dt.datetime))
        for f in DaylightBound.__dataclass_fields__
    )
    assert DaylightBound().algorithm.startswith("NOAA")


# -- SOL-008 / SOL-009: what a board records -------------------------------------


@pytest.mark.req("SOL-008")
def test_a_board_records_status_model_version_objective_hash_and_validation():
    problem = two_day_problem()
    board = solve(problem).board
    assert board.solver_status is SolverStatus.OPTIMAL
    assert MODEL_VERSION in board.solver_parameters
    assert "seed=" in board.solver_parameters
    assert board.solver_objective_value > 0
    assert board.constraint_snapshot_hash == problem.constraint_snapshot_hash
    assert board.validation_result.passed
    assert "move=3" in board.objective_weights


@pytest.mark.req("SOL-009")
def test_the_objective_breakdown_reports_each_term_separately():
    board = solve(two_day_problem()).board
    breakdown = board.objective_breakdown
    assert breakdown.company_moves == 1
    assert breakdown.holding_days == 0
    assert breakdown.overtime_hours == 0
    rendered = "\n".join(breakdown.lines())
    for term in ("company moves", "cast holding days", "overtime hours",
                 "added shoot days", "weather risk cost"):
        assert term in rendered


@pytest.mark.req("SOL-009")
def test_holding_days_are_measured_off_the_board_not_read_back_from_the_model():
    """Three days, one performer working the outer two: one held day in the middle."""
    work = (
        scene("H1", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item(),
        scene("H2", STUDIO, DayNight.DAY, 8, ("TOM",), IntExt.INT).to_work_item(),
        scene("H3", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item(),
    )
    pins = tuple(
        human(f"C-PIN-{i}", Family.LOCK, Subject(SubjectKind.WORK, w.work_id), PinnedDay(d))
        for i, (w, d) in enumerate(zip(work, (D1, D2, D3)))
    )
    board = solve(ScheduleProblem(
        problem_id="HOLD", production_calendar=ProductionCalendar((D1, D2, D3)),
        work_items=work, constraints=ConstraintSet(pins),
        roster=ROSTER, locations=PLACES,
    )).board
    assert board.objective_breakdown.holding_days == 1


@pytest.mark.req("SOL-002")
def test_a_problem_naming_unknown_cast_or_locations_refuses_to_be_built():
    bad = dataclasses.replace(
        scene("S1", PARK, DayNight.DAY, 8, ("SARAH",)).to_work_item(), cast_ids=("SARA",)
    )
    with pytest.raises(SolverError, match="SARA"):
        ScheduleProblem(
            problem_id="BAD", production_calendar=ProductionCalendar((D1,)),
            work_items=(bad,), constraints=ConstraintSet(), roster=ROSTER, locations=PLACES,
        )


# -- OUT-003 / AUD-001: the stripboard and its explanation -----------------------


@pytest.mark.req("OUT-003")
def test_the_stripboard_lists_days_work_scenes_locations_cast_and_call_windows():
    problem = two_day_problem()
    board = solve(problem).board
    rendered = stripboard(board, work_items=problem.work_items, locations=PLACES, roster=ROSTER)
    assert "Mon 14 Sep 2026" in rendered and "Tue 15 Sep 2026" in rendered
    assert "sc S1" in rendered and "sc S2" in rendered
    assert PARK.name in rendered and STUDIO.name in rendered
    assert "DAY" in rendered and "NIGHT" in rendered
    assert "MAYA" in rendered and "DEV" in rendered
    assert "call" in rendered and "wrap" in rendered
    assert "company moves" in rendered


@pytest.mark.req("AUD-001")
def test_a_strip_traces_to_the_active_constraints_that_bounded_it():
    availability = human(
        "C-SARAH", Family.CAST, Subject(SubjectKind.CAST, "SARAH"),
        DateWindows((AvailabilityWindow(D1, D3),)),
    )
    problem = two_day_problem(constraints=(DAYLIGHT_RULE, availability))
    board = solve(problem).board
    trace = explain_assignment(
        board, "W-S1", constraints=problem.constraints, work_items=problem.work_items
    )
    assert "C-DAYLIGHT" in trace and "C-SARAH" in trace
    assert "company moves" in trace and "cast holding days" in trace
    assert board.constraint_snapshot_hash[:12] in trace


@pytest.mark.req("AUD-001")
def test_an_inactive_constraint_is_not_offered_as_a_reason():
    availability = human(
        "C-SARAH", Family.CAST, Subject(SubjectKind.CAST, "SARAH"),
        DateWindows((AvailabilityWindow(D1, D3),)),
    ).deactivate()
    problem = two_day_problem(constraints=(DAYLIGHT_RULE, availability))
    board = solve(problem).board
    trace = explain_assignment(
        board, "W-S1", constraints=problem.constraints, work_items=problem.work_items
    )
    assert "C-SARAH" not in trace


# ==============================================================================
# Holes found by review. Each of these passed the suite while being wrong.
# ==============================================================================


def _pin(cid, work_id, day):
    return human(cid, Family.LOCK, Subject(SubjectKind.WORK, work_id), PinnedDay(day))


@pytest.mark.req("SOL-003")
def test_structural_infeasibility_is_named_rather_than_returned_empty():
    """A scene longer than the maximum day is infeasible before any constraint applies.

    The conflict then comes from problem structure, not from anything relaxable, and
    reporting an empty set as "irreducible" tells a First AD that no schedule exists
    and offers nothing to change.
    """
    huge = scene("X1", STUDIO, DayNight.DAY, 200, ("SARAH",), IntExt.INT).to_work_item()
    result = solve(ScheduleProblem(
        problem_id="STRUCT", production_calendar=ProductionCalendar((D1, D2)),
        work_items=(huge,), constraints=ConstraintSet(()), roster=ROSTER, locations=PLACES,
    ))
    assert result.status is SolverStatus.INFEASIBLE
    conflict = result.conflict_set
    assert conflict.structural_causes, "structural infeasibility must be named"
    assert any("day" in cause.lower() for cause in conflict.structural_causes)
    assert "W-X1" in conflict.detail


@pytest.mark.req("SOL-003")
def test_a_relaxable_constraint_is_not_blamed_for_structural_infeasibility():
    """The 25-hour scene is infeasible with nothing active, so daylight is not the cause.

    Naming it anyway sends someone to renegotiate a constraint whose relaxation
    changes nothing — a confidently wrong explanation, which is the same failure this
    project designs against in values, moved into the diagnosis.
    """
    huge = scene("X1", STUDIO, DayNight.DAY, 200, ("SARAH",), IntExt.INT).to_work_item()
    result = solve(ScheduleProblem(
        problem_id="BLAME", production_calendar=ProductionCalendar((D1, D2)),
        work_items=(huge,), constraints=ConstraintSet((DAYLIGHT_RULE,)),
        roster=ROSTER, locations=PLACES,
    ))
    assert result.status is SolverStatus.INFEASIBLE
    assert "C-DAYLIGHT" not in result.conflict_set.constraint_ids


@pytest.mark.req("SOL-003")
def test_a_day_and_a_night_scene_on_one_available_day_is_named():
    """Split days are refused by the model, so one calendar day cannot hold both."""
    day_work = scene("Y1", PARK, DayNight.DAY, 8, ("SARAH",)).to_work_item()
    night_work = scene("Y2", STUDIO, DayNight.NIGHT, 8, ("TOM",), IntExt.INT).to_work_item()
    result = solve(ScheduleProblem(
        problem_id="SPLIT", production_calendar=ProductionCalendar((D1,)),
        work_items=(day_work, night_work), constraints=ConstraintSet(()),
        roster=ROSTER, locations=PLACES,
    ))
    assert result.status is SolverStatus.INFEASIBLE
    assert result.conflict_set.structural_causes
    assert any("night" in cause.lower() for cause in result.conflict_set.structural_causes)


@pytest.mark.req("SOL-003")
def test_a_conflict_set_that_names_nothing_cannot_be_constructed():
    """An explanation that names nothing explains nothing."""
    from coverset.solver import ConflictSet

    with pytest.raises(SolverError, match="names nothing"):
        ConflictSet(constraint_ids=(), structural_causes=())
    with pytest.raises(SolverError, match="irreducibility is a claim"):
        ConflictSet(constraint_ids=(), structural_causes=("STRUCT-X",), irreducible=True)


@pytest.mark.req("DAY-008")
def test_daylight_cannot_bind_without_a_constraint_record_saying_so():
    """An 11h exterior day scene does not fit a 9h December window.

    Refusing it is right; refusing it on the authority of a bound that appears in no
    constraint set, no snapshot hash and no validation report is not. Nobody can
    trace it, waive it, or find it in the audit trail.
    """
    december = (dt.date(2026, 12, 14), dt.date(2026, 12, 15))
    long_exterior = scene("Z1", PARK, DayNight.DAY, 88, ("SARAH",)).to_work_item()
    problem = ScheduleProblem(
        problem_id="SYN", production_calendar=ProductionCalendar(december),
        work_items=(long_exterior,), constraints=ConstraintSet(()),
        roster=ROSTER, locations=PLACES,
    )
    # The bound must have been made explicit rather than applied invisibly.
    daylight_records = [r for r in problem.constraints if r.family is Family.DAYLIGHT]
    assert daylight_records, "daylight bound the solve, so a record must say so"
    assert daylight_records[0].source.describe().startswith("NOAA")

    result = solve(problem)
    assert result.status is SolverStatus.INFEASIBLE
    assert daylight_records[0].constraint_id in result.conflict_set.constraint_ids


@pytest.mark.req("DAY-008")
def test_a_problem_with_no_daylight_work_gets_no_synthetic_daylight_record():
    interior = scene("I1", STUDIO, DayNight.NIGHT, 8, ("TOM",), IntExt.INT).to_work_item()
    problem = ScheduleProblem(
        problem_id="NOSUN", production_calendar=ProductionCalendar((D1,)),
        work_items=(interior,), constraints=ConstraintSet(()), roster=ROSTER, locations=PLACES,
    )
    assert not [r for r in problem.constraints if r.family is Family.DAYLIGHT]


@pytest.mark.req("SOL-006")
def test_an_overnight_move_is_counted_when_the_day_ends_away_from_where_the_next_begins():
    """Day one plays the park then the studio; day two returns to the park.

    Sharing *a* location with the previous day is not continuity — the unit has to
    travel from wherever it wrapped to wherever it calls. Counting this as one move
    understates the board by a full relocation, and understates it in both the model
    and the measurement, so the cost cross-check cannot see it.
    """
    a = scene("M1", PARK, DayNight.DAY, 8, ("SARAH",)).to_work_item()
    b = scene("M2", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item()
    c = scene("M3", PARK, DayNight.DAY, 8, ("SARAH",)).to_work_item()
    board = solve(ScheduleProblem(
        problem_id="MOVES", production_calendar=ProductionCalendar((D1, D2)),
        work_items=(a, b, c),
        constraints=ConstraintSet((
            _pin("P1", "W-M1", D1), _pin("P2", "W-M2", D1), _pin("P3", "W-M3", D2),
        )),
        roster=ROSTER, locations=PLACES,
    )).board

    first, second = board.days
    if first.location_ids[-1] != second.location_ids[0]:
        assert board.objective_breakdown.company_moves == 2, (
            f"day one wraps at {first.location_ids[-1]} and day two calls at "
            f"{second.location_ids[0]}; that relocation must be counted"
        )
    else:
        # The solver may instead order day one to wrap where day two calls, which is
        # a genuine one-move board rather than an undercounted two-move one.
        assert board.objective_breakdown.company_moves == 1


@pytest.mark.req("CST-007")
def test_minimum_rest_is_compiled_rather_than_only_caught_after_the_fact():
    """A night wrap at 00:06 followed by a sunrise call is six and a half hours' rest.

    The validator catches it, which is why no bad board ships. But catching it there
    yields no board *and* a diagnosis blaming a miscompiled model, when the model
    simply never represented the bound. The solver should either place the work
    legally or report the rest constraint as the reason it cannot.
    """
    night = scene("R1", STUDIO, DayNight.NIGHT, 40, ("SARAH",), IntExt.INT).to_work_item()
    day = scene("R2", PARK, DayNight.DAY, 16, ("SARAH",)).to_work_item()
    rest = human("C-REST", Family.TURNAROUND, Subject(SubjectKind.SCHEDULE), MinimumRest(12.0))
    result = solve(ScheduleProblem(
        problem_id="REST", production_calendar=ProductionCalendar((D1, D2)),
        work_items=(night, day),
        constraints=ConstraintSet((rest, _pin("P1", "W-R1", D1), _pin("P2", "W-R2", D2))),
        roster=ROSTER, locations=PLACES,
    ))
    assert result.status is not SolverStatus.ERROR, (
        "a bound the model never represented is not a miscompile: " + str(result.diagnostics)
    )
    assert result.status is SolverStatus.INFEASIBLE
    assert "C-REST" in result.conflict_set.constraint_ids


@pytest.mark.req("CST-007")
def test_minimum_rest_is_satisfiable_when_the_solver_is_free_to_order_the_days():
    night = scene("R1", STUDIO, DayNight.NIGHT, 40, ("SARAH",), IntExt.INT).to_work_item()
    day = scene("R2", PARK, DayNight.DAY, 16, ("SARAH",)).to_work_item()
    rest = human("C-REST", Family.TURNAROUND, Subject(SubjectKind.SCHEDULE), MinimumRest(12.0))
    board = solve(ScheduleProblem(
        problem_id="RESTOK", production_calendar=ProductionCalendar((D1, D2)),
        work_items=(night, day), constraints=ConstraintSet((rest,)),
        roster=ROSTER, locations=PLACES,
    )).board
    gap = board.days[1].call_time - board.days[0].wrap_time
    assert gap >= dt.timedelta(hours=12)


# ==============================================================================
# Second review round: calendar arithmetic, sequence-aware daylight, cast hours,
# and twilight. Each of these passed the suite while being wrong.
# ==============================================================================


DARK_DAY_CALENDAR = (dt.date(2026, 9, 14), dt.date(2026, 9, 16))
DECEMBER = (dt.date(2026, 12, 14),)


@pytest.mark.req("SOL-010")
def test_a_calendar_with_a_dark_day_schedules():
    """A production calendar skips dark days, weekends and holds.

    Treating a day's position in the calendar as its distance from the first day puts
    every clock time on the wrong date the moment a day is missed.
    """
    a = scene("G1", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item()
    b = scene("G2", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item()
    result = solve(ScheduleProblem(
        problem_id="DARK", production_calendar=ProductionCalendar(DARK_DAY_CALENDAR),
        work_items=(a, b),
        constraints=ConstraintSet((
            _pin("P1", "W-G1", DARK_DAY_CALENDAR[0]), _pin("P2", "W-G2", DARK_DAY_CALENDAR[1]),
        )),
        roster=ROSTER, locations=PLACES,
    ))
    assert result.status is not SolverStatus.ERROR, result.diagnostics
    board = result.board
    for a_ in board.assignments:
        assert a_.planned_call_time.date() == a_.shoot_day, (
            "call time landed on a different date than the strip it belongs to"
        )


@pytest.mark.req("CST-004")
def test_a_performer_held_across_a_dark_day_is_paid_for_it():
    """Holding is counted in calendar days, matching `Engagement.held_days`.

    Counting shoot-day positions instead prices the hold as though the dark day did
    not exist, and the model then disagrees with the cost measured off the board.
    """
    a = scene("G1", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item()
    b = scene("G2", STUDIO, DayNight.DAY, 8, ("SARAH",), IntExt.INT).to_work_item()
    board = solve(ScheduleProblem(
        problem_id="HOLDDARK", production_calendar=ProductionCalendar(DARK_DAY_CALENDAR),
        work_items=(a, b),
        constraints=ConstraintSet((
            _pin("P1", "W-G1", DARK_DAY_CALENDAR[0]), _pin("P2", "W-G2", DARK_DAY_CALENDAR[1]),
        )),
        roster=ROSTER, locations=PLACES,
    )).board
    assert board.objective_breakdown.holding_days == 1, (
        "Sarah works the 14th and the 16th, so she is held through the 15th"
    )


@pytest.mark.req("DAY-009")
def test_daylight_bounds_where_the_work_actually_falls_in_the_day():
    """A short December window, an exterior scene, and a long interior one.

    Bounding the aggregate daylight load says nothing about *when* in the day that
    load happens: an exterior scene queued behind a seven-hour interior wraps well
    after sunset while the aggregate still fits.
    """
    interior = scene("D1", STUDIO, DayNight.DAY, 54, ("SARAH",), IntExt.INT).to_work_item()
    exterior = scene("D2", PARK, DayNight.DAY, 16, ("SARAH",)).to_work_item()
    problem = ScheduleProblem(
        problem_id="DEC", production_calendar=ProductionCalendar(DECEMBER),
        work_items=(interior, exterior), constraints=ConstraintSet(()),
        roster=ROSTER, locations=PLACES,
    )
    result = solve(problem)
    assert result.status is not SolverStatus.ERROR, result.diagnostics
    board = result.board

    window = daylight_window(PARK, DECEMBER[0])
    placed = {a.work_id: a for a in board.assignments}
    assert placed["W-D2"].planned_wrap_time <= window.sunset, (
        "the exterior scene must finish before sunset"
    )
    assert placed["W-D2"].sequence < placed["W-D1"].sequence, (
        "sun-bound work leads the day, which is the assumption the bound is modelled on"
    )
    # And the interior work is free to run past sunset, which is the whole point of
    # bounding the daylight prefix rather than the whole day.
    assert placed["W-D1"].planned_wrap_time > window.sunset


@pytest.mark.req("CST-010")
def test_a_cast_hour_limit_counts_time_on_set_not_minutes_of_camera():
    """Two two-hour scenes at two locations is four hours of work and five on set.

    A performer waiting through a company move is still at work. The solver and the
    validator have to mean the same thing by "a working day" or the model proves a
    board the validator then rejects.
    """
    here = scene("H1", PARK, DayNight.DAY, 16, ("SARAH",)).to_work_item()
    there = scene("H2", STUDIO, DayNight.DAY, 16, ("SARAH",), IntExt.INT).to_work_item()
    limit = human(
        "C-MINOR", Family.CAST, Subject(SubjectKind.CAST, "SARAH"), MaximumDailyHours(4.5)
    )
    result = solve(ScheduleProblem(
        problem_id="MINOR", production_calendar=ProductionCalendar((D1,)),
        work_items=(here, there), constraints=ConstraintSet((limit,)),
        roster=ROSTER, locations=PLACES,
    ))
    assert result.status is not SolverStatus.ERROR, result.diagnostics
    assert result.status is SolverStatus.INFEASIBLE
    assert "C-MINOR" in result.conflict_set.constraint_ids


@pytest.mark.req("CST-010")
def test_a_cast_hour_limit_that_time_on_set_does_meet_is_schedulable():
    here = scene("H1", PARK, DayNight.DAY, 16, ("SARAH",)).to_work_item()
    there = scene("H2", STUDIO, DayNight.DAY, 16, ("SARAH",), IntExt.INT).to_work_item()
    limit = human(
        "C-MINOR", Family.CAST, Subject(SubjectKind.CAST, "SARAH"), MaximumDailyHours(5.0)
    )
    board = solve(ScheduleProblem(
        problem_id="MINOROK", production_calendar=ProductionCalendar((D1,)),
        work_items=(here, there), constraints=ConstraintSet((limit,)),
        roster=ROSTER, locations=PLACES,
    )).board
    assert board.days[0].length <= dt.timedelta(hours=5)


@pytest.mark.req("DAY-010")
@pytest.mark.parametrize("twilight", [DayNight.DAWN, DayNight.DUSK])
def test_twilight_work_is_refused_rather_than_called_at_seven_in_the_morning(twilight):
    """Dawn and dusk are short hard windows the model does not represent.

    Scheduling them as ordinary day work is not a dawn scene; it is a dawn scene shot
    in broad daylight. Same reasoning as `WorkItem` refusing `UNKNOWN`: work carrying
    no bound gets scheduled as though it had none.
    """
    item = scene("W1", PARK, twilight, 16, ("SARAH",)).to_work_item()
    with pytest.raises(SolverError, match="twilight window"):
        ScheduleProblem(
            problem_id="TWILIGHT", production_calendar=ProductionCalendar((D1,)),
            work_items=(item,), constraints=ConstraintSet(()), roster=ROSTER, locations=PLACES,
        )


@pytest.mark.req("DAY-003")
def test_a_board_spanning_a_dst_boundary_keeps_local_call_times():
    """US daylight saving ends on 1 November 2026, mid-board.

    Each day still calls at its own local sunrise. The model counts absolute minutes
    and the board carries zone-aware times, so the two agree about the instant while
    the local clock face moves an hour — the same class of mistake that put a daylight
    window an hour out, arriving this time in the check meant to catch such mistakes.
    """
    days = (dt.date(2026, 10, 31), dt.date(2026, 11, 1), dt.date(2026, 11, 2))
    work = tuple(
        scene(f"T{i}", PARK, DayNight.DAY, 8, ("SARAH",)).to_work_item() for i in range(3)
    )
    pins = ConstraintSet(tuple(
        _pin(f"P{i}", w.work_id, d) for i, (w, d) in enumerate(zip(work, days))
    ))
    result = solve(ScheduleProblem(
        problem_id="DST", production_calendar=ProductionCalendar(days),
        work_items=work, constraints=pins, roster=ROSTER, locations=PLACES,
    ))
    assert result.status is not SolverStatus.ERROR, result.diagnostics
    board = result.board
    for day in board.days:
        expected = daylight_window(PARK, day.date).sunrise
        assert abs((day.call_time - expected).total_seconds()) < 120, (
            f"{day.date} called at {day.call_time:%H:%M %Z}, sunrise is {expected:%H:%M %Z}"
        )
    offsets = {day.call_time.utcoffset() for day in board.days}
    assert len(offsets) == 2, "the board should straddle the change, not flatten it"


@pytest.mark.req("DAY-003")
def test_a_day_spanning_the_clocks_going_back_is_measured_in_real_hours():
    """A twelve-hour night that the clocks go back inside runs twelve real hours.

    Python subtracts two aware datetimes that share a tzinfo object *naively*: the
    common zone is ignored and the wall-clock difference comes back. Every time on a
    board carries the same `Location.zone`, so a call at 17:53 EDT and a wrap at
    05:53 EST used to measure twelve hours and really ran thirteen — over the company
    day, and an hour of overtime nobody was billed for.

    The two-readings arrangement could not catch it. The compiled model and the
    independent validator both subtracted the same way and agreed with each other,
    which is the shared misconception `CLAUDE.md` warns cross-checks are blind to.
    """
    fall_back = dt.date(2026, 10, 31)   # clocks go back at 02:00 on 1 November
    ordinary = dt.date(2026, 10, 24)    # same shape, no transition
    night = scene("N1", STUDIO, DayNight.NIGHT, 96, ("SARAH",), IntExt.INT).to_work_item()
    assert night.estimated_duration_minutes == 720, "the fixture is meant to be a 12h night"

    for day in (ordinary, fall_back):
        board = solve(ScheduleProblem(
            problem_id=f"DST-{day}", production_calendar=ProductionCalendar((day,)),
            work_items=(night,), constraints=ConstraintSet(()), roster=ROSTER,
            locations=PLACES, company=Company(maximum_day_hours=12.0),
        )).board
        shoot_day = board.days[0]
        real = (
            shoot_day.wrap_time.astimezone(dt.timezone.utc)
            - shoot_day.call_time.astimezone(dt.timezone.utc)
        )
        assert real == dt.timedelta(hours=12), (
            f"{day}: called {shoot_day.call_time:%H:%M %Z}, wrapped "
            f"{shoot_day.wrap_time:%H:%M %Z}, which is {real} of real time"
        )
        assert shoot_day.length == real, "the board must report the hours it really ran"
        assert board.objective_breakdown.overtime_hours == 2.0, (
            "two hours over a ten-hour standard day, on either date"
        )

    # The transition really is inside the night, or the test proves nothing.
    spanning = solve(ScheduleProblem(
        problem_id="DST-span", production_calendar=ProductionCalendar((fall_back,)),
        work_items=(night,), constraints=ConstraintSet(()), roster=ROSTER,
        locations=PLACES,
    )).board.days[0]
    assert spanning.call_time.utcoffset() != spanning.wrap_time.utcoffset()


@pytest.mark.req("CST-007")
def test_turnaround_is_measured_in_real_hours_across_the_clocks_going_forward():
    """Spring forward is the direction that hurts: a 12h gap is 11 hours of rest.

    The performer is an hour short and every wall-clock reading says they are not.
    """
    zone = STUDIO.zone
    def at(day, hour):
        return dt.datetime(2026, 3, day, hour, tzinfo=zone)

    # Clocks go forward at 02:00 on 8 March 2026, inside this gap.
    assignments = (
        Assignment(work_id="W1", shoot_day=dt.date(2026, 3, 7), sequence=0,
                   location_id=STUDIO.id, planned_call_time=at(7, 15),
                   planned_wrap_time=at(7, 23)),
        Assignment(work_id="W2", shoot_day=dt.date(2026, 3, 8), sequence=0,
                   location_id=STUDIO.id, planned_call_time=at(8, 11),
                   planned_wrap_time=at(8, 19)),
    )
    work = tuple(
        scene(w, STUDIO, DayNight.DAY, 64, ("SARAH",), IntExt.INT).to_work_item()
        for w in ("W1", "W2")
    )
    work = tuple(dataclasses.replace(w, work_id=wid)
                 for w, wid in zip(work, ("W1", "W2")))
    rest = human("C-REST", Family.TURNAROUND, Subject(SubjectKind.SCHEDULE),
                 MinimumRest(hours=12.0), said="twelve hours turnaround")
    report = validate_board(assignments, constraints=ConstraintSet((rest,)),
                            work_items=work, locations=PLACES, roster=ROSTER)
    assert not report.passed, (
        "23:00 to 11:00 across the spring forward is eleven hours of rest, not twelve"
    )
    assert "11.00h" in report.summary(), report.summary()
