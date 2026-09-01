"""Tests for coverage review, human decision, and pickup work.

Most of these exist to hold one boundary: Gemini flags, a human decides, and only a
human decision can put re-shoot work on the board. The boundary is cheap to state and
easy to erode, so it is tested from several directions rather than once.
"""

from __future__ import annotations

import datetime as dt

import pytest

from coverset.actors import Actor, AuthorityError, Role
from coverset.locations import Location
from coverset.review import (
    BoardSelection,
    CostApproval,
    CoverageItem,
    CoverageStatus,
    CoverageType,
    Disposition,
    InvalidTransition,
    PickupTask,
    ReviewDecision,
    ReviewError,
    ReviewFinding,
)
from coverset.work import WorkKind

CHURCH = Location(
    name="First African Baptist Church", locality="Savannah", region="Georgia"
)
DIRECTOR = Actor("A. Kowalczyk", Role.DIRECTOR)
FIRST_AD = Actor("R. Okonkwo", Role.FIRST_AD)
SUPERVISOR = Actor("J. Alvarez", Role.SCRIPT_SUPERVISOR)
SECOND_AD = Actor("T. Nguyen", Role.SECOND_AD)
UPM = Actor("M. Haddad", Role.UPM)
LINE_PRODUCER = Actor("L. Chen", Role.LINE_PRODUCER)


@pytest.fixture
def planned():
    return CoverageItem(
        id="S12-CU-01",
        scene_id="12",
        coverage_type=CoverageType.CLOSE_UP,
        location=CHURCH,
        required_cast=("SARAH", "MARCUS"),
        estimated_eighths=6,
    )


@pytest.fixture
def finding():
    return ReviewFinding(
        id="RF-001",
        coverage_item_id="S12-CU-01",
        summary="Eyeline appears inconsistent with the reverse",
        detail="Subject looks camera-left in both the close-up and the reverse.",
        confidence=0.62,
    )


@pytest.fixture
def flagged(planned, finding):
    return planned.mark_shot().flag_for_review(finding)


def _decision(disposition, by=DIRECTOR, finding_id="RF-001"):
    return ReviewDecision(
        finding_id=finding_id,
        coverage_item_id="S12-CU-01",
        disposition=disposition,
        decided_by=by,
    )


# --------------------------------------------------------------------------
# The boundary: advisory findings cannot act
# --------------------------------------------------------------------------


@pytest.mark.req("REV-001")
def test_a_finding_has_no_way_to_express_an_outcome():
    # Structural, not behavioural: there is no disposition field to set, so a
    # finding cannot carry a verdict even if a caller wanted it to.
    assert not hasattr(ReviewFinding("RF-1", "S12-CU-01", "Soft focus"), "disposition")


@pytest.mark.req("REV-001", "REV-002")
def test_flagging_can_only_move_an_item_to_needs_review(flagged, finding):
    assert flagged.status is CoverageStatus.NEEDS_REVIEW
    assert flagged.finding is finding
    assert flagged.decision is None
    assert flagged.awaits_decision


@pytest.mark.req("REV-003", "ACT-002", "AUD-004")
def test_the_role_enum_has_no_member_an_agent_could_occupy():
    # The structural guarantee: refusing agents is not a name check that has to
    # anticipate every name. There is simply no role for a non-human to hold.
    assert {r.value for r in Role} == {
        "first_ad",
        "director",
        "script_supervisor",
        "upm",
        "line_producer",
        "second_ad",
    }


@pytest.mark.req("REV-003", "ACT-002", "AUD-004")
@pytest.mark.parametrize(
    "agent", ["gemini", "Gemini", "GEMINI", "system", "ai", "bot", "coverset"]
)
def test_an_agent_name_cannot_be_given_a_human_role(agent):
    with pytest.raises(AuthorityError, match="advisory agent"):
        Actor(agent, Role.DIRECTOR)


@pytest.mark.req("REV-003", "ACT-001", "AUD-004")
def test_an_unattributed_decision_is_refused():
    with pytest.raises(AuthorityError, match="must be named"):
        Actor("   ", Role.DIRECTOR)


@pytest.mark.req("ACT-003")
@pytest.mark.parametrize("actor", [DIRECTOR, FIRST_AD])
def test_the_director_and_first_ad_may_rule_on_coverage(flagged, actor):
    item, _ = flagged.decide(_decision(Disposition.ACCEPT, by=actor))

    assert item.status is CoverageStatus.ACCEPTED


@pytest.mark.req("ACT-003", "ACT-006")
@pytest.mark.parametrize("actor", [SUPERVISOR, SECOND_AD, UPM])
def test_other_roles_may_not_rule_on_coverage(actor):
    with pytest.raises(AuthorityError, match="may not rule on coverage"):
        _decision(Disposition.REJECT, by=actor)


@pytest.mark.req("REV-001", "PIK-001")
def test_no_pickup_can_be_built_from_an_acceptance(flagged):
    accepted, _ = flagged.decide(_decision(Disposition.ACCEPT))

    with pytest.raises(ReviewError, match="does not authorise a pickup"):
        PickupTask.from_decision(accepted, _decision(Disposition.ACCEPT))


