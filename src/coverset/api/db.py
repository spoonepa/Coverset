"""Database engine/session helpers for API and worker runtimes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings  # type: ignore[import-not-found]
from .models import Base  # type: ignore[import-not-found]


def create_coverset_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    url = resolved.sqlalchemy_url
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        if "///" in url and not url.endswith(":memory:"):
            db_path = Path(url.split("///", 1)[1])
            if db_path.parent != Path(""):
                db_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


_engine = create_coverset_engine()
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db(engine: Engine | None = None) -> None:
    Base.metadata.create_all(engine or _engine)


def get_session() -> Iterator[Session]:
    init_db()
    with SessionLocal() as session:
        yield session
