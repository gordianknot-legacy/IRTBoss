# Deployment

Frontend on Vercel, backend on Fly.io, Postgres and Redis as managed services.
This document covers what the configuration does, what it deliberately does not
do, and the things that are known to break at the next step of scale.

## Shape

One Docker image, two processes.

| Process | Command | What it does |
|---|---|---|
| `api` | `uvicorn app.main:app` | HTTP. Never estimates anything. |
| `worker` | `python -m app.workers.main` | Dequeues from Redis, runs the analysis. |

They share an image so they cannot drift. A worker running older estimation code
than the API would produce results the API cannot describe, and the engine
version stamped on every run — which is part of what makes a report
reproducible — would then be a lie.

Migrations run as a Fly `release_command`, before the new version takes traffic.
Without that, the first request after a schema change reaches a database the
code does not match.

## Configuration

Every backend setting is read from the environment with the `IRTBOSS_` prefix
(`backend/app/core/config.py`). Settings without that prefix are ignored —
silently, because there is nothing to warn about; an unrecognised environment
variable is indistinguishable from an unrelated one.

| Variable | Notes |
|---|---|
| `IRTBOSS_ENVIRONMENT` | `production` enables the checks below. Anything else is treated as development. |
| `IRTBOSS_SECRET_KEY` | Signs session tokens. The development placeholder is **rejected outright** when environment is production. |
| `IRTBOSS_DATABASE_URL` | `postgresql+asyncpg://…` |
| `IRTBOSS_REDIS_URL` | |
| `IRTBOSS_STORAGE_BACKEND` | `local` or `s3`. `local` is **rejected outright** in production; see below. |
| `IRTBOSS_S3_BUCKET` | Required when the backend is `s3`. Missing means the process does not start. |
| `IRTBOSS_S3_ENDPOINT_URL` | Set for a non-AWS bucket (R2, B2, MinIO). Omit for AWS. Forces path-style addressing. |
| `IRTBOSS_S3_REGION`, `IRTBOSS_S3_PREFIX` | Region, and an optional key prefix for a shared bucket. |
| `IRTBOSS_UPLOAD_DIR` | Root for the `local` backend only. Ignored under `s3`. |
| `IRTBOSS_CORS_ALLOW_ORIGINS` | The deployed frontend origin. |

Bucket **credentials are not application settings.** `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` — unprefixed, because botocore reads them and this
application never does — resolve through botocore's standard chain, which also
covers an instance role. That keeps one place to look for them and one fewer
secret for the settings object to avoid logging.

Set secrets with `fly secrets set`, never in `fly.toml` — that file is
committed.

### Upload storage is required, not optional

`IRTBOSS_STORAGE_BACKEND=local` in production is a start-up failure, in the same
class as the placeholder secret. The reason is worth stating because the
alternative fails so badly: the API writes the CSV and the worker reads it, so on
the local backend the two processes must share a filesystem. The moment they do
not, the worker is handed a reference to a file its host never had and the run
dies with a missing file — which reads as corrupted data rather than as a
deployment mistake, and sends the reader looking at the wrong layer.

What the database stores is therefore a *storage reference*, not a path:
`local:datasets/<uuid>.csv` or `s3://<bucket>/<key>`. Both are self-describing,
so a worker configured for one backend that meets a reference from the other
refuses by name instead of guessing. Bare paths from before this existed are
still readable on the local backend. See `backend/app/storage/base.py`.

### One configuration trap worth stating plainly

The session cookie's `secure` flag follows `is_production`, which is derived
from `IRTBOSS_ENVIRONMENT`. A staging deploy left at the default
`development` will therefore serve session cookies over plaintext while
otherwise appearing to work. Set `IRTBOSS_ENVIRONMENT=production` on every
deployed environment, including staging, and use the environment's own hostname
to tell them apart rather than this flag.

## Local development

```bash
docker compose -f docker/docker-compose.yml up --build
```

Frontend on `:5173`, API on `:8000`, health at `/api/v1/health`, MinIO console on
`:9001`. Compose runs the `s3` backend against MinIO, so the storage path it
exercises is the deployed one — the API and the worker share no directory.

This is worth running before any deploy, because it is still the only place the
queue is exercised for real.

Postgres-specific behaviour — JSONB, native `uuid` columns, `ON DELETE CASCADE`
— *is* covered in CI: the `postgres` job points the same application tests at a
real PostgreSQL service through `IRTBOSS_TEST_DATABASE_URL`, and applies and
reverses the Alembic migration so a migration that has drifted from the models
fails there rather than on deploy. You can run that locally the same way:

```bash
IRTBOSS_TEST_DATABASE_URL=postgresql+asyncpg://irtboss:irtboss@localhost:5432/irtboss_test \
  pytest tests/test_api_*.py tests/test_worker_pipeline.py -q
```

The queue is the gap that remains. Every test uses `fakeredis`, so **no
automated test has ever seen a real RQ worker dequeue a real job.** Compose is
the only place that happens, which is why it is worth running before a deploy.

## Known limitations

These are load-bearing enough to state before someone discovers them in
production.

**No test has talked to a real S3 endpoint.** The store's round trip, reference
handling, prefix, missing-key path and cross-backend refusal all run against
`moto` in process, and Compose runs the same code against MinIO over the network.
Neither reproduces credential resolution against a real provider, bucket policy,
per-object permissions or eventual consistency. The first deployment is where
those get exercised, so treat the first upload-and-analyse cycle after a bucket
change as a test rather than as traffic.

**Login rate limiting is in-process.** With *N* API instances the effective
limit is *N* × `IRTBOSS_LOGIN_MAX_ATTEMPTS` per window, and a restart clears the
counters. A Redis-backed limiter exists in `app/auth/ratelimit.py` but is
deliberately not wired, so that login does not fail when Redis is unreachable.
That trade-off is worth revisiting before this is exposed to the public
internet; it was chosen for a small deployment.

**There is no CSRF token.** Cookie authentication takes precedence over bearer
in `app/api/deps.py`. This is safe only while the cookie stays `SameSite=Lax`
and no `GET` route mutates state. Both hold today; neither is enforced by a
test.

**Logout does not revoke bearer tokens.** It clears the cookie. A token already
issued stays valid for its full TTL (12 hours by default) and the only
revocation path is a password change. There is no server-side session table, so
a leaked token cannot be individually invalidated.

**Registration discloses whether an address is registered**, returning 409 on a
duplicate. Login is hardened against enumeration; registration is not, and the
two together still leak.

## Before a first real deployment

In rough order of how much damage the absence causes:

1. ~~Object storage for uploads.~~ Built: `backend/app/storage/`, with the `s3`
   backend required in production. What remains is naming a real bucket in
   `fly.toml` and setting the credentials as secrets.
2. A smoke test that a queued job is actually dequeued and completes against a
   real Redis. The Postgres half of this gap is now covered in CI; the queue
   half is not.
3. ~~A dependency lockfile.~~ Built: `backend/requirements.lock`, hash-pinned and
   resolved for the image's platform. The image and all three CI jobs install it
   with `--require-hashes`, and `tests/test_lockfile.py` fails when it drifts from
   `requirements.txt`.
4. Redis-backed rate limiting, or an edge rate limit in front of `/auth/login`.
5. Backups, and a restore that has actually been performed rather than
   configured. Now covers the bucket as well as the database — an upload is not
   reconstructible from the row that describes it.
