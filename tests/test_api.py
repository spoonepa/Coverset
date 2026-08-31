from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from coverset.api.config import Settings  # type: ignore[import-not-found]
from coverset.api.db import get_session  # type: ignore[import-not-found]
from coverset.api.main import app  # type: ignore[import-not-found]
from coverset.api.models import Base  # type: ignore[import-not-found]
from coverset.api.services import (  # type: ignore[import-not-found]
    create_production,
    get_board,
    materialize_demo_script,
    run_breakdown,
    run_scheduler,
    upload_screenplay,
)
from coverset.api.storage import ObjectStorage  # type: ignore[import-not-found]


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
    production = create_production(db_session, title="The Ferry Job", seed_demo_data=True)
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
