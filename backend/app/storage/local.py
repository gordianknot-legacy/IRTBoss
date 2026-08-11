"""Filesystem-backed object storage.

This is the development and test backend, and the only one the test suite can
reach without a service. It is also refused in production by
:mod:`app.core.config`, because a local directory shared between the API and the
worker is precisely the coupling this package exists to remove.

It keeps one piece of history alive: rows written before storage references
existed hold a bare filesystem path, and :meth:`LocalObjectStore.get` still reads
those. That is a deliberate, bounded compatibility path — it only ever applies to
a reference with no recognised scheme, and only this backend honours it.
"""

from __future__ import annotations

from pathlib import Path

from app.storage.base import (
    ObjectNotFound,
    ObjectStore,
    StorageError,
    UnusableReference,
    validate_key,
)

SCHEME = "local:"


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def put(self, key: str, data: bytes) -> str:
        path = self._path_for_key(validate_key(key))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"{SCHEME}{key}"

    def get(self, ref: str) -> bytes:
        try:
            return self._path_for_ref(ref).read_bytes()
        except FileNotFoundError:
            raise ObjectNotFound(ref) from None
        except OSError as exc:
            # A directory where a file should be, a permission error, a broken
            # mount. Distinct from "not found" because the operator's next step
            # is different.
            raise StorageError(f"could not read {ref!r}: {type(exc).__name__}") from exc

    def _path_for_ref(self, ref: str) -> Path:
        if ref.startswith(SCHEME):
            return self._path_for_key(validate_key(ref[len(SCHEME) :]))
        if "://" in ref:
            raise UnusableReference(
                f"{ref!r} was written by another storage backend; this process is "
                "configured for local storage"
            )
        # Legacy: a bare path written before this package existed. Not
        # traversal-checked, because it is a value this application wrote itself
        # and there is no root it was ever relative to.
        return Path(ref)

    def _path_for_key(self, key: str) -> Path:
        root = self._root.resolve()
        path = (root / key).resolve()
        # `validate_key` already rejects `..`, so this cannot currently fire.
        # It stays because the consequence if it ever could — writing outside the
        # upload directory — is worth two lines to make impossible rather than
        # merely unlikely.
        if root != path and root not in path.parents:
            raise StorageError(f"resolved path for {key!r} escapes the upload directory")
        return path
