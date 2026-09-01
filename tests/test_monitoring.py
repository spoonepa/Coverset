from __future__ import annotations

import pytest

from coverset.monitoring import (
    ChangeEvent,
    Materiality,
    MonitoredSource,
    ReplanRequest,
    fingerprint_value,
)


@pytest.mark.req("MON-005", "MON-006")
def test_monitored_source_and_change_event_capture_fact_fingerprints():
    source = MonitoredSource(
        id="src-1",
        schedule_version_id="sched-1",
        evidence_id="ev-1",
        url="https://film.example.gov/permits",
        fact_kind="permit",
        affected_work_ids=("W-1",),
        fingerprint=fingerprint_value({"hours": "07:00-22:00"}),
        monitor_subscription_id="sub-1",
    )
    event = ChangeEvent(
        id="chg-1",
        monitored_source_id=source.id,
        url=source.url,
        old_fingerprint=source.fingerprint,
        new_fingerprint=fingerprint_value({"hours": "08:00-20:00"}),
        old_value={"hours": "07:00-22:00"},
        new_value={"hours": "08:00-20:00"},
        materiality=Materiality(True, "permit hours changed"),
    )

    assert event.materiality.material is True
    assert event.new_fingerprint != event.old_fingerprint


@pytest.mark.req("MON-004", "MON-006")
def test_unchanged_fingerprints_cannot_be_material():
    fingerprint = fingerprint_value({"precipitation_probability": 20})

    with pytest.raises(ValueError, match="unchanged fingerprints"):
        ChangeEvent(
            id="chg-1",
            monitored_source_id="src-1",
            url="https://weather.example/forecast",
            old_fingerprint=fingerprint,
            new_fingerprint=fingerprint,
            materiality=Materiality(True, "same value"),
        )


@pytest.mark.req("ACT-007", "MON-007", "MON-008")
def test_replan_request_cannot_select_a_board():
    request = ReplanRequest(
        id="replan-1",
        production_id="prod-1",
        trigger_event_id="chg-1",
        current_board_id="board-current",
        locked_day_ids=("lock-1",),
        affected_work_ids=("W-1",),
        requester_component="monitor",
    )

    assert request.selected_board_id is None
    with pytest.raises(ValueError, match="cannot select a board"):
        ReplanRequest(
            id="replan-2",
            production_id="prod-1",
            trigger_event_id="chg-1",
            current_board_id="board-current",
            locked_day_ids=(),
            affected_work_ids=("W-1",),
            requester_component="monitor",
            selected_board_id="board-option",
        )
