from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from coverset.api.config import Settings  # type: ignore[import-not-found]
from coverset.api.db import (  # type: ignore[import-not-found]
    create_coverset_engine,
    get_session,
    run_migrations,
)
from coverset.api.main import app  # type: ignore[import-not-found]
from coverset.api.models import AuditEventModel, Base  # type: ignore[import-not-found]
from coverset.api.services import (  # type: ignore[import-not-found]
    activate_constraint,
    approve_cost,
    create_constraint,
    create_production,
    decide_monitor_finding,
    enqueue_breakdown_job,
    enqueue_monitor_job,
    enqueue_schedule_job,
    export_audit_events_to_sink,
    generate_call_sheet,
    get_board,
    get_job,
    ground_fact,
    list_audit_events,
    list_call_sheets,
    list_candidates_for_run,
    list_monitor_findings,
    list_replan_requests,
    lock_board_day,
    materialize_demo_script,
    run_breakdown,
    run_job,
    run_scheduler,
    select_board,
    upload_screenplay,
)
from coverset.api.storage import ObjectStorage  # type: ignore[import-not-found]
from coverset.grounding import SearchGrounder  # type: ignore[import-not-found]


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        yield session


def solved_board(db_session: Session, tmp_path):
    settings = Settings(upload_root=tmp_path, agent_mode="fixture")
    storage = ObjectStorage(settings)
    production = create_production(db_session, title="P3", seed_demo_data=True)
    asset = upload_screenplay(
        db_session,
        production_id=production.id,
        filename="the_ferry_job.txt",
        media="text",
        content=materialize_demo_script(),
        storage=storage,
    )
    breakdown_run = run_breakdown(
        db_session,
        production_id=production.id,
        screenplay_asset_id=asset.id,
        auto_accept_schedulable=True,
        agent_mode="fixture",
        storage=storage,
        settings=settings,
    )
    assert breakdown_run.status == "complete"
    schedule_run = run_scheduler(db_session, production_id=production.id)
    assert schedule_run.status == "optimal"
    assert schedule_run.board_id is not None
    return production, get_board(db_session, schedule_run.board_id)


@pytest.mark.req("BRK-001", "BRK-004", "BRK-013", "SOL-001", "SOL-007")
def test_service_runs_screenplay_to_persisted_board(db_session: Session, tmp_path):
    settings = Settings(upload_root=tmp_path, agent_mode="fixture")
    storage = ObjectStorage(settings)
    production = create_production(
        db_session, title="The Ferry Job", seed_demo_data=True
    )
    asset = upload_screenplay(
        db_session,
        production_id=production.id,
        filename="the_ferry_job.txt",
        media="text",
        content=materialize_demo_script(),
        storage=storage,
    )

    breakdown_run = run_breakdown(
        db_session,
        production_id=production.id,
        screenplay_asset_id=asset.id,
        auto_accept_schedulable=True,
        agent_mode="fixture",
        storage=storage,
        settings=settings,
    )
    assert breakdown_run.status == "complete"
    assert breakdown_run.unresolved_cast == []
    assert breakdown_run.unresolved_locations == []

    schedule_run = run_scheduler(db_session, production_id=production.id)
    assert schedule_run.status == "optimal"
    assert schedule_run.board_id is not None
    board = get_board(db_session, schedule_run.board_id)
    assert "STRIPBOARD" in board.stripboard
    assert "Maya's Apartment" in board.stripboard
    assert board.result_json["shoot_day_count"] == 2


def test_health_alias_is_available():
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 200, response.text
    assert response.json()["storage_backend"] in {"local", "gcs"}


@pytest.mark.req("BRK-001", "SOL-001")
def test_demo_endpoint_runs_the_vertical_slice(db_session: Session):
    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        response = client.post("/demo/run")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["solver_status"] == "optimal"
    assert "STRIPBOARD" in payload["stripboard"]


def test_migrations_create_expected_tables_and_are_idempotent(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'coverset.db'}")

    run_migrations(settings)
    run_migrations(settings)

    engine = create_coverset_engine(settings)
    inspector = inspect(engine)
    assert {
        "productions",
        "cast_members",
        "locations",
        "shoot_days",
        "scene_candidates",
        "locked_days",
        "monitor_findings",
        "replan_requests",
        "board_selections",
        "cost_approvals",
        "audit_events",
    }.issubset(set(inspector.get_table_names()))
    columns = {column["name"] for column in inspector.get_columns("scene_candidates")}
    assert "proposal_scene_json" in columns


