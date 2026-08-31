"""Background job execution for Coverset.

The first deployable MVP keeps API endpoints synchronous for easy smoke testing, but
Cloud Run still deploys this worker boundary so long-running breakdown/solve work can be
moved behind job records without changing domain code.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from coverset.api.models import JobModel, utcnow  # type: ignore[import-not-found]


def run_once(session: Session) -> int:
    """Run one queued job if present.

    The current MVP records the worker boundary and returns cleanly when no queued jobs
    exist. This is intentionally conservative: schedule decisions still happen through
    `coverset.solver` inside the API/service layer until Cloud Tasks is wired in.
    """
    job = session.scalars(
        select(JobModel).where(JobModel.status == "queued").order_by(JobModel.created_at)
    ).first()
    if job is None:
        return 0
    job.status = "failed"
    job.attempts += 1
    job.error = f"job type {job.job_type!r} is not wired to Cloud Tasks in the MVP"
    job.updated_at = utcnow()
    session.commit()
    return 1
