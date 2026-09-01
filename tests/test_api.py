from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
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
from coverset.api.models import Base  # type: ignore[import-not-found]
from coverset.api.services import (  # type: ignore[import-not-found]
    activate_constraint,
    create_constraint,
    create_production,
    enqueue_breakdown_job,
    enqueue_schedule_job,
    get_board,
    get_job,
    ground_fact,
    list_candidates_for_run,
    materialize_demo_script,
    run_breakdown,
    run_job,
    run_scheduler,
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
def test_async_jobs_are_enqueued_and_worker_updates_status(db_session: Session, tmp_path):
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


def test_job_enqueue_api_returns_pollable_job(db_session: Session, tmp_path, monkeypatch):
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
def test_active_lock_constraint_pins_work_item_in_schedule(db_session: Session, tmp_path):
    settings = Settings(upload_root=tmp_path, agent_mode="fixture")
    storage = ObjectStorage(settings)
    production = create_production(db_session, title="Locked Board", seed_demo_data=True)
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
