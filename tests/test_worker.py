from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from coverset.api.config import Settings  # type: ignore[import-not-found]
from coverset.api.models import Base, JobModel, new_id
from coverset.api.services import (  # type: ignore[import-not-found]
    create_production,
    enqueue_breakdown_job,
    enqueue_schedule_job,
    get_board,
    materialize_demo_script,
    run_breakdown,
    run_job,
    upload_screenplay,
)
from coverset.api.storage import ObjectStorage  # type: ignore[import-not-found]
from coverset.worker.jobs import run_once


def session_fixture() -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        yield session


def test_worker_noops_when_no_job_is_queued():
    with next(session_fixture()) as session:
        assert run_once(session) == 0


def test_worker_records_unknown_job_failures():
    with next(session_fixture()) as session:
        job = JobModel(id=new_id("job"), job_type="future", target_id="thing")
        session.add(job)
        session.commit()

        assert run_once(session) == 1
        assert job.status == "failed"
        assert job.attempts == 1
        assert "unsupported job type" in job.error


def test_worker_runs_breakdown_job_with_local_storage(tmp_path):
    with next(session_fixture()) as session:
        settings = Settings(
            upload_root=tmp_path, agent_mode="fixture", enable_fixture_mode=True
        )
        storage = ObjectStorage(settings)
        production = create_production(
            session, title="Async Breakdown", seed_demo_data=True
        )
        asset = upload_screenplay(
            session,
            production_id=production.id,
            filename="the_ferry_job.txt",
            media="text",
            content=materialize_demo_script(),
            storage=storage,
        )
        job = enqueue_breakdown_job(
            session,
            production.id,
            screenplay_asset_id=asset.id,
            auto_accept_schedulable=True,
            agent_mode="fixture",
            settings=settings,
        )

        finished = run_job(session, job_id=job.id, storage=storage, settings=settings)

        assert finished.status == "complete"
        assert finished.attempts == 1
        assert finished.result_json["breakdown_run_id"].startswith("brk_")
        assert finished.result_json["status"] == "complete"
        again = run_job(session, job_id=job.id, storage=storage, settings=settings)
        assert again.attempts == 1, "completed jobs are idempotent"


def test_worker_runs_schedule_job_from_accepted_scenes(tmp_path):
    with next(session_fixture()) as session:
        settings = Settings(
            upload_root=tmp_path, agent_mode="fixture", enable_fixture_mode=True
        )
        storage = ObjectStorage(settings)
        production = create_production(
            session, title="Async Schedule", seed_demo_data=True
        )
        asset = upload_screenplay(
            session,
            production_id=production.id,
            filename="the_ferry_job.txt",
            media="text",
            content=materialize_demo_script(),
            storage=storage,
        )
        run_breakdown(
            session,
            production_id=production.id,
            screenplay_asset_id=asset.id,
            auto_accept_schedulable=True,
            agent_mode="fixture",
            storage=storage,
            settings=settings,
        )
        job = enqueue_schedule_job(session, production.id)

        assert run_once(session) == 1

        assert job.status == "complete"
        assert job.result_json["board_id"].startswith("board_")
        board = get_board(session, job.result_json["board_id"])
        assert board.solver_status == "optimal"
        assert board.result_json["strips"]
        assert board.result_json["explanation_traces"]
