"""Database engine/session helpers for API and worker runtimes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

try:
    from alembic import command  # type: ignore[import-not-found]
    from alembic.config import Config  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - migrations are a runtime dependency.
    command = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment]

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
_initialized = False
_init_lock = Lock()


def init_db(
    engine: Engine | None = None, *, use_migrations: bool | None = None
) -> None:
    """Initialize the database schema once for the current process.

    Tests and ad-hoc SQLite databases use SQLAlchemy metadata directly. Long-lived
    app/worker runtimes can run Alembic head migrations and fail startup loudly when
    the migration assets or dependency are unavailable.
    """
    global _initialized
    target = engine or _engine
    if engine is not None:
        Base.metadata.create_all(target)
        return
    with _init_lock:
        if _initialized:
            return
        migrate = (
            use_migrations
            if use_migrations is not None
            else not target.url.drivername.startswith("sqlite")
        )
        if migrate:
            run_migrations()
        else:
            Base.metadata.create_all(target)
        _initialized = True


def run_migrations(settings: Settings | None = None) -> None:
    if command is None or Config is None:
        raise RuntimeError("Alembic is not installed; cannot initialize service schema")
    config_path = _alembic_config_path()
    config = Config(str(config_path))
    config.attributes["sqlalchemy_url"] = (settings or get_settings()).sqlalchemy_url
    command.upgrade(config, "head")


def _alembic_config_path() -> Path:
    candidates = (
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[3] / "alembic.ini",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "Alembic config is missing; looked for "
        + ", ".join(str(candidate) for candidate in candidates)
    )


def get_session() -> Iterator[Session]:
    init_db()
    with SessionLocal() as session:
        yield session