@pytest.mark.req("BRK-001", "BRK-004", "BRK-013", "SOL-001")
def test_production_setup_api_builds_scheduler_ready_state(
    db_session: Session, tmp_path
):
    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        created = client.post(
            "/productions", json={"title": "Custom Ferry", "seed_demo_data": False}
        )
        assert created.status_code == 200, created.text
        production_id = created.json()["id"]
        assert created.json()["cast_count"] == 0
        assert created.json()["location_count"] == 0

        cast_rows = [
            ("cast-maya", "A. Idowu", "MAYA", False),
            ("cast-dev", "B. Whitfield", "DEV", False),
            ("cast-ruth", "C. Okonkwo", "RUTH", False),
            ("cast-kid", "D. Alvarez", "KID", True),
        ]
        for cast_id, performer, character, is_minor in cast_rows:
            response = client.post(
                f"/productions/{production_id}/cast",
                json={
                    "cast_id": cast_id,
                    "performer": performer,
                    "character": character,
                    "is_minor": is_minor,
                },
            )
            assert response.status_code == 200, response.text
        duplicate = client.post(
            f"/productions/{production_id}/cast",
            json={
                "cast_id": "cast-maya",
                "performer": "Duplicate",
                "character": "MAYA",
            },
        )
        assert duplicate.status_code == 409

        locations = [
            {
                "location_id": "maya-s-apartment",
                "name": "Maya's Apartment",
                "city": "Brooklyn",
                "state": "NY",
                "latitude": 40.7,
                "longitude": -73.99,
            },
            {
                "location_id": "brooklyn-bridge-park",
                "name": "Brooklyn Bridge Park",
                "city": "Brooklyn",
                "state": "NY",
                "latitude": 40.7002,
                "longitude": -73.9967,
            },
            {
                "location_id": "warehouse",
                "name": "Warehouse",
                "city": "Queens",
                "state": "NY",
                "latitude": 40.742,
                "longitude": -73.938,
            },
            {
                "location_id": "ferry-terminal",
                "name": "Ferry Terminal",
                "city": "Manhattan",
                "state": "NY",
                "latitude": 40.701,
                "longitude": -74.013,
                "aliases": ["FERRY TERMINAL / RIVER DOCK"],
            },
        ]
        for payload in locations:
            response = client.post(
                f"/productions/{production_id}/locations", json=payload
            )
            assert response.status_code == 200, response.text
        invalid = client.post(
            f"/productions/{production_id}/locations",
            json={
                "location_id": "bad",
                "name": "Bad",
                "city": "Nowhere",
                "state": "NA",
                "latitude": 100,
            },
        )
        assert invalid.status_code == 400

        calendar = client.put(
            f"/productions/{production_id}/calendar",
            json={"shoot_dates": ["2026-10-01", "2026-10-02"]},
        )
        assert calendar.status_code == 200, calendar.text
        assert calendar.json()["shoot_dates"] == ["2026-10-01", "2026-10-02"]
    finally:
        app.dependency_overrides.clear()

    settings = Settings(upload_root=tmp_path, agent_mode="fixture")
    storage = ObjectStorage(settings)
    asset = upload_screenplay(
        db_session,
        production_id=production_id,
        filename="the_ferry_job.txt",
        media="text",
        content=materialize_demo_script(),
        storage=storage,
    )
    breakdown_run = run_breakdown(
        db_session,
        production_id=production_id,
        screenplay_asset_id=asset.id,
        auto_accept_schedulable=True,
        agent_mode="fixture",
        storage=storage,
        settings=settings,
    )
    assert breakdown_run.status == "complete"
    schedule_run = run_scheduler(db_session, production_id=production_id)
    assert schedule_run.status == "optimal"
    assert schedule_run.board_id is not None
    board = get_board(db_session, schedule_run.board_id)
    assert board.result_json["days"][0]["date"] == "2026-10-01"


@pytest.mark.req("BRK-004", "BRK-013")
def test_screenplay_upload_records_normalized_text_and_pdf_errors(
    db_session: Session, tmp_path
):
    settings = Settings(upload_root=tmp_path, agent_mode="fixture")
    storage = ObjectStorage(settings)
    production = create_production(db_session, title="Assets", seed_demo_data=True)

    text_asset = upload_screenplay(
        db_session,
        production_id=production.id,
        filename="script.txt",
        media="text",
        content=b"INT. ROOM - DAY\r\nAction.\r\n",
        storage=storage,
    )
    assert text_asset.normalized_text_uri is not None
    assert text_asset.extraction_error == ""
    assert text_asset.extraction_metadata["strategy"] == "utf-8"
    assert storage.get(text_asset.normalized_text_uri) == b"INT. ROOM - DAY\nAction.\n"

    pdf_asset = upload_screenplay(
        db_session,
        production_id=production.id,
        filename="broken.pdf",
        media="pdf",
        content=b"not a pdf",
        storage=storage,
    )
    assert pdf_asset.normalized_text_uri is None
    assert pdf_asset.extraction_error
    failed = run_breakdown(
        db_session,
        production_id=production.id,
        screenplay_asset_id=pdf_asset.id,
        agent_mode="fixture",
        storage=storage,
        settings=settings,
    )
    assert failed.status == "failed"
    assert "screenplay extraction failed" in failed.error


