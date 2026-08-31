"""Screenplay/artifact storage abstraction.

Local development stores blobs under `.coverset-data/uploads`. Cloud Run stores them in
GCS. The database keeps only the URI and hash.
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from .config import Settings, get_settings  # type: ignore[import-not-found]


class StorageError(RuntimeError):
    pass


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _gcs_storage() -> Any:
    return cast(Any, importlib.import_module("google.cloud.storage"))


class ObjectStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def put(self, *, production_id: str, object_id: str, filename: str, content: bytes) -> str:
        key = f"productions/{production_id}/{object_id}/{filename}"
        if self.settings.upload_bucket:
            storage = _gcs_storage()
            client = storage.Client(project=self.settings.project_id)
            bucket = client.bucket(self.settings.upload_bucket)
            blob = bucket.blob(key)
            blob.upload_from_string(content)
            return f"gs://{self.settings.upload_bucket}/{key}"

        root = self.settings.upload_root
        path = root / production_id / object_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return f"file://{quote(str(path.resolve()))}"

    def get(self, uri: str) -> bytes:
        if uri.startswith("gs://"):
            bucket_name, _, key = uri.removeprefix("gs://").partition("/")
            if not bucket_name or not key:
                raise StorageError(f"invalid GCS URI: {uri}")
            storage = _gcs_storage()
            client = storage.Client(project=self.settings.project_id)
            return client.bucket(bucket_name).blob(key).download_as_bytes()
        if uri.startswith("file://"):
            return Path(uri.removeprefix("file://")).read_bytes()
        raise StorageError(f"unsupported storage URI: {uri}")
