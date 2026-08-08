"""Upload storage.

The defect this package removes was not a bug in any line of code: the API wrote
a CSV to a path and the worker opened that path, which is correct while both are
on one machine and fails as soon as they are not — with a missing file, which
looks like corrupted data rather than like a deployment mistake. So the tests
that matter here are not the round trips. They are:

* a reference is self-describing, and a store refuses one written by a different
  backend rather than looking for something its host was never going to have;
* the end-to-end test at the bottom, which puts an upload and a worker run
  through S3 with **no shared filesystem** and asserts that nothing touched the
  local upload directory. That is the property the whole package exists for, and
  it is the one that a path-based implementation cannot pass.

S3 here is ``moto``, in process. It verifies the call arguments and the reference
handling; it does not reproduce credential resolution, bucket policy or eventual
consistency, and no test in this repository has talked to a real endpoint.
"""

from __future__ import annotations

import io
import sys
import types
import uuid

import pytest

from app.storage import (
    LocalObjectStore,
    ObjectNotFound,
    S3ObjectStore,
    StorageError,
    UnusableReference,
    set_object_store,
)
from tests.conftest import CSV_BODY, auth, register

BUCKET = "irtboss-test-uploads"


# --- local backend -------------------------------------------------------

def test_local_round_trip_and_reference_format(tmp_path):
    store = LocalObjectStore(tmp_path / "uploads")
    ref = store.put("datasets/one.csv", b"i1,i2\n1,0\n")

    # The reference is not a path. Nothing downstream may join it to a directory.
    assert ref == "local:datasets/one.csv"
    assert store.get(ref) == b"i1,i2\n1,0\n"
    assert (tmp_path / "uploads" / "datasets" / "one.csv").exists()


def test_local_reports_a_missing_object_as_not_found(tmp_path):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ObjectNotFound):
        store.get("local:datasets/never-written.csv")


def test_local_refuses_a_reference_from_another_backend(tmp_path):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(UnusableReference, match="another storage backend"):
        store.get(f"s3://{BUCKET}/datasets/one.csv")


def test_local_still_reads_a_bare_path_written_before_references(tmp_path):
    """Rows predating this package hold a filesystem path. They still resolve.

    Bounded on purpose: only a reference with no recognised scheme takes this
    path, and only this backend honours it.
    """

    legacy = tmp_path / "var" / "uploads" / f"{uuid.uuid4()}.csv"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"i1\n1\n")

    store = LocalObjectStore(tmp_path / "somewhere-else")
    assert store.get(str(legacy)) == b"i1\n1\n"


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/absolute.csv",
        "../escape.csv",
        "datasets/../../escape.csv",
        "datasets//double.csv",
        "datasets\\windows.csv",
        "s3://bucket/key.csv",
        "datasets/space in name.csv",
    ],
)
def test_a_key_that_is_not_a_plain_relative_name_is_rejected(tmp_path, key):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(StorageError):
        store.put(key, b"x")


# --- S3 backend ----------------------------------------------------------

@pytest.fixture
def s3_client(monkeypatch):
    """An in-process S3 with the bucket already created.

    Credentials are set to fixed nonsense so that a developer's real AWS profile
    cannot be reached from a test run.
    """

    from moto import mock_aws

    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(name, value)

    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_s3_round_trip_and_reference_format(s3_client):
    store = S3ObjectStore(bucket=BUCKET, client=s3_client)
    ref = store.put("datasets/one.csv", b"i1,i2\n1,0\n")

    assert ref == f"s3://{BUCKET}/datasets/one.csv"
    assert store.get(ref) == b"i1,i2\n1,0\n"
    # And it is genuinely in the bucket under that key, not just in the store.
    body = s3_client.get_object(Bucket=BUCKET, Key="datasets/one.csv")["Body"].read()
    assert body == b"i1,i2\n1,0\n"


def test_s3_prefix_is_applied_to_the_key_and_recorded_in_the_reference(s3_client):
    store = S3ObjectStore(bucket=BUCKET, prefix="/irtboss/", client=s3_client)
    ref = store.put("datasets/one.csv", b"x")

    assert ref == f"s3://{BUCKET}/irtboss/datasets/one.csv"
    assert store.get(ref) == b"x"


def test_s3_reports_a_missing_object_as_not_found(s3_client):
    store = S3ObjectStore(bucket=BUCKET, client=s3_client)
    with pytest.raises(ObjectNotFound):
        store.get(f"s3://{BUCKET}/datasets/never-written.csv")


def test_s3_refuses_a_local_reference(s3_client):
    store = S3ObjectStore(bucket=BUCKET, client=s3_client)
    # The important half of the refusal: a worker on S3 handed a local reference
    # says so, instead of failing later with a missing file.
    with pytest.raises(UnusableReference, match="not written to S3"):
        store.get("local:datasets/one.csv")
    with pytest.raises(UnusableReference):
        store.get(f"s3://{BUCKET}")


