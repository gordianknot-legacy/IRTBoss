# IRTBoss Development Progress

State of the `rebuild/v2` branch. This file exists so that a session, a reviewer or a new contributor can tell what is genuinely finished from what merely has a directory. The v1 version of this file reported "PHASE 2 COMPLETE" with a checked box reading "Connected model fitting worker to database" for a connection that did not exist; the list below is written against the code and the commit history rather than against the plan.

Build order is the one set out in [`docs/v2/ARCHITECTURE.md`](docs/v2/ARCHITECTURE.md) §7: honesty before surface area. Nothing user-facing ships on top of a number that cannot be defended.

---

## Status

The v1 estimation stack — the R subprocess wrapper, its fabrication path, and the routes, worker tasks, model selection, diagnostics, recommendations and report generator that depended on it — has been removed. Everything below it has been rebuilt on a native estimator.

### Done

**Estimation engine** (`backend/app/irt/`)
- Bock–Aitkin EM / marginal maximum likelihood over a fixed quadrature grid
- Seven families sharing one unconstrained parameterisation: Rasch, 1PL, 2PL, 3PL, GRM, PCM, GPCM
- Rasch and 1PL separated, with the estimated latent standard deviation carried downstream
- Standard errors for every estimated parameter, via the observed information matrix and a delta-method transform
- Non-convergence is terminal: no parameters, no fit statistics, an explicit failure reason
- Beta(5, 17) prior on the 3PL lower asymptote, recorded in the fit notes
- Full-information handling of missing responses, per cell, with no imputation
- Response simulation from known parameters, used by the recovery tests

**Validation harness** (`backend/tests/validation/`, `.github/workflows/ci.yml`)
- Tier 1: parameter recovery for all seven families, standard-error calibration against empirical sampling variability, missing-data handling and the refusal paths. Pure Python, runs on every push and gates merges.
- Tier 2: agreement with R `mirt` on committed fixtures, over parameters, log-likelihood and free-parameter count. Scheduled weekly and on manual dispatch, because installing R and compiling mirt dominates the runtime. The ordinary test run needs no R and skips these with a stated reason.

**Psychometrics** (`backend/app/psychometrics/`) — one implementation per quantity
- Information, differentiated from each family's own category probabilities rather than hand-derived per family
- Person scoring: EAP, MAP, WLE, each with a standard error; chosen per run through the API, recorded on the run row, and stated in the notes with what the choice costs
- Reliability: marginal Bayesian and information-based, empirical, McDonald's ω, conditional SEM curve, precision bands. No Cronbach's α.
- Item fit: S-X² over a Lord–Wingersky rest-score distribution, infit, outfit, RMSD
- Assumptions: polychoric matrix, parallel analysis, Velicer's MAP, bifactor ECV/PUC/ω<sub>h</sub> approximation; local independence by Q3\* against a bootstrapped critical value
- DIF: Mantel–Haenszel with the ETS A/B/C conjunction, logistic-regression DIF on ΔMcFadden, IRT likelihood-ratio DIF with anchor purification, Benjamini–Hochberg across items
- Global fit: M2 / M2\*, RMSEA2 with a Steiger interval, SRMSR
- Comparison: k-fold held-out predictive log-likelihood with paired per-fold differences, AIC/BIC, a nested likelihood-ratio ladder with explicit refusals, a disagreement matrix, and an indistinguishability verdict. No `best_model` field.

**Analysis pipeline** (`backend/app/analysis/`)
- Validation that refuses rather than repairs, with every decision recorded as a note that reaches the report
- An orchestrator that owns the order of operations, threads the latent standard deviation through every statistic, designates a reference model for item-level diagnostics with a recorded rationale, and records a failed diagnostic as a failure rather than an absence
- JSON-safe serialisation of the diagnostics payload, including result properties opted in via `JSON_PROPERTIES`