# --------------------------------------------------------------------------
# Human decisions
# --------------------------------------------------------------------------


@pytest.mark.req("REV-005")
def test_accepting_produces_no_pickup_work(flagged):
    item, pickup = flagged.decide(_decision(Disposition.ACCEPT))

    assert item.status is CoverageStatus.ACCEPTED
    assert pickup is None


@pytest.mark.req("PIK-003")
@pytest.mark.parametrize(
    ("disposition", "expected"),
    [
        (Disposition.REJECT, CoverageStatus.REJECTED),
        (Disposition.REQUEST_PICKUP, CoverageStatus.PICKUP_REQUESTED),
    ],
)
def test_rejecting_or_requesting_a_pickup_yields_exactly_one_task(
    flagged, disposition, expected
):
    item, pickup = flagged.decide(_decision(disposition))

    assert item.status is expected
    assert pickup is not None
    assert pickup.coverage_item_id == item.id


@pytest.mark.req("REV-004")
def test_a_decision_records_who_decided_and_what_it_responded_to(flagged):
    item, _ = flagged.decide(_decision(Disposition.REJECT, by=FIRST_AD))

    assert item.decision.decided_by == FIRST_AD
    assert item.decision.decided_by.role is Role.FIRST_AD
    assert item.decision.finding_id == flagged.finding.id
    assert item.decision.decided_at.tzinfo is dt.UTC


@pytest.mark.req("REV-004")
def test_a_decision_must_answer_the_finding_that_raised_the_item(flagged):
    with pytest.raises(ReviewError, match="must respond to the finding"):
        flagged.decide(_decision(Disposition.REJECT, finding_id="RF-999"))


@pytest.mark.req("REV-004")
def test_a_decision_for_another_item_is_refused(flagged):
    stray = ReviewDecision(
        finding_id="RF-001",
        coverage_item_id="S99-WIDE-01",
        disposition=Disposition.REJECT,
        decided_by=DIRECTOR,
    )

    with pytest.raises(ReviewError, match="not S12-CU-01"):
        flagged.decide(stray)


# --------------------------------------------------------------------------
# Lifecycle ordering
# --------------------------------------------------------------------------


@pytest.mark.req("REV-007")
def test_unshot_coverage_cannot_be_flagged(planned, finding):
    with pytest.raises(InvalidTransition, match="has not been shot"):
        planned.flag_for_review(finding)


@pytest.mark.req("REV-006")
def test_an_item_not_awaiting_review_cannot_be_decided(planned):
    with pytest.raises(InvalidTransition, match="nothing awaiting decision"):
        planned.mark_shot().decide(_decision(Disposition.REJECT))


@pytest.mark.req("REV-006")
def test_an_item_cannot_be_decided_twice(flagged):
    decided, _ = flagged.decide(_decision(Disposition.REJECT))

    with pytest.raises(InvalidTransition, match="nothing awaiting decision"):
        decided.decide(_decision(Disposition.ACCEPT))


@pytest.mark.req("REV-002")
def test_a_finding_about_a_different_item_is_refused(planned):
    stray = ReviewFinding(id="RF-2", coverage_item_id="S99-WIDE-01", summary="Soft")

    with pytest.raises(ReviewError, match="not S12-CU-01"):
        planned.mark_shot().flag_for_review(stray)


@pytest.mark.req("REV-006")
def test_transitions_do_not_mutate_the_original(planned, finding):
    shot = planned.mark_shot()

    assert planned.status is CoverageStatus.PLANNED
    assert shot.status is CoverageStatus.SHOT
    assert shot.flag_for_review(finding).status is CoverageStatus.NEEDS_REVIEW
    assert shot.status is CoverageStatus.SHOT


# --------------------------------------------------------------------------
# Pickup work handed to the solver
# --------------------------------------------------------------------------


@pytest.mark.req("PIK-004")
def test_a_pickup_carries_what_the_solver_needs_to_place_it(flagged):
    _, pickup = flagged.decide(_decision(Disposition.REQUEST_PICKUP))

    assert pickup.scene_id == "12"
    assert pickup.coverage_type is CoverageType.CLOSE_UP
    assert pickup.location is CHURCH
    assert pickup.required_cast == ("SARAH", "MARCUS")
    assert pickup.estimated_eighths == 6


@pytest.mark.req("PIK-002", "AUD-004")
def test_a_pickup_traces_to_the_decision_and_the_finding(flagged):
    _, pickup = flagged.decide(_decision(Disposition.REJECT, by=FIRST_AD))

    assert pickup.authorised_by == FIRST_AD
    trail = pickup.audit_trail(flagged.finding)
    assert "R. Okonkwo" in trail
    assert "RF-001" in trail
    assert "gemini" in trail
    assert "Eyeline appears inconsistent" in trail


