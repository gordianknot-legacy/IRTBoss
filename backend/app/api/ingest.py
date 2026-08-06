"""CSV upload handling.

Three v1 defects converge on this file (all P5), and each has a countermeasure
here:

1. **Unbounded uploads.** v1 read the whole body into memory and then let pandas
   materialise a second copy. Here the body is streamed in chunks, the running
   total is checked against ``max_upload_bytes`` *while* reading, and the request
   is rejected the moment it exceeds the cap — before the bytes are parsed and
   before they are written to disk. Row and column caps are enforced after
   parsing, on shape, so a small file cannot expand into a 100k-column frame.
2. **Blocking the event loop.** Parsing and hashing are CPU-bound and the disk
   write is blocking, so all three go through ``asyncio.to_thread``. A route that
   parses inline stalls every other request in that worker.
3. **Inferred schema.** The item columns are stated by the caller (or default to
   "every column that is not the declared id/group column"), never guessed. v1
   inferred, and cheerfully fitted a respondent-id column as an item (P2).

The parsed matrix is not returned to the caller: this module's job is to accept
bytes safely, record their shape and checksum, and hand the worker a file it can
re-read deterministically.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from fastapi import UploadFile

# Read in 1 MiB slices. Large enough that the syscall overhead is irrelevant,
# small enough that the overshoot past the cap before detection is bounded.
_CHUNK = 1024 * 1024


class UploadTooLarge(Exception):
    def __init__(self, limit_bytes: int) -> None:
        super().__init__(f"upload exceeds {limit_bytes} bytes")
        self.limit_bytes = limit_bytes


class InvalidUpload(Exception):
    """The bytes arrived intact but are not a usable response matrix."""


@dataclass(frozen=True)
class ParsedUpload:
    checksum_sha256: str
    size_bytes: int
    n_persons: int
    n_items: int
    column_metadata: dict
    storage_ref: str


async def read_capped(upload: UploadFile, *, max_bytes: int) -> bytes:
    """Stream the body, aborting as soon as it passes ``max_bytes``.

    Checking ``UploadFile.size`` or the ``Content-Length`` header instead would
    trust a client-supplied number; this counts what actually arrived.
    """

    buffer = bytearray()
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise UploadTooLarge(max_bytes)
    if not buffer:
        raise InvalidUpload("uploaded file is empty")
    return bytes(buffer)


def _parse(
    raw: bytes,
    *,
    max_rows: int,
    max_columns: int,
    id_column: str | None,
    group_columns: list[str],
) -> tuple[pd.DataFrame, dict]:
    # Runs in a worker thread. Keep it pure: no I/O, no globals.
    try:
        frame = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:  # pandas raises a wide family here
        raise InvalidUpload(f"could not parse CSV: {type(exc).__name__}") from exc

    n_rows, n_cols = frame.shape
    if n_cols > max_columns:
        raise InvalidUpload(f"too many columns: {n_cols} exceeds the limit of {max_columns}")
    if n_rows > max_rows:
        raise InvalidUpload(f"too many rows: {n_rows} exceeds the limit of {max_rows}")

    columns = [str(c) for c in frame.columns]
    if id_column is not None and id_column not in columns:
        raise InvalidUpload(f"declared id column {id_column!r} is not in the file")
    missing_groups = [c for c in group_columns if c not in columns]
    if missing_groups:
        raise InvalidUpload(f"declared group columns not in the file: {missing_groups}")

    reserved = {id_column, *group_columns} - {None}
    item_columns = [c for c in columns if c not in reserved]
    if not item_columns:
        raise InvalidUpload("no item columns remain after excluding id and group columns")
    if n_rows == 0:
        raise InvalidUpload("file contains no respondents")

    # Observed distinct non-missing values per item, which is what tells the
    # analysis layer whether the data is dichotomous or polytomous. Recorded,
    # not acted on: recoding belongs to validation in the worker.
    categories = {
        column: sorted(
            str(v) for v in pd.unique(frame[column].dropna())
        )[:20]
        for column in item_columns
    }

    metadata = {
        "columns": columns,
        "item_columns": item_columns,
        "id_column": id_column,
        "group_columns": group_columns,
        "observed_categories": categories,
    }
    return frame, metadata


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


async def ingest_csv(
    upload: UploadFile,
    *,
    upload_dir: Path,
    max_bytes: int,
    max_rows: int,
    max_columns: int,
    id_column: str | None = None,
    group_columns: list[str] | None = None,
) -> ParsedUpload:
    raw = await read_capped(upload, max_bytes=max_bytes)
    groups = list(group_columns or [])

    frame, metadata = await asyncio.to_thread(
        _parse,
        raw,
        max_rows=max_rows,
        max_columns=max_columns,
        id_column=id_column,
        group_columns=groups,
    )
    checksum = await asyncio.to_thread(lambda: hashlib.sha256(raw).hexdigest())

    # Name the stored file by a fresh UUID, never by the client's filename.
    # The original name is metadata; using it as a path is how directory
    # traversal gets in.
    storage_path = Path(upload_dir) / f"{uuid.uuid4()}.csv"
    await asyncio.to_thread(_write, storage_path, raw)

    return ParsedUpload(
        checksum_sha256=checksum,
        size_bytes=len(raw),
        n_persons=int(frame.shape[0]),
        n_items=len(metadata["item_columns"]),
        column_metadata=metadata,
        storage_ref=str(storage_path),
    )
