"""Background job execution for Coverset.

The first deployable MVP keeps API endpoints synchronous for easy smoke testing, but
Cloud Run still deploys this worker boundary so long-running breakdown/solve work can be
moved behind job records without changing domain code.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from coverset.api.models import JobModel  # type: ignore[import-not-found]
from coverset.api.services import run_job, run_next_job  # type: ignore[import-not-found]


def run_once(session: Session) -> int:
    """Run one queued job if present."""
    return run_next_job(session)


def run_by_id(session: Session, job_id: str) -> JobModel:
    """Run one specific queued/failed job, idempotently returning completed jobs."""
    return run_job(session, job_id=job_id)