@pytest.mark.req("PIK-001")
def test_a_pickup_and_its_authorising_decision_must_concern_the_same_item(flagged):
    _, pickup = flagged.decide(_decision(Disposition.REJECT))
    mismatched = ReviewDecision(
        finding_id="RF-001",
        coverage_item_id="S99-WIDE-01",
        disposition=Disposition.REJECT,
        decided_by=DIRECTOR,
    )

    with pytest.raises(ReviewError, match="disagree"):
        PickupTask(
            id=pickup.id,
            scene_id=pickup.scene_id,
            coverage_item_id=pickup.coverage_item_id,
            coverage_type=pickup.coverage_type,
            location=pickup.location,
            decision=mismatched,
        )


@pytest.mark.req("PIK-004")
def test_coverage_with_no_duration_is_refused():
    with pytest.raises(ValueError, match="must have a duration"):
        CoverageItem(
            id="S12-INS-01",
            scene_id="12",
            coverage_type=CoverageType.INSERT,
            location=CHURCH,
            estimated_eighths=0,
        )


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


@pytest.mark.req("REV-001", "REV-003", "PIK-002")
def test_the_full_path_from_advisory_finding_to_authorised_pickup(planned, finding):
    shot = planned.mark_shot()
    flagged = shot.flag_for_review(finding)  # Gemini: advisory only
    assert flagged.awaits_decision  # ... and it stops here

    decision = _decision(Disposition.REQUEST_PICKUP, by=FIRST_AD)
    decided, pickup = flagged.decide(decision)  # the human acts

    assert decided.status is CoverageStatus.PICKUP_REQUESTED
    assert pickup.id == "PU-S12-CU-01"
    assert pickup.decision is decision
    # Nothing between the finding and the board that a person did not sign.
    assert pickup.authorised_by == FIRST_AD


# --------------------------------------------------------------------------
# Cast resolution
# --------------------------------------------------------------------------


@pytest.mark.req("CST-002")
def test_a_coverage_item_resolves_its_cast_against_the_roster(planned):
    from coverset.people import CastMember, Roster

    roster = Roster(
        (
            CastMember(id="SARAH", name="S. Idowu", character="Ruth"),
            CastMember(id="MARCUS", name="D. Whitfield", character="Elias"),
        )
    )

    assert [m.character for m in planned.cast_on(roster)] == ["Ruth", "Elias"]


@pytest.mark.req("CST-002")
def test_a_coverage_item_naming_someone_not_on_the_roster_is_rejected(planned):
    from coverset.people import CastMember, Roster, UnknownCastMember

    roster = Roster((CastMember(id="SARAH", name="S. Idowu", character="Ruth"),))

    with pytest.raises(UnknownCastMember, match="MARCUS"):
        planned.cast_on(roster)


@pytest.mark.req("CST-002", "PIK-004")
def test_a_pickup_carries_cast_that_resolves_against_the_roster(flagged):
    from coverset.people import CastMember, Roster

    roster = Roster(
        (
            CastMember(id="SARAH", name="S. Idowu", character="Ruth"),
            CastMember(id="MARCUS", name="D. Whitfield", character="Elias"),
        )
    )
    _, pickup = flagged.decide(_decision(Disposition.REQUEST_PICKUP))

    assert pickup.cast_on(roster) == roster.resolve(("SARAH", "MARCUS"))


@pytest.mark.req("PIK-011", "AUD-004")
def test_a_pickup_converts_to_solver_work_with_authorization_trace(flagged):
    _, pickup = flagged.decide(_decision(Disposition.REQUEST_PICKUP, by=FIRST_AD))

    work = pickup.to_work_item()

    assert work.kind is WorkKind.PICKUP
    assert work.work_id == pickup.id
    assert work.source_record_id == pickup.id
    assert work.location_id == CHURCH.id
    assert work.cast_ids == ("SARAH", "MARCUS")
    assert pickup.authorised_by == FIRST_AD


@pytest.mark.req("ACT-004", "ACT-009")
def test_board_selection_is_a_first_ad_decision():
    selection = BoardSelection(
        production_id="prod-1",
        selected_board_id="board-new",
        prior_board_id="board-old",
        prior_schedule_version_id="sched-old",
        new_schedule_version_id="sched-new",
        selected_by=FIRST_AD,
    )

    assert selection.selected_by == FIRST_AD
    with pytest.raises(AuthorityError, match="may not select board"):
        BoardSelection(
            production_id="prod-1",
            selected_board_id="board-new",
            prior_board_id=None,
            prior_schedule_version_id=None,
            new_schedule_version_id="sched-new",
            selected_by=DIRECTOR,
        )


@pytest.mark.req("ACT-005", "ACT-008", "PIK-010")
def test_cost_approval_is_a_upm_or_line_producer_decision():
    CostApproval(
        production_id="prod-1",
        board_id="board-new",
        approver=UPM,
        cost_delta=12000,
        added_shoot_days=(dt.date(2026, 9, 16),),
    )
    CostApproval(
        production_id="prod-1",
        board_id="board-new",
        approver=LINE_PRODUCER,
        cost_delta=12000,
        added_shoot_days=(dt.date(2026, 9, 16),),
    )

    with pytest.raises(AuthorityError, match="may not approve cost"):
        CostApproval(
            production_id="prod-1",
            board_id="board-new",
            approver=FIRST_AD,
            cost_delta=12000,
            added_shoot_days=(dt.date(2026, 9, 16),),
        )
