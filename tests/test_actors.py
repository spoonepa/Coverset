"""Tests for the authority model.

The architecture's spine is who may do what: Gemini advises, a human decides, CP-SAT
schedules. Among humans the authority is scoped, because ruling that coverage is
unusable and ruling that the production can afford another day are different
judgements belonging to different people.
"""

from __future__ import annotations

import pytest

from coverset.actors import ADVISORY_AGENTS, Actor, AuthorityError, Role

FIRST_AD = Actor("R. Okonkwo", Role.FIRST_AD)
DIRECTOR = Actor("A. Kowalczyk", Role.DIRECTOR)
SUPERVISOR = Actor("J. Alvarez", Role.SCRIPT_SUPERVISOR)
UPM = Actor("M. Haddad", Role.UPM)
SECOND_AD = Actor("T. Nguyen", Role.SECOND_AD)
EVERYONE = [FIRST_AD, DIRECTOR, SUPERVISOR, UPM, SECOND_AD]


@pytest.mark.req("ACT-001")
def test_an_actor_carries_both_a_name_and_the_role_they_act_under():
    assert FIRST_AD.name == "R. Okonkwo"
    assert FIRST_AD.role is Role.FIRST_AD
    assert str(FIRST_AD) == "R. Okonkwo (first ad)"


@pytest.mark.req("ACT-002")
def test_no_role_exists_for_an_automated_agent():
    # The guarantee is structural. Refusing agents does not depend on anticipating
    # their names, because there is no role a non-human could occupy.
    assert {r.value for r in Role} == {
        "first_ad", "director", "script_supervisor", "upm", "second_ad"
    }


@pytest.mark.req("ACT-002")
@pytest.mark.parametrize("agent", sorted(ADVISORY_AGENTS))
@pytest.mark.parametrize("role", list(Role))
def test_an_agent_name_is_refused_in_every_human_role(agent, role):
    with pytest.raises(AuthorityError, match="advisory agent"):
        Actor(agent, role)


@pytest.mark.req("ACT-001")
def test_an_unnamed_actor_is_refused():
    with pytest.raises(AuthorityError, match="must be named"):
        Actor("  ", Role.DIRECTOR)


# --------------------------------------------------------------------------
# Scoped authority
# --------------------------------------------------------------------------


@pytest.mark.req("ACT-003")
def test_ruling_on_coverage_belongs_to_the_director_and_first_ad():
    holders = {a for a in EVERYONE if a.may_rule_on_coverage}

    assert holders == {DIRECTOR, FIRST_AD}


@pytest.mark.req("ACT-004")
def test_selecting_a_board_belongs_to_the_first_ad_alone():
    # The monitor generates options; the First AD owns which one the production runs.
    holders = {a for a in EVERYONE if a.may_select_board}

    assert holders == {FIRST_AD}


@pytest.mark.req("ACT-005")
def test_approving_added_cost_belongs_to_the_upm():
    holders = {a for a in EVERYONE if a.may_approve_cost}

    assert holders == {UPM}


@pytest.mark.req("ACT-006")
def test_the_script_supervisor_may_raise_findings_but_not_rule_on_them():
    assert SUPERVISOR.may_raise_finding
    assert not SUPERVISOR.may_rule_on_coverage


@pytest.mark.req("ACT-006")
def test_locking_a_day_belongs_to_the_first_ad_and_script_supervisor():
    holders = {a for a in EVERYONE if a.may_lock_day}

    assert holders == {FIRST_AD, SUPERVISOR}


@pytest.mark.req("ACT-003")
def test_the_second_ad_holds_no_authority_over_the_schedule():
    assert not any(
        getattr(SECOND_AD, f"may_{c}")
        for c in ("rule_on_coverage", "select_board", "approve_cost", "lock_day")
    )


# --------------------------------------------------------------------------
# require()
# --------------------------------------------------------------------------


@pytest.mark.req("ACT-003")
def test_require_names_the_person_and_the_role_that_holds_the_authority():
    with pytest.raises(AuthorityError) as excinfo:
        SUPERVISOR.require("rule_on_coverage")

    message = str(excinfo.value)
    assert "J. Alvarez" in message          # who was refused
    assert "may not rule on coverage" in message
    assert "director" in message            # who could have


@pytest.mark.req("ACT-003")
def test_require_passes_silently_for_an_actor_who_holds_it():
    assert DIRECTOR.require("rule_on_coverage") is None


@pytest.mark.req("ACT-003")
def test_an_unknown_capability_is_a_programming_error_not_a_refusal():
    with pytest.raises(ValueError, match="unknown capability"):
        DIRECTOR.require("fly_the_drone")


@pytest.mark.req("ACT-010")
def test_no_role_exists_for_cast_crew_or_permit_authorities():
    # Cast and crew are recipients and constraint sources; location owners and permit
    # authorities are neither. None of them decides anything, so none can hold a Role.
    # Stated as a test because the claim was got wrong once already: "they never touch
    # the system" is false (cast receive call sheets) and hid a modelling gap.
    forbidden = {
        "cast", "performer", "actor_talent", "crew", "grip", "gaffer",
        "location_owner", "permit_authority", "vendor",
    }

    assert forbidden.isdisjoint({r.value for r in Role})


@pytest.mark.req("ACT-010")
@pytest.mark.parametrize("who", ["cast", "crew", "location_owner"])
def test_a_non_deciding_party_cannot_be_constructed_as_a_deciding_actor(who):
    # There is no role to give them, so the type system refuses before any check runs.
    with pytest.raises(ValueError, match="not a valid Role"):
        Actor(who, Role(who))
