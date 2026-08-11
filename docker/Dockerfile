# IRTBoss backend.
#
# One image, two commands: the API runs uvicorn, the worker runs
# `python -m app.workers.main`. Building them separately would let the two
# drift, and the worker imports the same estimation code the API validates
# against.
#
# There is deliberately no R in this image. v1 installed rocker/r-ver and
# compiled mirt here — hundreds of megabytes — because the estimator shelled out
# to Rscript at runtime. It no longer does: the engine is pure Python, and mirt
# is used only as a test oracle in CI. Keeping R would have meant shipping a
# dependency the running system never calls.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall scipy.
#
# From the lock, with --require-hashes: two builds of the same commit contain the
# same code, which is the minimum a product that stamps an engine version on
# every result has to be able to claim. requirements.txt is copied alongside it
# for provenance — nothing installs from it here.
COPY backend/requirements.txt backend/requirements.lock ./
RUN pip install --upgrade pip && pip install --require-hashes -r requirements.lock

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

# The local storage backend writes here. It is a development convenience only —
# production configuration is refused on it, because a directory shared between
# the API and the worker only works while the two are on one machine. Compose
# runs against MinIO, so nothing in a normal run writes to this directory.
RUN mkdir -p /app/var/uploads

RUN useradd --create-home --uid 1000 irtboss && chown -R irtboss:irtboss /app
USER irtboss

EXPOSE 8000

# Probes the path that actually exists. v1 probed `/health` — which was never
# routed — using curl, which was not installed in the image, so the healthcheck
# could only ever fail or be ignored.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
