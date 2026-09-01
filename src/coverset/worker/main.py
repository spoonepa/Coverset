"""Cloud Run worker entrypoint."""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from coverset.api.config import get_settings  # type: ignore[import-not-found]
from coverset.api.db import SessionLocal, init_db  # type: ignore[import-not-found]

from .jobs import run_by_id, run_once  # type: ignore[import-not-found]

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # The API service owns Alembic startup. During Cloud Run rollouts the worker can
    # be created before the API because the API needs the worker URL for Cloud Tasks;
    # running migrations in both services races on the same Cloud SQL schema.
    yield


app = FastAPI(title="Coverset Worker", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str | bool]:
    return {
        "ok": True,
        "service": "coverset-worker",
        "environment": settings.environment,
    }


@app.get("/readyz")
def readyz() -> dict[str, str | bool]:
    return healthz()


@app.post("/jobs/run-once")
def run_once_endpoint() -> dict[str, int | bool]:
    with SessionLocal() as session:
        processed = run_once(session)
    return {"ok": True, "processed": processed}


@app.post("/jobs/{job_id}/run")
def run_job_endpoint(job_id: str) -> dict[str, object]:
    with SessionLocal() as session:
        job = run_by_id(session, job_id)
        return {
            "ok": job.status == "complete",
            "job_id": job.id,
            "status": job.status,
            "attempts": job.attempts,
            "error": job.error,
            "result": job.result_json or {},
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coverset worker utilities")
    parser.add_argument("command", choices=("run-once",))
    parser.parse_args(argv)
    init_db(use_migrations=False)
    with SessionLocal() as session:
        processed = run_once(session)
    print(f"processed={processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