def test_candidate_edit_clears_blockers_before_explicit_accept(
    db_session: Session, tmp_path
):
    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        created = client.post(
            "/productions", json={"title": "Review", "seed_demo_data": False}
        )
        production_id = created.json()["id"]
        assert (
            client.post(
                f"/productions/{production_id}/cast",
                json={"cast_id": "cast-maya", "performer": "A", "character": "MAYA"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/productions/{production_id}/locations",
                json={
                    "location_id": "maya-s-apartment",
                    "name": "Maya's Apartment",
                    "city": "Brooklyn",
                    "state": "NY",
                },
            ).status_code
            == 200
        )

        settings = Settings(upload_root=tmp_path, agent_mode="fixture")
        storage = ObjectStorage(settings)
        asset = upload_screenplay(
            db_session,
            production_id=production_id,
            filename="the_ferry_job.txt",
            media="text",
            content=materialize_demo_script(),
            storage=storage,
        )
        breakdown_run = run_breakdown(
            db_session,
            production_id=production_id,
            screenplay_asset_id=asset.id,
            auto_accept_schedulable=False,
            agent_mode="fixture",
            storage=storage,
            settings=settings,
        )
        first = list_candidates_for_run(db_session, breakdown_run.id)[0]
        blocked = client.patch(
            f"/scene-candidates/{first.id}/review", json={"decision": "accept"}
        )
        assert blocked.status_code == 400
        assert "unresolved cast cue: DEV" in blocked.text

        assert (
            client.post(
                f"/productions/{production_id}/cast",
                json={"cast_id": "cast-dev", "performer": "B", "character": "DEV"},
            ).status_code
            == 200
        )
        edited = client.patch(
            f"/scene-candidates/{first.id}",
            json={"cast_ids": ["cast-maya", "cast-dev"]},
        )
        assert edited.status_code == 200, edited.text
        edited_payload = edited.json()
        assert edited_payload["schedulable"] is True
        assert edited_payload["proposal_scene"]["cast_ids"] == ["cast-maya"]
        assert edited_payload["cast_ids"] == ["cast-maya", "cast-dev"]

        accepted = client.patch(
            f"/scene-candidates/{first.id}/review", json={"decision": "accept"}
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["accepted"] is True

        batch = client.post(f"/breakdowns/{breakdown_run.id}/candidates/batch-accept")
        assert batch.status_code == 200, batch.text
        assert first.id in batch.json()["accepted"]
        assert any(batch.json()["skipped"].values())
    finally:
        app.dependency_overrides.clear()


@pytest.mark.req("BRK-001", "SOL-001")
def test_async_jobs_are_enqueued_and_worker_updates_status(
    db_session: Session, tmp_path
):
    settings = Settings(upload_root=tmp_path, agent_mode="fixture")
    storage = ObjectStorage(settings)
    production = create_production(db_session, title="Async Jobs", seed_demo_data=True)
    asset = upload_screenplay(
        db_session,
        production_id=production.id,
        filename="the_ferry_job.txt",
        media="text",
        content=materialize_demo_script(),
        storage=storage,
    )

    breakdown_job = enqueue_breakdown_job(
        db_session,
        production.id,
        screenplay_asset_id=asset.id,
        auto_accept_schedulable=True,
        agent_mode="fixture",
    )
    assert breakdown_job.status == "queued"
    completed_breakdown = run_job(
        db_session,
        job_id=breakdown_job.id,
        storage=storage,
        settings=settings,
    )
    assert completed_breakdown.status == "complete"
    assert get_job(db_session, breakdown_job.id).attempts == 1

    schedule_job = enqueue_schedule_job(db_session, production.id)
    completed_schedule = run_job(db_session, job_id=schedule_job.id)
    assert completed_schedule.status == "complete"
    board = get_board(db_session, completed_schedule.result_json["board_id"])
    assert board.result_json["strips"]
    assert board.result_json["explanation_traces"]

    rerun = run_job(db_session, job_id=schedule_job.id)
    assert rerun.attempts == 1


def test_job_enqueue_api_returns_pollable_job(
    db_session: Session, tmp_path, monkeypatch
):
    import coverset.api.main as api_main  # type: ignore[import-not-found]

    monkeypatch.setattr(api_main, "settings", Settings(task_queue="", worker_url=""))

    def override_session() -> Iterator[Session]:
        yield db_session

    settings = Settings(upload_root=tmp_path, agent_mode="fixture")
    storage = ObjectStorage(settings)
    production = create_production(db_session, title="Job API", seed_demo_data=True)
    asset = upload_screenplay(
        db_session,
        production_id=production.id,
        filename="the_ferry_job.txt",
        media="text",
        content=materialize_demo_script(),
        storage=storage,
    )

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        queued = client.post(
            f"/productions/{production.id}/breakdowns/jobs",
            json={
                "screenplay_asset_id": asset.id,
                "auto_accept_schedulable": True,
                "agent_mode": "fixture",
            },
        )
        assert queued.status_code == 200, queued.text
        payload = queued.json()
        assert payload["status"] == "queued"
        assert payload["job_type"] == "breakdown"

        polled = client.get(f"/jobs/{payload['id']}")
        assert polled.status_code == 200, polled.text
        assert polled.json()["id"] == payload["id"]

        history = client.get(f"/productions/{production.id}/jobs")
        assert history.status_code == 200, history.text
        assert [job["id"] for job in history.json()] == [payload["id"]]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.req("CON-008")
def test_grounding_evidence_creates_inactive_constraint_until_activated(
    db_session: Session, parallel_stub
):
    target_date = dt.date(2026, 3, 17)
    production = create_production(db_session, title="Grounding", seed_demo_data=True)
    client, recorder = parallel_stub()

    evidence = ground_fact(
        db_session,
        production.id,
        kind="weather",
        location_id="brooklyn-bridge-park",
        target_date=target_date,
        grounder=SearchGrounder(client),
    )

    assert evidence.status == "complete"
    assert "/v1/search" in recorder.paths()
    assert evidence.evidence_json["covering_urls"]

    constraint = create_constraint(
        db_session,
        production.id,
        payload={
            "constraint_id": "WX-BROOKLYN-RAIN",
            "family": "weather",
            "policy": "hard",
            "subject_kind": "location",
            "subject_ref": "brooklyn-bridge-park",
            "expression_type": "blackout_dates",
            "dates": [target_date],
            "evidence_id": evidence.id,
            "active": False,
        },
    )

    assert constraint.active is False
    assert constraint.provenance_json["type"] == "grounded"
    assert constraint.provenance_json["evidence_id"] == evidence.id

    activated = activate_constraint(
        db_session, constraint_row_id=constraint.id, active=True
    )
    assert activated.active is True
    assert activated.constraint_json["active"] is True


@pytest.mark.req("SOL-001", "SOL-007")
def test_active_lock_constraint_pins_work_item_in_schedule(
    db_session: Session, tmp_path
):
    settings = Settings(upload_root=tmp_path, agent_mode="fixture")
    storage = ObjectStorage(settings)
    production = create_production(
        db_session, title="Locked Board", seed_demo_data=True
    )
    asset = upload_screenplay(
        db_session,
        production_id=production.id,
        filename="the_ferry_job.txt",
        media="text",
        content=materialize_demo_script(),
        storage=storage,
    )
    breakdown_run = run_breakdown(
        db_session,
        production_id=production.id,
        screenplay_asset_id=asset.id,
        auto_accept_schedulable=True,
        agent_mode="fixture",
        storage=storage,
        settings=settings,
    )
    assert breakdown_run.status == "complete"

    create_constraint(
        db_session,
        production.id,
        payload={
            "constraint_id": "LOCK-W-BRK-001",
            "family": "lock",
            "policy": "hard",
            "subject_kind": "work",
            "subject_ref": "W-BRK-001",
            "expression_type": "pinned_day",
            "day": dt.date(2026, 9, 14),
            "statement": "First AD locked scene 1 to day 1.",
            "active": True,
        },
    )

    schedule_run = run_scheduler(db_session, production_id=production.id)
    assert schedule_run.status == "optimal"
    assert schedule_run.board_id is not None
    board = get_board(db_session, schedule_run.board_id)
    strips = {strip["work_id"]: strip for strip in board.result_json["strips"]}
    assert strips["W-BRK-001"]["shoot_day"] == "2026-09-14"
    assert any(
        trace["constraint_id"] == "LOCK-W-BRK-001" and trace["source"]
        for trace in board.result_json["explanation_traces"]
    )


@pytest.mark.req("LCK-001", "LCK-002", "SOL-004", "SOL-012")
def test_locked_day_records_compile_into_replans(db_session: Session, tmp_path):
    production, board = solved_board(db_session, tmp_path)
    locked_date = dt.date.fromisoformat(board.result_json["days"][0]["date"])

    lock = lock_board_day(
        db_session,
        board_id=board.id,
        shoot_date=locked_date,
        call_sheet_version="CS-001",
        actor_name="J. Alvarez",
        actor_role="script_supervisor",
    )

    assert lock.locked_assignments_json[0]["work_id"]
    rerun = run_scheduler(db_session, production_id=production.id)
    assert rerun.status == "optimal"
    assert rerun.board_id is not None
    replanned = get_board(db_session, rerun.board_id)
    assert any(
        trace["family"] == "lock" and trace["satisfied"] is True
        for trace in replanned.result_json["explanation_traces"]
    )
    audit_rows = db_session.scalars(
        sa.select(AuditEventModel).where(AuditEventModel.event_type == "day.locked")
    ).all()
    assert audit_rows[-1].actor.startswith("J. Alvarez")


@pytest.mark.req("MON-001", "MON-005", "MON-006", "MON-007", "MON-008", "ACT-007")
def test_monitor_job_creates_finding_and_human_acceptance_requests_replan(
    db_session: Session, tmp_path
):
    production, board = solved_board(db_session, tmp_path)
    work_id = board.result_json["strips"][0]["work_id"]
    job = enqueue_monitor_job(
        db_session,
        production.id,
        payload={
            "board_id": board.id,
            "source_url": "https://film.example.gov/permits",
            "fact_kind": "permit",
            "old_fingerprint": "old",
            "new_fingerprint": "new",
            "old_value": {"hours": "07:00-22:00"},
            "new_value": {"hours": "08:00-20:00"},
            "affected_work_ids": [work_id],
            "material": True,
            "message": "permit window changed",
        },
    )

    processed = run_job(db_session, job_id=job.id)

    assert processed.status == "complete"
    finding = list_monitor_findings(db_session, production.id)[0]
    assert finding.status == "open"
    replans = list_replan_requests(db_session, production.id)
    assert len(replans) == 1
    replan = replans[0]

    _, accepted_replan = decide_monitor_finding(
        db_session,
        finding_id=finding.id,
        decision="accept",
        actor_name="R. Okonkwo",
        actor_role="first_ad",
    )

    assert accepted_replan is not None
    assert accepted_replan.id == replan.id
    assert replan.current_board_id == board.id
    assert replan.affected_work_ids_json == [work_id]
    assert get_job(db_session, job.id).result_json["finding_id"] == finding.id
    assert get_job(db_session, job.id).result_json["replan_request_id"] == replan.id


@pytest.mark.req("MON-004", "ACT-007")
def test_rejected_or_non_material_findings_leave_board_unselected(
    db_session: Session, tmp_path
):
    production, board = solved_board(db_session, tmp_path)
    job = enqueue_monitor_job(
        db_session,
        production.id,
        payload={
            "board_id": board.id,
            "source_url": "https://weather.example/forecast",
            "fact_kind": "weather",
            "old_fingerprint": "same",
            "new_fingerprint": "changed",
            "material": False,
            "message": "forecast changed below materiality threshold",
        },
    )
    run_job(db_session, job_id=job.id)
    finding = list_monitor_findings(db_session, production.id)[0]

    reviewed, replan = decide_monitor_finding(
        db_session,
        finding_id=finding.id,
        decision="reject",
        actor_name="R. Okonkwo",
        actor_role="first_ad",
    )

    assert reviewed.status == "rejected"
    assert replan is None
    assert list_replan_requests(db_session, production.id) == []
    assert get_board(db_session, board.id).id == board.id


@pytest.mark.req("ACT-004", "ACT-005", "ACT-008", "ACT-009")
def test_board_selection_and_cost_approval_services_enforce_roles(
    db_session: Session, tmp_path
):
    production, board = solved_board(db_session, tmp_path)

    with pytest.raises(Exception, match="may not select board"):
        select_board(
            db_session,
            board_id=board.id,
            actor_name="A. Kowalczyk",
            actor_role="director",
        )

    selection = select_board(
        db_session,
        board_id=board.id,
        actor_name="R. Okonkwo",
        actor_role="first_ad",
    )
    approval = approve_cost(
        db_session,
        board_id=board.id,
        actor_name="L. Chen",
        actor_role="line_producer",
        cost_delta=12000,
        added_shoot_days=[dt.date(2026, 9, 16)],
    )

    assert selection.selected_board_id == board.id
    assert approval.decision == "approved"
    assert approval.added_shoot_days_json == ["2026-09-16"]


@pytest.mark.req(
    "ACT-010",
    "CST-006",
    "CST-007",
    "DAY-001",
    "DAY-003",
    "OUT-001",
    "OUT-004",
    "OUT-006",
)
def test_call_sheet_service_builds_second_ad_day_output(db_session: Session, tmp_path):
    production, board = solved_board(db_session, tmp_path)
    day_snapshot = board.result_json["days"][1]
    shoot_date = dt.date.fromisoformat(day_snapshot["date"])
    location_id = day_snapshot["strips"][0]["location_id"]
    create_constraint(
        db_session,
        production.id,
        payload={
            "constraint_id": "PERMIT-CALLSHEET",
            "family": "permit",
            "policy": "hard",
            "subject_kind": "location",
            "subject_ref": location_id,
            "expression_type": "date_windows",
            "windows": [{"start": shoot_date, "end": shoot_date}],
            "statement": "Permit allows this location on the shoot day.",
            "actor_name": "R. Okonkwo",
            "actor_role": "first_ad",
            "active": True,
        },
    )

    sheet = generate_call_sheet(
        db_session,
        board_id=board.id,
        shoot_date=shoot_date,
        actor_name="T. Nguyen",
        actor_role="second_ad",
    )

    assert sheet.shoot_date == shoot_date
    assert sheet.payload_json["crew_call"] == day_snapshot["call_time"]
    assert sheet.payload_json["wrap_estimate"] == day_snapshot["wrap_time"]
    assert sheet.payload_json["scenes"][0]["location_id"] == location_id
    assert sheet.payload_json["daylight_windows"][0]["sunrise"]
    assert sheet.payload_json["turnaround_notes"][0]["subject"] == "crew"
    assert sheet.payload_json["permit_notes"][0]["constraint_id"] == "PERMIT-CALLSHEET"
    assert {row["authority"] for row in sheet.payload_json["recipients"]} == {
        "read_only"
    }
    assert "CALL SHEET" in sheet.rendered_text
    assert list_call_sheets(db_session, board.id) == [sheet]

    with pytest.raises(Exception, match="may not generate call sheet"):
        generate_call_sheet(
            db_session,
            board_id=board.id,
            shoot_date=shoot_date,
            actor_name="R. Okonkwo",
            actor_role="first_ad",
        )


@pytest.mark.req("OUT-001", "OUT-004", "OUT-006", "ACT-010")
def test_call_sheet_endpoints_generate_list_and_export(db_session: Session, tmp_path):
    _, board = solved_board(db_session, tmp_path)
    shoot_date = board.result_json["days"][0]["date"]

    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        rejected = client.post(
            f"/boards/{board.id}/call-sheets",
            json={
                "shoot_date": shoot_date,
                "actor_name": "R. Okonkwo",
                "actor_role": "first_ad",
            },
        )
        assert rejected.status_code == 403

        created = client.post(
            f"/boards/{board.id}/call-sheets",
            json={
                "shoot_date": shoot_date,
                "actor_name": "T. Nguyen",
                "actor_role": "second_ad",
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["payload"]["shoot_date"] == shoot_date
        assert body["payload"]["recipients"][0]["authority"] == "read_only"
        assert "Daylight" in body["rendered_text"]

        listed = client.get(f"/boards/{board.id}/call-sheets")
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["id"] == body["id"]

        exported_text = client.get(f"/call-sheets/{body['id']}/export?format=text")
        assert exported_text.status_code == 200, exported_text.text
        assert "CALL SHEET" in exported_text.text
        assert "read_only" in exported_text.text

        exported_json = client.get(f"/call-sheets/{body['id']}/export?format=json")
        assert exported_json.status_code == 200, exported_json.text
        assert exported_json.json()["id"] == body["id"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.req("ACT-004", "ACT-007", "ACT-008", "LCK-001", "MON-007")
def test_p3_authority_and_replan_endpoints(db_session: Session, tmp_path):
    production, board = solved_board(db_session, tmp_path)
    shoot_day = board.result_json["days"][0]["date"]
    work_id = board.result_json["strips"][0]["work_id"]

    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        locked = client.post(
            f"/boards/{board.id}/locks",
            json={
                "shoot_date": shoot_day,
                "call_sheet_version": "CS-001",
                "actor_name": "J. Alvarez",
                "actor_role": "script_supervisor",
            },
        )
        assert locked.status_code == 200, locked.text
        assert locked.json()["locked_assignments"][0]["work_id"]

        monitor_job = client.post(
            f"/productions/{production.id}/monitor/jobs",
            json={
                "board_id": board.id,
                "source_url": "https://film.example.gov/permits",
                "fact_kind": "permit",
                "old_fingerprint": "old",
                "new_fingerprint": "new",
                "affected_work_ids": [work_id],
                "material": True,
                "message": "permit window changed",
            },
        )
        assert monitor_job.status_code == 200, monitor_job.text
        run_job(db_session, job_id=monitor_job.json()["id"])

        findings = client.get(f"/productions/{production.id}/monitor/findings")
        assert findings.status_code == 200, findings.text
        finding_id = findings.json()[0]["id"]
        decided = client.patch(
            f"/monitor/findings/{finding_id}",
            json={
                "decision": "accept",
                "actor_name": "R. Okonkwo",
                "actor_role": "first_ad",
            },
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["replan_request"]["current_board_id"] == board.id

        rejected_selection = client.post(
            f"/boards/{board.id}/selection",
            json={"actor_name": "A. Kowalczyk", "actor_role": "director"},
        )
        assert rejected_selection.status_code == 403
        selected = client.post(
            f"/boards/{board.id}/selection",
            json={"actor_name": "R. Okonkwo", "actor_role": "first_ad"},
        )
        assert selected.status_code == 200, selected.text

        rejected_cost = client.post(
            f"/boards/{board.id}/cost-approvals",
            json={
                "actor_name": "R. Okonkwo",
                "actor_role": "first_ad",
                "cost_delta": 1000,
                "added_shoot_days": ["2026-09-16"],
            },
        )
        assert rejected_cost.status_code == 403
        approved_cost = client.post(
            f"/boards/{board.id}/cost-approvals",
            json={
                "actor_name": "L. Chen",
                "actor_role": "line_producer",
                "cost_delta": 1000,
                "added_shoot_days": ["2026-09-16"],
            },
        )
        assert approved_cost.status_code == 200, approved_cost.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.req("OUT-003", "OUT-007", "AUD-006", "ACT-001")
def test_board_and_audit_exports_are_reviewable_and_append_only(
    db_session: Session, tmp_path
):
    production, board = solved_board(db_session, tmp_path)
    shoot_day = dt.date.fromisoformat(board.result_json["days"][0]["date"])
    lock_board_day(
        db_session,
        board_id=board.id,
        shoot_date=shoot_day,
        call_sheet_version="CS-EXPORT",
        actor_name="J. Alvarez",
        actor_role="script_supervisor",
    )
    before_exports = list_audit_events(db_session, production.id)

    class MemorySink:
        def __init__(self) -> None:
            self.rows: list[dict] = []

        def append_rows(self, rows: list[dict]) -> int:
            self.rows.extend(rows)
            return len(rows)

    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        text_export = client.get(f"/boards/{board.id}/export?format=text")
        assert text_export.status_code == 200, text_export.text
        assert "STRIPBOARD" in text_export.text
        assert text_export.headers["content-disposition"].endswith('-stripboard.txt"')

        csv_export = client.get(f"/boards/{board.id}/export?format=csv")
        assert csv_export.status_code == 200, csv_export.text
        assert "work_id,scene_id" in csv_export.text
        assert "W-BRK-001" in csv_export.text

        json_export = client.get(f"/boards/{board.id}/export?format=json")
        assert json_export.status_code == 200, json_export.text
        assert json_export.json()["id"] == board.id

        audit_json = client.get(
            f"/productions/{production.id}/audit/export?format=json"
        )
        assert audit_json.status_code == 200, audit_json.text
        assert any(row["event_type"] == "day.locked" for row in audit_json.json())

        audit_csv = client.get(f"/productions/{production.id}/audit/export?format=csv")
        assert audit_csv.status_code == 200, audit_csv.text
        assert "event_type,actor" in audit_csv.text
        assert "day.locked" in audit_csv.text
    finally:
        app.dependency_overrides.clear()

    after_exports = list_audit_events(db_session, production.id)
    assert [row.id for row in after_exports] == [row.id for row in before_exports]

    sink = MemorySink()
    exported = export_audit_events_to_sink(db_session, production.id, sink=sink)
    assert exported == len(before_exports)
    assert sink.rows[-1]["event_type"] == "day.locked"
    assert isinstance(sink.rows[-1]["payload"], str)


@pytest.mark.req("CON-001", "CON-002", "CON-003", "CON-007", "CON-009", "GRD-012", "AUD-003")
def test_completion_constraint_translation_grounded_values_and_permit_activation(
    db_session: Session, parallel_stub
):
    production = create_production(db_session, title="Completion Constraints", seed_demo_data=True)

    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        translated = client.post(
            f"/productions/{production.id}/constraints/translate",
            json={"text": "Maximum daily hours 11", "actor_name": "R. Okonkwo"},
        )
        assert translated.status_code == 200, translated.text
        proposal = translated.json()[0]
        assert proposal["status"] == "candidate"
        assert proposal["payload"]["active"] is False

        accepted = client.post(
            f"/constraint-proposals/{proposal['id']}/accept",
            json={"actor_name": "R. Okonkwo", "actor_role": "first_ad"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["active"] is True
        assert accepted.json()["constraint"]["accepted_by"]["role"] == "first_ad"

        weather_client, _ = parallel_stub()
        weather = ground_fact(
            db_session,
            production.id,
            kind="weather",
            location_id="brooklyn-bridge-park",
            target_date=dt.date(2026, 3, 17),
            grounder=SearchGrounder(weather_client),
        )
        value = client.post(
            f"/grounding/{weather.id}/values",
            json={
                "normalized_value": {"probability": 0.85},
                "units": "probability_0_1",
                "source_url": weather.evidence_json["covering_urls"][0],
                "source_quote": "Precipitation probability 85%",
                "source_span": "forecast row",
                "query": "weather forecast",
                "validator_family": "weather",
            },
        )
        assert value.status_code == 200, value.text
        assert value.json()["covering_date"] is True
        assert value.json()["source_quote"] == "Precipitation probability 85%"

        permit_url = "https://brooklyn.example.gov/film-permits"
        permit_client, _ = parallel_stub(
            search={
                "results": [
                    {
                        "url": permit_url,
                        "excerpts": ["Permit filming hours are published by the city."],
                        "title": "Film Permits",
                        "publish_date": "2026-01-01",
                    }
                ],
                "search_id": "search_permit_1",
                "session_id": "session_permit_1",
            },
            extract={
                "results": [
                    {
                        "url": permit_url,
                        "excerpts": ["Permit filming hours."],
                        "full_content": "Filming permit window is 07:00-22:00 for public locations.",
                        "title": "Film Permits",
                        "publish_date": "2026-01-01",
                    }
                ],
                "errors": [],
                "extract_id": "extract_permit_1",
                "session_id": "session_permit_1",
            },
        )
        permit = ground_fact(
            db_session,
            production.id,
            kind="permit",
            location_id="brooklyn-bridge-park",
            target_date=dt.date(2026, 9, 14),
            grounder=SearchGrounder(permit_client),
        )
        created = client.post(
            f"/productions/{production.id}/constraints",
            json={
                "constraint_id": "PERMIT-BBP-001",
                "family": "permit",
                "policy": "hard",
                "subject_kind": "location",
                "subject_ref": "brooklyn-bridge-park",
                "expression_type": "date_windows",
                "windows": [{"start": "2026-09-14", "end": "2026-09-14"}],
                "evidence_id": permit.id,
                "timezone": "America/New_York",
                "active": True,
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["constraint"]["activation_validation"]["passed"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.req("MON-001", "MON-002", "MON-003", "MON-004", "OUT-002", "OUT-005", "LCK-004")
def test_monitor_source_event_creates_replan_options_and_non_material_alerts(
    db_session: Session, tmp_path
):
    production, board = solved_board(db_session, tmp_path)
    work_id = board.result_json["strips"][0]["work_id"]

    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        registered = client.post(
            f"/productions/{production.id}/monitored-sources",
            json={
                "board_id": board.id,
                "source_url": "https://film.example.gov/permits",
                "fact_kind": "permit",
                "location_id": "brooklyn-bridge-park",
                "query": "Brooklyn film permit hours",
                "external_monitor_id": "parallel-monitor-1",
            },
        )
        assert registered.status_code == 200, registered.text

        event = client.post(
            f"/productions/{production.id}/monitor/events",
            json={
                "monitored_source_id": registered.json()["id"],
                "board_id": board.id,
                "source_url": "https://film.example.gov/permits",
                "fact_kind": "permit",
                "old_fingerprint": "old",
                "new_fingerprint": "new",
                "affected_work_ids": [work_id],
                "material": True,
                "message": "permit hours changed",
            },
        )
        assert event.status_code == 200, event.text
        assert event.json()["material"] is True
        assert event.json()["replan_request_id"]

        options = client.post(
            f"/replan-requests/{event.json()['replan_request_id']}/options",
            json={"max_options": 1},
        )
        assert options.status_code == 200, options.text
        diff = options.json()[0]
        assert diff["diff"]["base_board_id"] == board.id
        assert "required_approvals" in diff

        stale = client.post(
            f"/productions/{production.id}/monitor/events",
            json={
                "monitored_source_id": registered.json()["id"],
                "board_id": board.id,
                "source_url": "https://film.example.gov/permits",
                "fact_kind": "permit",
                "status": "stale",
            },
        )
        assert stale.status_code == 200, stale.text
        assert stale.json()["status"] == "stale"
        assert stale.json()["replan_request_id"] is None

        locked_day = dt.date.fromisoformat(board.result_json["days"][0]["date"])
        lock_board_day(
            db_session,
            board_id=board.id,
            shoot_date=locked_day,
            call_sheet_version="CS-RETRO",
            actor_name="J. Alvarez",
            actor_role="script_supervisor",
        )
        retro = client.post(
            f"/productions/{production.id}/monitor/events",
            json={
                "monitored_source_id": registered.json()["id"],
                "board_id": board.id,
                "source_url": "https://film.example.gov/permits",
                "fact_kind": "permit",
                "old_fingerprint": "new",
                "new_fingerprint": "retro",
                "target_date": locked_day.isoformat(),
                "material": True,
                "message": "past permit wording changed",
            },
        )
        assert retro.status_code == 200, retro.text
        assert retro.json()["status"] == "retroactive_exception"
        assert retro.json()["replan_request_id"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.req(
    "PIK-005",
    "PIK-006",
    "PIK-007",
    "PIK-008",
    "PIK-009",
    "PIK-010",
    "PIK-011",
    "REV-008",
    "SOL-004",
    "SOL-012",
    "LCK-003",
)
def test_pickup_workflow_requires_confirmed_spec_and_preserves_locked_days(
    db_session: Session, tmp_path
):
    production, board = solved_board(db_session, tmp_path)
    locked_day = dt.date.fromisoformat(board.result_json["days"][0]["date"])
    first_strip = next(
        strip for strip in board.result_json["strips"] if strip["shoot_day"] == locked_day.isoformat()
    )
    lock_board_day(
        db_session,
        board_id=board.id,
        shoot_date=locked_day,
        call_sheet_version="CS-LOCKED",
        actor_name="J. Alvarez",
        actor_role="script_supervisor",
    )

    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        coverage = client.post(
            f"/productions/{production.id}/coverage-items",
            json={
                "scene_id": first_strip["scene_id"],
                "coverage_key": "scene-1-insert-a",
                "coverage_type": "insert",
                "planned": {"shot": "insert"},
            },
        )
        assert coverage.status_code == 200, coverage.text
        shot = client.post(
            f"/coverage-items/{coverage.json()['id']}/shot",
            json={"shot": {"take": "A3", "usable": False}},
        )
        assert shot.status_code == 200, shot.text
        finding = client.post(
            f"/coverage-items/{coverage.json()['id']}/findings",
            json={
                "board_id": board.id,
                "message": "insert is unusable from camera shake",
                "actor_name": "S. Patel",
                "actor_role": "script_supervisor",
            },
        )
        assert finding.status_code == 200, finding.text
        pickup = client.post(
            f"/coverage-findings/{finding.json()['id']}/pickup",
            json={"actor_name": "A. Kowalczyk", "actor_role": "director"},
        )
        assert pickup.status_code == 200, pickup.text
        duplicate = client.post(
            f"/coverage-findings/{finding.json()['id']}/pickup",
            json={"actor_name": "A. Kowalczyk", "actor_role": "director"},
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["id"] == pickup.json()["id"]

        unconfirmed = client.post(
            f"/pickup-tasks/{pickup.json()['id']}/replan",
            json={
                "current_board_id": board.id,
                "cutoff_at": "2026-09-14T12:00:00-04:00",
                "lock_policy": "preserve_locked",
            },
        )
        assert unconfirmed.status_code == 400

        confirmed = client.post(
            f"/pickup-tasks/{pickup.json()['id']}/confirm",
            json={
                "actor_name": "R. Okonkwo",
                "actor_role": "first_ad",
                "pickup_spec": {
                    "scene_id": first_strip["scene_id"],
                    "coverage_type": "insert",
                    "location_id": first_strip["location_id"],
                    "cast_ids": first_strip["cast_ids"],
                    "duration_minutes": 15,
                    "priority": "must_have",
                    "day_night": first_strip["day_night"],
                },
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "schedulable"

        replan = client.post(
            f"/pickup-tasks/{pickup.json()['id']}/replan",
            json={
                "current_board_id": board.id,
                "cutoff_at": "2026-09-14T12:00:00-04:00",
                "lock_policy": "preserve_locked",
            },
        )
        assert replan.status_code == 200, replan.text
        options = client.post(
            f"/replan-requests/{replan.json()['id']}/options",
            json={"max_options": 1},
        )
        assert options.status_code == 200, options.text
        diff = options.json()[0]
        expected_pickup_work_id = f"pickup-{pickup.json()['id']}"
        assert expected_pickup_work_id in diff["diff"]["added_pickups"]
        assert "upm_or_line_producer_cost_approval" in diff["required_approvals"]
        revised = client.get(f"/boards/{diff['revised_board_id']}")
        assert revised.status_code == 200, revised.text
        assert revised.json()["approval_state"] == "pending_cost_approval"
        locked_work_ids = {
            assignment["work_id"]
            for assignment in client.get(f"/productions/{production.id}/locks").json()[0]["locked_assignments"]
        }
        locked_day_work_ids = {
            strip["work_id"]
            for strip in revised.json()["result"]["strips"]
            if strip["shoot_day"] == locked_day.isoformat()
        }
        assert locked_day_work_ids == locked_work_ids
    finally:
        app.dependency_overrides.clear()
