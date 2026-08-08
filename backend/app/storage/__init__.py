"""Object storage: the interface, the two backends, and how one is chosen.

``get_object_store`` is the only way the application obtains a store, so which
backend is in use is a configuration question with exactly one answer per
process. The override that :func:`set_object_store` installs exists for tests —
it is what lets the API and the worker be pointed at the same in-process S3
without either of them knowing.

The cache is keyed on the settings that define a store rather than on the
settings object, because building an S3 client is not free and a request handler
must not pay for it. A ``LocalObjectStore`` would be cheap enough to rebuild; the
two are cached the same way so there is only one lifecycle to reason about.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.storage.base import (
    ObjectNotFound,
    ObjectStore,
    StorageError,
    UnusableReference,
    validate_key,
)
from app.storage.local import LocalObjectStore
from app.storage.s3 import S3ObjectStore

__all__ = [
    "LocalObjectStore",
    "ObjectNotFound",
    "ObjectStore",
    "S3ObjectStore",
    "StorageError",
    "UnusableReference",
    "get_object_store",
    "set_object_store",
    "validate_key",
]

_override: ObjectStore | None = None


def set_object_store(store: ObjectStore | None) -> None:
    """Install (or, with ``None``, remove) a process-wide store override."""

    global _override
    _override = store


def get_object_store(settings: Settings | None = None) -> ObjectStore:
    store = _override
    if store is not None:
        return store
    settings = settings or get_settings()
    return _build(
        backend=settings.storage_backend,
        upload_dir=str(settings.upload_dir),
        bucket=settings.s3_bucket,
        prefix=settings.s3_prefix,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
    )


@lru_cache
def _build(
    *,
    backend: str,
    upload_dir: str,
    bucket: str | None,
    prefix: str,
    endpoint_url: str | None,
    region: str | None,
) -> ObjectStore:
    if backend == "s3":
        # `Settings` already refuses an s3 backend with no bucket, so this is the
        # second of two guards rather than the only one.
        if not bucket:
            raise StorageError("storage_backend is 's3' but no bucket is configured")
        return S3ObjectStore(
            bucket=bucket, prefix=prefix, endpoint_url=endpoint_url, region=region
        )
    if backend == "local":
        return LocalObjectStore(upload_dir)
    raise StorageError(f"unknown storage backend {backend!r}")