def test_s3_reads_the_bucket_named_in_the_reference(s3_client):
    """A reference outlives the configured bucket.

    Written into a second bucket and read back by a store configured for the
    first, because a bucket change must not orphan existing rows.
    """

    s3_client.create_bucket(Bucket="irtboss-older-bucket")
    s3_client.put_object(Bucket="irtboss-older-bucket", Key="datasets/old.csv", Body=b"i1\n1\n")

    store = S3ObjectStore(bucket=BUCKET, client=s3_client)
    assert store.get("s3://irtboss-older-bucket/datasets/old.csv") == b"i1\n1\n"


def test_s3_surfaces_a_transport_failure_as_a_storage_error(s3_client):
    class _Broken:
        def put_object(self, **_kwargs):
            raise TimeoutError("connection timed out")

    store = S3ObjectStore(bucket=BUCKET, client=_Broken())
    with pytest.raises(StorageError, match="could not store"):
        store.put("datasets/one.csv", b"x")


# --- the property the package exists for ---------------------------------

async def test_upload_and_worker_round_trip_with_no_shared_filesystem(
    client, settings, queue, engine, s3_client, monkeypatch
):
    """The API writes and the worker reads with nothing on local disk between.

    Both obtain their store through ``get_object_store``, so installing one
    override points both at the same in-process S3 — which is the whole reason
    the override exists.
    """

    set_object_store(S3ObjectStore(bucket=BUCKET, client=s3_client))

    token = await register(client)
    project = await client.post(
        "/api/v1/projects", json={"name": "s3"}, headers=auth(token)
    )
    upload = await client.post(
        f"/api/v1/projects/{project.json()['id']}/datasets",
        files={"file": ("responses.csv", CSV_BODY, "text/csv")},
        data={"id_column": "id"},
        headers=auth(token),
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]

    stored = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert len(stored) == 1
    assert stored[0]["Key"].startswith("datasets/")
    # Nothing landed on local disk. This is the assertion a path-based
    # implementation fails.
    assert not settings.upload_dir.exists()

    run = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"]},
        headers=auth(token),
    )
    assert run.status_code == 202, run.text

    seen: dict = {}

    def _run_analysis(data, models, groups=None, seed=None):
        seen["columns"] = list(data.columns)
        seen["shape"] = data.shape
        return types.SimpleNamespace(fits=[], diagnostics={}, notes=[])

    module = types.ModuleType("app.analysis")
    module.run_analysis = _run_analysis
    monkeypatch.setitem(sys.modules, "app.analysis", module)

    from app.workers.tasks import _execute

    await _execute(uuid.UUID(run.json()["id"]))

    # The worker read the bytes out of the bucket and parsed them: the declared
    # id column is excluded, and the shape matches what was uploaded.
    assert seen["columns"] == ["i1", "i2", "i3"]
    assert seen["shape"] == (20, 3)


async def test_a_reference_the_worker_cannot_resolve_fails_the_run(
    client, queue, engine, s3_client, monkeypatch
):
    """A cross-backend mismatch is a failed run with a reason, not a lost job."""

    from app.db.database import get_sessionmaker
    from app.db.models import AnalysisRun, RunStatus

    token = await register(client)
    project = await client.post(
        "/api/v1/projects", json={"name": "mismatch"}, headers=auth(token)
    )
    upload = await client.post(
        f"/api/v1/projects/{project.json()['id']}/datasets",
        files={"file": ("responses.csv", CSV_BODY, "text/csv")},
        data={"id_column": "id"},
        headers=auth(token),
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]

    run = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyses",
        json={"models": ["2pl"]},
        headers=auth(token),
    )
    run_id = uuid.UUID(run.json()["id"])

    # The upload went to the local backend; the worker is now on S3, which is the
    # state a half-finished migration between backends leaves behind.
    set_object_store(S3ObjectStore(bucket=BUCKET, client=s3_client))

    from app.workers.tasks import _execute

    await _execute(run_id)

    async with get_sessionmaker()() as session:
        stored = await session.get(AnalysisRun, run_id)
        await session.refresh(stored)
        assert stored.status is RunStatus.FAILED
        # The reason names the mismatch rather than a missing file.
        assert "UnusableReference" in stored.failure_reason


def test_the_store_is_chosen_by_configuration(settings, monkeypatch, tmp_path):
    from app.core.config import Settings
    from app.storage import get_object_store

    local = get_object_store(settings)
    assert isinstance(local, LocalObjectStore)
    assert local.root == settings.upload_dir

    configured = Settings(
        secret_key="x" * 32,
        storage_backend="s3",
        s3_bucket=BUCKET,
        s3_region="us-east-1",
    )
    monkeypatch.setattr(
        "app.storage.s3.build_client", lambda **_kwargs: object(), raising=True
    )
    remote = get_object_store(configured)
    assert isinstance(remote, S3ObjectStore)
    assert remote.bucket == BUCKET


def test_the_worker_parses_what_the_store_returns(tmp_path):
    """The read path is bytes-in, frame-out — no filename anywhere."""

    import pandas as pd

    store = LocalObjectStore(tmp_path)
    ref = store.put("datasets/one.csv", CSV_BODY.encode())
    frame = pd.read_csv(io.BytesIO(store.get(ref)))
    assert list(frame.columns) == ["id", "i1", "i2", "i3"]
