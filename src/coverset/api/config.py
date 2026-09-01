"""Runtime configuration for the deployable API/worker.

The domain library remains environment-free; only the service boundary reads deploy
configuration. Local development defaults to SQLite and local file storage. Cloud Run
uses Cloud SQL's Unix socket, GCS, and Secret Manager-provided environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


def _load_local_env() -> None:
    explicit = os.getenv("COVERSET_ENV_FILE")
    if explicit:
        load_dotenv(explicit)
        return
    if Path(".env").exists():
        load_dotenv(".env")
        return
    load_dotenv(Path.home() / ".config" / "coverset" / "Coverset.env")


_load_local_env()


@dataclass(frozen=True)
class Settings:
    project_id: str = os.getenv("GOOGLE_CLOUD_PROJECT", "spoonepa")
    region: str = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
    environment: str = os.getenv("COVERSET_ENV", "local")
    database_url: str = os.getenv("COVERSET_DATABASE_URL", "")
    db_user: str = os.getenv("COVERSET_DB_USER", "coverset")
    db_password: str = os.getenv("COVERSET_DB_PASSWORD", "")
    db_name: str = os.getenv("COVERSET_DB_NAME", "coverset")
    cloudsql_instance: str = os.getenv("COVERSET_CLOUDSQL_INSTANCE", "")
    upload_bucket: str = os.getenv("COVERSET_UPLOAD_BUCKET", "")
    artifact_bucket: str = os.getenv("COVERSET_ARTIFACT_BUCKET", "")
    upload_root: Path = Path(os.getenv("COVERSET_UPLOAD_ROOT", ".coverset-data/uploads"))
    task_queue: str = os.getenv("COVERSET_TASK_QUEUE", "")
    worker_url: str = os.getenv("COVERSET_WORKER_URL", "")
    task_oidc_service_account: str = os.getenv("COVERSET_TASK_OIDC_SERVICE_ACCOUNT", "")
    agent_mode: str = os.getenv("COVERSET_AGENT_MODE", "gemini")
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("COVERSET_CORS_ORIGINS", "*").split(",")
        if origin.strip()
    )

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.cloudsql_instance:
            user = quote_plus(self.db_user)
            password = quote_plus(self.db_password)
            db = quote_plus(self.db_name)
            socket_path = quote_plus(f"/cloudsql/{self.cloudsql_instance}")
            return f"postgresql+psycopg://{user}:{password}@/{db}?host={socket_path}"
        return "sqlite:///./.coverset-data/coverset.db"

    @property
    def storage_backend(self) -> str:
        return "gcs" if self.upload_bucket else "local"


def get_settings() -> Settings:
    return Settings()