**Persistence, auth and API** (`backend/app/db/`, `repositories/`, `auth/`, `api/`)
- Alembic migrations from the initial schema; `create_all` is not used outside tests
- `owner_id` on every owned row; repositories are constructed with the acting user and have no unscoped read path. The worker's unscoped access lives in a separately named class so its use is visible in a diff. Another user's row returns 404 with a body identical to a nonexistent id.
- Argon2id passwords, signed timed session tokens carrying a fingerprint of the password hash, so a password change invalidates every prior session
- Double-submit CSRF token required on state-changing requests that authenticate by cookie; bearer callers are exempt, since `Authorization` is not CORS-safelisted and a forged cross-origin request carrying it needs a preflight that passes the origin allowlist
- `POST /auth/revoke-sessions` invalidates every token signed before it, by comparing each token's signature timestamp against one column on the account. Revocation without a session table, and without making a password change the only lever
- The session cookie is `Secure` unless the environment is explicitly named as local development. Following `is_production` instead meant `staging`, `uat` and every typo served it over plaintext
- Streamed uploads under a byte cap, with row and column caps applied on shape; parsing, hashing and the disk write all off the event loop
- Item, ID and grouping columns declared by the caller, never inferred
- Analyses: the run row is committed as QUEUED before the job reaches Redis, so a dead queue leaves a visible stuck run and a 503 rather than a client holding an id for a row that was never written. There is a test asserting the enqueue happens — the specific thing v1 lacked.
- CORS is an explicit allowlist; a wildcard is rejected by a validator. Unhandled exceptions return a generic 500 body.

**Upload storage** (`backend/app/storage/`)
- Two backends behind one interface: a filesystem one for development and tests, and an S3-compatible one that works against AWS, R2, B2 or MinIO by `endpoint_url`
- What the database records is a storage reference — `local:datasets/<uuid>.csv` or `s3://<bucket>/<key>` — not a path, so the worker needs no filesystem in common with the API. A reference from the other backend is refused by name rather than resolved into a missing file
- Local storage is rejected outright in production, in the same class as the placeholder secret
- Credentials resolve through botocore's own chain and are not application settings
- Docker Compose runs the S3 backend against MinIO, so the path a deployment uses is the path a local run exercises. The API and worker no longer share a volume, and the Fly volume is gone

**Dependency lock** (`backend/requirements.lock`)
- Hash-pinned, resolved for the image's platform, installed with `--require-hashes` by the image and by all three CI jobs
- `tests/test_lockfile.py` fails when a bound in `requirements.txt` is not satisfied by the pin. It does not re-resolve, so an upstream release cannot redden an unrelated build

**Worker** (`backend/app/workers/`)
- RQ job that re-reads the stored CSV by its storage reference and overwrites the run's results, so re-running is safe
- A failed run is stored as FAILED with a reason, never as a succeeded run carrying partial results

**Reports** (`backend/app/reports/`)
- Self-contained HTML rendered from persisted data only. Nothing is recomputed at render time.
- Jinja with autoescaping and `StrictUndefined`, both load-bearing: item ids and failure reasons are user-supplied and reach the page, and a renamed field must fail loudly rather than render as a blank cell
- Formatting whose one job is that absence must not look like a value: an uncomputed statistic renders as an explicit marker, small p-values render as a bound, an interval with one missing endpoint is refused
- Owner-scoped, and a run that did not succeed returns 409 rather than a document of absent numbers laid out as findings

**Frontend** (`frontend/`)
- React 18 + TypeScript + Vite, TanStack Query for all server state, React Router with an auth guard
- Result sections for the sample, the comparison dossier, per-model diagnostics, assumptions, DIF, person scores, reproducibility and diagnostic failures
- A shared component for rendering absence, with tests

