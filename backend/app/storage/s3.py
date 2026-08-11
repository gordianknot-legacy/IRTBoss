"""S3-compatible object storage.

Written against the S3 API rather than against AWS: ``endpoint_url`` makes the
same code work on Cloudflare R2, Backblaze B2, MinIO and a plain AWS bucket, so
the deployment target is a configuration choice and not a rewrite.

Credentials come from botocore's standard chain — environment variables, a shared
config file, or an instance role — and are deliberately *not* application
settings. Putting them in :class:`~app.core.config.Settings` would mean an
operator has two places to look and this project has one more secret to avoid
logging.

What the tests cover, and what they do not: the round trip, the reference format,
the prefix, the missing-key path and the cross-backend refusal all run against
``moto``'s in-process S3 implementation, so the call arguments and the reference
handling are verified. **No test in this repository has talked to a real S3
endpoint**, and moto does not reproduce eventual consistency, credential
resolution, bucket policy or per-object permissions. The first real deployment is
where those get exercised.
"""

from __future__ import annotations

from typing import Any

from app.storage.base import (
    ObjectNotFound,
    ObjectStore,
    StorageError,
    UnusableReference,
    validate_key,
)

SCHEME = "s3://"

# Botocore reports a missing object under either code depending on whether the
# call was a GET or a HEAD, and S3-compatible services are not consistent about
# which they use.
_MISSING = {"NoSuchKey", "404", "NotFound"}


def build_client(*, endpoint_url: str | None = None, region: str | None = None) -> Any:
    """Construct a boto3 S3 client.

    boto3 is imported here rather than at module scope so that a deployment on
    the local backend does not pay for the import, and so that a missing boto3
    is an error at the point of configuring S3 rather than at application start.

    A configured ``endpoint_url`` forces path-style addressing. botocore's
    default would put the bucket in the hostname — ``https://<bucket>.<host>`` —
    which resolves for AWS and for very little else, so MinIO and a self-hosted
    gateway fail at DNS with an error that says nothing about addressing.
    """

    import boto3
    from botocore.config import Config

    config = Config(s3={"addressing_style": "path"}) if endpoint_url else None
    return boto3.client(
        "s3", endpoint_url=endpoint_url, region_name=region, config=config
    )


class S3ObjectStore(ObjectStore):
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        client: Any | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        if not bucket:
            raise StorageError("S3ObjectStore requires a bucket")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = client if client is not None else build_client(
            endpoint_url=endpoint_url, region=region
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def put(self, key: str, data: bytes) -> str:
        full_key = self._full_key(validate_key(key))
        try:
            self._client.put_object(Bucket=self._bucket, Key=full_key, Body=data)
        except Exception as exc:  # botocore raises a wide family here
            raise StorageError(
                f"could not store object in {self._bucket!r}: {type(exc).__name__}"
            ) from exc
        return f"{SCHEME}{self._bucket}/{full_key}"

    def get(self, ref: str) -> bytes:
        bucket, key = self._split(ref)
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()
        except Exception as exc:
            code = _error_code(exc)
            if code in _MISSING:
                raise ObjectNotFound(ref) from None
            raise StorageError(
                f"could not read {ref!r}: {code or type(exc).__name__}"
            ) from exc

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def _split(self, ref: str) -> tuple[str, str]:
        if not ref.startswith(SCHEME):
            raise UnusableReference(
                f"{ref!r} was not written to S3; this process is configured for "
                "S3 storage and will not read it from anywhere else"
            )
        bucket, _, key = ref[len(SCHEME) :].partition("/")
        if not bucket or not key:
            raise UnusableReference(f"{ref!r} is not a bucket-and-key reference")
        # The reference names its own bucket and that is the one read. A bucket
        # rename therefore leaves existing rows readable, as long as the old
        # bucket still exists and the credentials still reach it; the configured
        # bucket only decides where *new* objects go.
        return bucket, key


def _error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code")) if error.get("Code") is not None else None
    return None
