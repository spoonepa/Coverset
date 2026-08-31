from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from coverset.api.models import Base, JobModel, new_id
from coverset.worker.jobs import run_once


def test_worker_noops_when_no_job_is_queued():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        assert run_once(session) == 0


def test_worker_records_unwired_job_failures():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        job = JobModel(id=new_id("job"), job_type="future", target_id="thing")
        session.add(job)
        session.commit()

        assert run_once(session) == 1
        assert job.status == "failed"
        assert job.attempts == 1
        assert "not wired" in job.error