**Example datasets** (`examples/sample_datasets/`, `backend/scripts/generate_sample_datasets.py`)
- Four datasets generated from written-down parameters with recorded seeds, replacing the v1 files whose generating parameters nobody had kept and a README that documented a file which did not exist
- Each ships a `<name>.parameters.csv`, and `MANIFEST.json` records seed, shape and SHA-256; `tests/test_sample_datasets.py` checks the digests, so a hand-edited CSV fails the suite rather than outliving its documentation
- Two of them are instructive about their own limits, with the measured numbers in the README: the 3PL example carries real lower asymptotes that n = 500 cannot recover (estimated c correlates with true c at −0.01, the Beta(5, 17) prior doing the work), and the DIF example has no group impact, which is the best case for Mantel-Haenszel rather than a representative one
- The DIF example is complete by design. An earlier draft with 8% missing left 140 complete cases of 800 — below the per-group minimum — so the dataset whose purpose was DIF produced no DIF statistics at all. Missing-data handling is demonstrated by the Likert example instead
- Validation now separates a code set that was merely shifted to 0-based (the 1–5 rating scale) from one that lost a category to a gap. The single note it used to emit claimed a removal that had not happened

**Explainer series** (`docs/explainers/`)
- Twelve self-contained HTML chapters plus an index, taking a reader from "what is wrong with a total score" to the primary literature: history, the seven models, the Bock–Aitkin derivation, scoring and precision, fit and assumptions, DIF, the comparison dossier, applications, the software architecture, a worked example, and a glossary with references
- Part 11 narrates an actual run of `run_analysis()` — 400×12, 2PL and Rasch, seed 20260803 — and every number in it is from the real output, including an indistinguishability verdict alongside a significant LRT and three DIF false positives that die under Benjamini–Hochberg, each used as a teaching case
- Three reading tracks (Stakeholder, Analyst, Maintainer) marked per chapter; inline SVG diagrams; one shared stylesheet, light and dark
- These teach; they do not supersede `docs/irt-basics.md`, `docs/modeling-decisions.md` or the v2 reference documents, and the index says how they relate

---

## Known gaps

These are real and none of them are hidden in the code. They belong here rather than in a backlog nobody reads.

**Security**
- Login rate limiting is in-process, so the effective limit across N API workers is N times the configured one, and a restart clears it. A Redis-backed limiter is written but deliberately not wired, so that login does not depend on Redis being reachable.
- Login CSRF is not defended. State-changing requests that authenticate by cookie must now echo a token (`app/auth/csrf.py`), but a request arriving with no session cookie is exempt, because there is no session to hijack — so a victim can still be forced into the attacker's account. `/auth/logout` is exempt too: being unable to end a session is worse than a forged logout.
- Session revocation is all-or-nothing. `POST /auth/revoke-sessions` invalidates every token signed before it, which covers the lost laptop, but one timestamp per account cannot end one device's session and keep another's. Plain logout stays local to the browser that calls it, and a bearer token it holds survives for the rest of its 12-hour TTL.
- Registration still returns 409 on a duplicate address, and cannot stop doing so without an email channel: the enumeration-safe answer is "check your inbox", which needs an inbox. It is now throttled, so the endpoint cannot be swept against a list; a single address can still be probed.

**Deployment**
- No test has talked to a real S3 endpoint. The store is covered by `moto` in process, and Compose runs the same code against MinIO over the network; neither reproduces credential resolution against a real provider, bucket policy, per-object permissions or eventual consistency.
- The Compose and Fly changes that go with object storage — the MinIO service, the bucket-creation step, the removed shared volume, the removed Fly mount — **have not been run.** There is no Docker on this machine. They are verified by parsing and by reading, not by observation.
- The same applies to the Compose frontend's proxy target. It was set to a `VITE_API_URL` that no frontend code read, so the dev server proxied `/api` to its own container's port 8000 and the browser could not reach the API under Compose at all. It is now `VITE_PROXY_TARGET=http://api:8000`, which is correct by construction and unconfirmed by observation. The same override was verified on this machine against a local API.
- `fly.toml` carries an empty `IRTBOSS_S3_BUCKET`. That is deliberate: it documents the variable and fails at start-up rather than at the first upload. A real bucket name and the credential secrets are still to be set.
- The lockfile covers test and lint dependencies as well as runtime ones, because `requirements.txt` does, so the production image carries pytest and moto. Splitting the two is worth doing and has not been done.
- The lockfile is resolved for Linux on Python 3.12 and does not install on Windows or macOS — `uvloop` alone will not build there. Local development installs `requirements.txt`.

