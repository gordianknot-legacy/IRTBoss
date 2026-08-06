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
- Person scoring: EAP, MAP, WLE, each with a standard error
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
- Streamed uploads under a byte cap, with row and column caps applied on shape; parsing, hashing and the disk write all off the event loop
- Item, ID and grouping columns declared by the caller, never inferred
- Analyses: the run row is committed as QUEUED before the job reaches Redis, so a dead queue leaves a visible stuck run and a 503 rather than a client holding an id for a row that was never written. There is a test asserting the enqueue happens — the specific thing v1 lacked.
- CORS is an explicit allowlist; a wildcard is rejected by a validator. Unhandled exceptions return a generic 500 body.

**Worker** (`backend/app/workers/`)
- RQ job that re-reads the stored CSV by its storage reference and overwrites the run's results, so re-running is safe
- A failed run is stored as FAILED with a reason, never as a succeeded run carrying partial results

**Reports** (`backend/app/reports/`)
- Self-contained HTML rendered from persisted data only. Nothing is recomputed at render time.
- Jinja with autoescaping and `StrictUndefined`, both load-bearing: item ids and failure reasons are user-supplied and reach the page, and a renamed field must fail loudly rather than render as a blank cell
- Formatting whose one job is that absence must not look like a value: an uncomputed statistic renders as an explicit marker, small p-values render as a bound, an interval with one missing endpoint is refused
- Owner-scoped, and a run that did not succeed returns 409 rather than a document of absent numbers laid out as findings

**Frontend** (`frontend/`) — present in the working tree, not yet committed
- React 18 + TypeScript + Vite, TanStack Query for all server state, React Router with an auth guard
- Result sections for the sample, the comparison dossier, per-model diagnostics, assumptions, DIF, person scores, reproducibility and diagnostic failures
- A shared component for rendering absence, with tests

---

## Known gaps

These are real and none of them are hidden in the code. They belong here rather than in a backlog nobody reads.

**Security**
- Login rate limiting is in-process, so the effective limit across N API workers is N times the configured one, and a restart clears it. A Redis-backed limiter is written but deliberately not wired, so that login does not depend on Redis being reachable.
- No CSRF token. This is safe only while the session cookie stays `SameSite=Lax` and no GET request mutates state.
- Logout clears the cookie, but a bearer token remains valid for its 12-hour TTL. The only revocation is a password change.
- The cookie's `secure` flag follows `is_production`, so a staging deployment left at `environment=development` would send it in plaintext.
- Registration returns 409 on a duplicate address, which discloses that the address is registered. Login does not.

**Deployment**
- Uploads land on container-local disk. The API and the worker share a volume in Docker Compose, which is exactly the coupling that stops working once they run on different hosts. This has to become object storage before a multi-process deploy, not after.
- `requirements.txt` still uses lower bounds. It is the input to a lockfile, not a substitute for one, and the lockfile does not exist yet.

**Testing**
- The suite runs against SQLite and `fakeredis` by default. PostgreSQL specifics — JSONB, native `uuid`, `ON DELETE CASCADE`, the CHECK-constraint enums — are now covered by a CI job that points the same application tests at a real PostgreSQL service via `IRTBOSS_TEST_DATABASE_URL`, and that job also applies and reverses the Alembic migration so a migration that drifts from the models is caught. That job has not yet run on this machine: there is no PostgreSQL or Docker here, so it is verified by construction rather than by observation.
- The queue is still `fakeredis` everywhere. **No real RQ worker has dequeued a real job in an automated test.** Docker Compose is the only place that path runs at all.
- Tier 2 mirt agreement runs on a schedule, not per push, so a divergence from the reference implementation can survive on a branch for up to a week.

**Product**
- Consequence analysis (how much θ estimates, standard errors and cut-score classifications change across candidate models) is described in ARCHITECTURE §3.3 and is not implemented.
- The Vuong test for non-nested pairs is not implemented. The held-out predictive log-likelihood answers the same question with one fewer asymptotic approximation; the refusal states this rather than hiding it.
- Report export is HTML only. There is no PDF or JSON export endpoint.
- The orchestrator scores respondents with EAP. MAP and WLE exist in the engine and are not selectable through the API.
- The IRT likelihood-ratio DIF method fits both groups under a single latent population, so it is approximate under substantial group impact. The observed-score methods are the ones to trust there, and the limitation is documented in the module.
- M2's power against 3PL guessing is modest: the 2PL absorbs the univariate margins almost exactly, so detecting a real lower asymptote needs roughly 25 items and n = 4000 at c = 0.35 before the statistic fires reliably. A non-significant M2 is not evidence against guessing.
- `examples/sample_datasets/` still contains the v1 files and its README documents a `dichotomous_medium.csv` that does not exist. The datasets have not been regenerated from `app/irt/simulate.py`, so their true parameters are not documented.

---

## Design decisions worth knowing

1. **A comparison dossier, not a recommended model.** The reversal of the v1 principle, with its four documented reasons, is in `backend/app/psychometrics/comparison.py`.
2. **Refuse rather than repair.** A non-numeric column is rejected rather than alphabetised; categories are mapped by value so an ordered scale cannot be permuted by row order.
3. **Non-convergence is terminal**, at every layer: engine, orchestrator, worker, report.
4. **One implementation per quantity.** The API computes nothing on read; it serves what the worker persisted.
5. **The latent standard deviation travels.** Passing the 1.0 default for a Rasch or PCM fit puts every moment on a different metric from the parameters, and the output looks plausible while being wrong. There is a test that asserts on the call arguments for exactly that reason.
6. **Enums persist their values, not their member names**, so the database and the wire format cannot diverge.

---

## Reference documents

- [`docs/v2/PROBLEMS.md`](docs/v2/PROBLEMS.md) — the audit of the v1 baseline, with file and line evidence
- [`docs/v2/ARCHITECTURE.md`](docs/v2/ARCHITECTURE.md) — the target design and the decisions behind it
- [`docs/v2/DEPLOYMENT.md`](docs/v2/DEPLOYMENT.md) — deployment topology and operational notes