**Testing**
- The suite runs against SQLite and `fakeredis` by default. PostgreSQL specifics — JSONB, native `uuid`, `ON DELETE CASCADE`, the CHECK-constraint enums — are now covered by a CI job that points the same application tests at a real PostgreSQL service via `IRTBOSS_TEST_DATABASE_URL`, and that job also applies and reverses the Alembic migration so a migration that drifts from the models is caught. It cannot be run on this machine — there is no PostgreSQL or Docker here — but it has now run on GitHub and passes, migration round-trip included, so this one is observed rather than merely constructed.
- The queue is still `fakeredis` everywhere. **No real RQ worker has dequeued a real job in an automated test.** Docker Compose is the only place that path runs at all.
- Tier 2 mirt agreement runs on a schedule and on manual dispatch, not per push, so a divergence from the reference implementation can survive on a branch for up to a week.
- Tier 2 **has now run**, which it never had before the v2 branch reached `main`: run `31468740005`, dispatched from `main` on 2026-08-11. Twelve comparisons — four fixtures (Rasch 20×1500, 2PL 25×2000, 3PL 30×3000, GRM 12×2000) against three checks each: item parameters, log-likelihood, free-parameter count — all passed, none skipped. The agreement with `mirt` is now a property of a job that has passed rather than of code that has been read. What is still unobserved is agreement on anything outside those four fixtures.

**Product**
- Consequence analysis (how much θ estimates, standard errors and cut-score classifications change across candidate models) is described in ARCHITECTURE §3.3 and is not implemented.
- The Vuong test for non-nested pairs is not implemented. The held-out predictive log-likelihood answers the same question with one fewer asymptotic approximation; the refusal states this rather than hiding it.
- Report export is HTML only. There is no PDF or JSON export endpoint.
- The IRT likelihood-ratio DIF method fits both groups under a single latent population, so it is approximate under substantial group impact. The observed-score methods are the ones to trust there, and the limitation is documented in the module.
- M2's power against 3PL guessing is modest: the 2PL absorbs the univariate margins almost exactly, so detecting a real lower asymptote needs roughly 25 items and n = 4000 at c = 0.35 before the statistic fires reliably. A non-significant M2 is not evidence against guessing.
- The example datasets are simulated, so they exercise the platform without validating it. They are now generated from documented parameters with recorded seeds (see below), which makes them checkable but does not make them real response data. Nothing in this repository has been fitted to a real instrument.

---

## Design decisions worth knowing

1. **A comparison dossier, not a recommended model.** The reversal of the v1 principle, with its four documented reasons, is in `backend/app/psychometrics/comparison.py`.
2. **Refuse rather than repair.** A non-numeric column is rejected rather than alphabetised; categories are mapped by value so an ordered scale cannot be permuted by row order.
3. **Non-convergence is terminal**, at every layer: engine, orchestrator, worker, report.
4. **One implementation per quantity.** The API computes nothing on read; it serves what the worker persisted.
5. **The latent standard deviation travels.** Passing the 1.0 default for a Rasch or PCM fit puts every moment on a different metric from the parameters, and the output looks plausible while being wrong. There is a test that asserts on the call arguments for exactly that reason.
6. **Enums persist their values, not their member names**, so the database and the wire format cannot diverge.
7. **A storage reference, not a path.** `local:…` and `s3://…` are self-describing, so a process handed a reference from a backend it is not configured for says so. The alternative — a bare path — fails on the wrong layer: the run dies with a missing file, which reads as corrupted data rather than as a deployment mistake. See `backend/app/storage/base.py`.

---

## Reference documents

- [`docs/v2/PROBLEMS.md`](docs/v2/PROBLEMS.md) — the audit of the v1 baseline, with file and line evidence
- [`docs/v2/ARCHITECTURE.md`](docs/v2/ARCHITECTURE.md) — the target design and the decisions behind it
- [`docs/v2/DEPLOYMENT.md`](docs/v2/DEPLOYMENT.md) — deployment topology and operational notes
- [`docs/explainers/index.html`](docs/explainers/index.html) — the twelve-part beginner-to-expert explainer series
