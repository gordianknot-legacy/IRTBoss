# IRTBoss v2 — Problem Statement

Written 2026-08-03, from a four-track audit of the `rebuild/v2` baseline commit
(`e6003a7`). Every claim below cites the file and line it came from in that
commit. This document is the justification for the rebuild; the target design
lives in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## P0 — The headline problem

> **IRTBoss has never fitted an IRT model, and cannot tell the difference
> between a real result and a fabricated one.**

This is not a bug. It is three independent failures that compose into a product
which is, in its current state, capable of emitting statistically meaningless
output over a professional-looking UI with no disclosure of any kind.

### P0.1 The pipeline is severed

`POST /projects/{id}/fit` (`backend/app/api/routes.py:186`) inserts a
`FittingJob` row with `status="pending"` and returns. The function that would
dispatch it, `enqueue_fitting_job` (`backend/app/workers/tasks.py:486`), has
**zero call sites** — the only occurrence of that identifier in the repository
is its own `def` line. No `BackgroundTasks`, no `.delay()`, no RQ enqueue
anywhere in `app/api/` or `app/services/`.

Consequence: `model_results` and `item_parameters` are never written, so
`/results`, `/diagnostics`, `/recommendations` and `/report` return 404 forever,
and the project sits at status `"fitting"` permanently. The `redis` and `worker`
services in `docker/docker-compose.yml` are decoration.

### P0.2 Even if wired, it would crash before persisting

`store_model_result` reads `model.fit_statistics` at `tasks.py:114-117`. The
attribute is `fit_stats` (`core/model_selection.py:117`), used correctly in the
eight other places it appears. Four consecutive `AttributeError`s, swallowed by
the blanket `except` at `tasks.py:468`, job marked `failed`.

### P0.3 When it can't fit, it invents results

`get_fitter()` (`irt/mirt_wrapper.py:562`) probes for R and, on failure, returns
`DummyFitter` on nothing but a `logger.warning`. `DummyFitter` (`:461-559`):

| Line | What it fabricates |
|---|---|
| `:486` | `difficulty = -2 + 4*(1 - item_mean)` — a linear rescale of the p-value onto [-2,2], not an estimate |
| `:491` | `discrimination = 0.5 + U(0,1)*1.5` — noise, seeded `np.random.seed(42)` *inside* `fit()` so every dataset draws the same numbers |
| `:510` | `log_likelihood = -1000 - rand*100` — unrelated to the data or N |
| `:511-512` | `aic = 2000 + 2k`, `bic = 2000 + k·ln(N)` — **not derived from the LL on the line above**, so AIC/BIC are internally inconsistent with their own log-likelihood |
| `:515` | `converged = True` unconditionally |

Because the fake AIC and BIC are both strictly monotone in `k`, and
`k(1PL) < k(2PL)`, **the Rasch model wins deterministically for every dataset**.
`ModelSelector` then emits the sentence *"1PL model selected: has lowest AIC and
BIC, indicating best balance of fit and complexity"* — a fabricated statistical
justification for a foregone conclusion.

**Where the user is told none of this: nowhere.** Full trace of the disclosure:

1. `mirt_wrapper.py:476` — server log only.
2. → `FittedModel.warnings` → `FittingTaskResult.warnings` → the RQ return dict
   → stored in Redis → **read by no endpoint**.
3. → `ModelResult.warnings` → `/results` response — **blocked by the P0.2 crash**.
4. Even unblocked: the frontend's only reference to `warnings` is the type
   declaration at `frontend/src/api/types.ts:107`. No component renders it.
5. The exported HTML/JSON/PDF report has no warnings field at all — `ReportData`
   (`reports/generator.py:29-67`) does not define one.

The README's stated principle is *"No silent fallbacks."* This is the largest
silent fallback the codebase could contain.

### P0.4 The R path is probably broken anyway

`docker/Dockerfile:14-16` copies `/usr/local/lib/R` and the `R`/`Rscript`
wrappers out of `rocker/r-ver:4.3` (Ubuntu) into `python:3.11-slim` (Debian)
without any of R's runtime shared libraries — no `libgfortran5`, `libgomp1`,
`libblas3`, `liblapack3`, `libreadline`, `libpcre2`, `libicu`, `libtirpc`.
`Rscript` fails on a missing `.so` at first exec, `is_available()` swallows it
(`mirt_wrapper.py:189-204`), and P0.3 takes over. **The shipped container is a
DummyFitter deployment.**

---

## P1 — The psychometrics are wrong where they exist

### P1.1 Marginal reliability is systematically overstated

`irt/models.py:282` and `core/diagnostics.py:484` both compute:

```python
reliability = 1.0 - (1.0 / avg_info)      # avg_info = E_θ[I(θ)]
```

Marginal reliability is `ρ = 1 − E_θ[SE²(θ)] = 1 − E_θ[1/I(θ)]`. By Jensen's
inequality `1/E[I] ≤ E[1/I]`, so **this formula biases reliability upward**, and
the bias grows with how peaked the TIF is — exactly the case for short tests,
which are the ones most in need of an honest number. It also ignores the prior:
under an N(0,1) prior the posterior error variance is `1/(I+1)`, not `1/I`.

Below `avg_info = 1` it returns **exactly 0.0** — a hard discontinuity where
average information 0.99 reports reliability 0.00 and 1.01 reports 0.01. And
because `0.0` is falsy, `recommendations.py:468`'s `elif reliability and ...`
falls through to the reassuring branch at `:474`: **a total measurement failure
reads to the user as "functioning adequately."**

### P1.2 There are no item-fit statistics, despite the docstring

`core/diagnostics.py:7` claims "Item fit statistics." `_generate_item_flags`
(`:369-447`) checks only whether `a`/`b`/`c` fall inside hardcoded boxes from
`config.py:80-84`. Those are *parameter plausibility bounds*, not fit. A grossly
misfitting item with `a=1.2, b=0.3` is reported as `GOOD`.

Absent from the entire backend: **S-X² (Orlando & Thissen), infit/outfit
mean-square, Zh, M2 / RMSEA / SRMSR global fit, Yen's Q3 or any local-dependence
check, any unidimensionality assessment, any DIF, and any parameter standard
error.** `printSE=TRUE` is never passed to `coef()`, so
`se_discrimination`/`se_difficulty`/`se_guessing` are always `None`. There is no
parameter uncertainty anywhere in the product.

### P1.3 Model selection asserts things it did not test

- The `BIC_DIFFERENCE_MEANINGFUL = 10.0` threshold (`config.py:88`) **never
  gates a decision.** `_select_by_information_criteria` (`model_selection.py:353`)
  takes `argmin BIC` unconditionally; the threshold only decides whether to
  *append prose*. So a 2PL beating 1PL by ΔBIC = 0.4 is selected, and the code
  prints two contradictory sentences in the same list: *"2PL selected: lowest
  AIC and BIC"* and *"1PL has similar fit… Simpler model preferred when fit is
  comparable."* The documented parsimony preference (`:160`) is not implemented.
- `:374-377` hardcodes *"Note: AIC slightly favors X, but the difference is not
  substantial enough to justify additional complexity."* **The AIC difference is
  never checked** — `min_aic` is computed at `:358` and never read. The sentence
  is emitted even when ΔAIC = 500. This is a fabricated claim about the data.

### P1.4 `n_parameters` is wrong

`mirt_wrapper.py:135` uses `length(coef(fit))`, which on an mirt object returns
one element per item **plus** a `GroupPars` element — i.e. `n_items + 1`, not
`2·n_items` (2PL) or `3·n_items` (3PL). AIC/BIC come from R and are correct; the
`k` column printed beside them in the comparison table and the exported report
is not.

### P1.5 Rasch and 1PL are conflated, and the R spec is self-contradictory

`IRTModel.RASCH = "1PL"` (`model_selection.py:58`). Rasch fixes `a ≡ 1` and
frees the latent variance; 1PL estimates a common `a` and fixes the variance to
1. Different metrics. The R template (`mirt_wrapper.py:60-64`) passes
`itemtype="Rasch"` **and** a `CONSTRAIN=(1-N, a1)` block — mutually exclusive,
since under `Rasch` mirt does not estimate `a1`. `:104` then hardcodes `a <- 1.0`
and discards the estimated group variance, while every downstream θ-grid
assumes θ ~ N(0,1) (`diagnostics.py:476`, `irt/models.py:274`). For a Rasch fit
with free variance that assumption is false, so **reliability and TIF are
computed on the wrong metric.**

### P1.6 Max 3PL information uses the wrong formula

`project_service.py:633` places the maximum at `P = (1+c)/2`. The maximum of the
3PL information function is at `P = (1 + √(1+8c))/4`. For `c = 0.2` the true
value is 0.653 against the coded 0.600 — the returned "maximum" is not the
maximum of the expression on the very next line. Meanwhile `diagnostics.py:233`
computes the same quantity by grid argmax, so the number a user sees depends on
which code path served it.

### P1.7 θ-coverage fails open

`project_service.py:441-450` initialises `coverage_low = -4.0, coverage_high =
4.0` and overwrites them only if some grid point has `I ≥ 1`. If the test
provides adequate information **nowhere**, the defaults survive and the API
reports **full coverage from −4 to +4** — the exact inverse of the truth.
`diagnostics.py:502` returns `(0, 0)` in the same situation. The API ships the
wrong one.

---

## P2 — Polytomous support is a broken promise

`examples/sample_datasets/polytomous_likert.csv` ships with the repo.
`_detect_response_type` (`data_validation.py:328-348`) recognises it, returns
`POLYTOMOUS, n_categories=5`, and emits a friendly **INFO** message. Validation
passes `is_valid=True`. The user is told their data is fine.

But **there is no GRM, PCM, GPCM or rating-scale model anywhere in the backend.**
`IRTModel` has exactly three members, all dichotomous
(`model_selection.py:58-60`); the R template hardcodes `itemtype ∈ {Rasch, 2PL,
3PL}`. Zero repository hits for `graded|gpcm|grm|pcm`.

So the outcome depends on which fitter is live:

- **With mirt:** `mirt(data, 1, itemtype="2PL")` on 5-category data errors inside
  the `tryCatch`, both models fail, and the user is told *"No models converged
  successfully"* (`tasks.py:252`) — a misdiagnosis. The real cause, *this tool
  cannot model your data*, is never stated.
- **With DummyFitter:** nothing errors. `item_mean ≈ 3` → `difficulty = -10`,
  far outside the `MIN_DIFFICULTY = -4` bound. The system returns
  `status=SUCCESS`, fabricated dichotomous parameters for Likert data, an ICC, a
  TIF, a reliability estimate, and a downloadable report — **all meaningless,
  all labelled as results.**

Relatedly, `_check_item_quality` (`data_validation.py:432`) gates its entire body
on `if response_type == DICHOTOMOUS`, so polytomous data receives **no item
quality checks at all** — no category-frequency check, no empty/collapsed
category detection, no reverse-keying check. `MIN_CATEGORY_FREQUENCY`
(`config.py:69`) is defined and never read.

---

## P3 — Four implementations of the same quantities, disagreeing

| Quantity | Implementations | Disagreement |
|---|---|---|
| Item information | `diagnostics.py:288`, `irt/models.py:250`, `project_service.py:598` | guards differ; only one branches on model type |
| Max item information | `diagnostics.py:233` (grid argmax) vs `project_service.py:622` (closed form) | closed form wrong for 3PL (P1.6) |
| Marginal reliability | `diagnostics.py:466`, `irt/models.py:238` | identical, and identically wrong (P1.1) |
| θ coverage | `diagnostics.py:490` → `(0,0)` on failure vs `project_service.py:441` → `(−4,+4)` | opposite defaults; the API ships the misleading one (P1.7) |
| Item status | `diagnostics.py:449` (1 warning ⇒ ACCEPTABLE) vs `project_service.py:465` (a<0.25 ⇒ FLAGGED) | different verdicts for the same item |
| Recommendations | `core/recommendations.py` (576 lines) vs `project_service.py:507` (80 lines) | **the rich one is dead; the shallow one ships** |
| Comparison-table keys | `model_selection.py:272` `"AIC"` vs `project_service.py:365` `"aic"` | the report reader expects lowercase |

Large parts of the "analysis core" are dead code that never reaches a user:
`core/diagnostics.py` (554 lines) and `core/recommendations.py` (576 lines) are
both computed in `tasks.py` and then **discarded without being persisted**
(`tasks.py:329-331`); the API recomputes shallower versions on read.
`irt/models.py:189` `validate_for_fitting`, `mirt_wrapper.py:362` `fit_all`, and
`mirt_wrapper.py:388` `estimate_abilities` have no call sites — meaning **no
person parameters are ever produced by this system**; `FittedModel.theta_estimates`
is never populated.

---

## P4 — The report is partly fabricated at the route layer

`routes.py:428-475` assembles `ReportData` with hardcoded values:

| Line | Hardcoded | Effect on the exported report |
|---|---|---|
| `:434` | `n_respondents=0` | header prints **"Respondents: 0"** |
| `:436` | `response_type="dichotomous"` | a polytomous project is described as dichotomous |
| `:437` | `missing_percentage=0.0` | asserts complete data regardless of truth |
| `:451` | every item `status="good"` | contradicts the flagged-item list at `:456` in the same report |
| `:443` | `reliability_threshold=0.80` | ignores stakes — a **high-stakes** project (true threshold 0.90) with reliability 0.85 gets a report saying it is *above* threshold while `/recommendations` says *below* |

`data_hash` is computed and stored (`project_service.py:217`) but never plumbed
to the report, so the promised reproducibility metadata is not delivered.
`ReproducibilityMetadata` (`schemas.py:281`) is defined and returned by no
endpoint. `create_mock_report_data` (`generator.py:343-388`) — a fully
fabricated report with hardcoded reliability 0.85 and the sentence *"The
assessment demonstrates acceptable psychometric properties for operational
use"* — is unwired but lives in the shipping module, one import from being served.

---

## P5 — Security and correctness of the application layer

- **No authentication or authorisation of any kind.** Every project, dataset and
  report is world-readable and world-writable by UUID.
- **IDOR on report download.** `routes.py:504-533` accepts `project_id` and
  `format` and then **never uses them** — the file is resolved as
  `REPORTS_DIR / filename`. Any caller fetches any report by filename, which is
  semi-guessable: `report_{project_id[:8]}_{YYYYmmdd_HHMMSS}`.
- **Stored XSS in generated HTML reports.** `reports/generator.py:100-273`
  interpolates `project_name`, `project_description`, `overall_assessment`,
  recommendation titles and item IDs into HTML with **no escaping**. The Jinja
  env sets `select_autoescape` (`:81`) but `TEMPLATE_DIR` does not exist, so the
  unescaped inline path is always taken. `project_name` is attacker-controlled at
  `POST /projects` and the result is served same-origin as `text/html`.
- **CORS `allow_origins=["*"]` with `allow_credentials=True`** (`main.py:63-69`)
  — a spec violation browsers reject, and wide open besides.
- **Unbounded uploads.** `routes.py:148` reads the entire body into RAM, then
  `pd.read_csv` materialises a second copy. No size, row or column cap.
- **Blocking calls on the event loop:** `pd.read_csv` (`project_service.py:138`),
  the synchronous upload write (`:224`), the 81×n_items TIF loop (`:589`), and
  WeasyPrint PDF rendering (`routes.py:482`). None use a threadpool. One upload
  or PDF render stalls every concurrent request in that worker.
- **Raw exception strings returned to clients** (`routes.py:488`, `:170`).
- Upload volume is root-owned because `/app/uploads` is never created before
  `USER irtboss` (`Dockerfile:41`), so the write fails, is downgraded to a
  `logger.warning` (`project_service.py:227`), and `file_path=None` is stored —
  the user sees a successful upload that the worker could never read.
- Healthcheck probes `/health`, which does not exist (it is `/api/v1/health`),
  using `curl`, which is not installed in the production image. Permanently
  unhealthy.
- `psycopg2-binary` is **missing from requirements.txt** while `tasks.py:41`
  builds a sync `postgresql://` engine — the worker dies on its first query.
- WeasyPrint's native deps (pango, cairo, gdk-pixbuf) are not installed; PDF
  export 500s in-container.
- `alembic` is declared with no `alembic/` directory and no `alembic.ini`; schema
  comes from `create_all`. **No migration path.**
- Every requirement is `>=` with no upper bound and no lockfile — builds are not
  reproducible, in a product whose selling point is reproducibility.

---

## P6 — Frontend

The frontend is in better shape than the backend: it is genuinely wired to the
API, `npx tsc --noEmit` passes clean, and there is no mock data. The problems are:

- **Contract drift.** TS uses `?: T` (`undefined`) where FastAPI sends `null`,
  across seven optional fields; data enters through an unchecked
  `response.json()` cast (`client.ts:70`), so `strict` mode catches none of it.
  TS unions (`severity`, `status`, `priority`) are narrower than the backend's
  bare `str` with no enum or validator. `getReportDownloadUrl` (`client.ts:228`)
  omits the `{filename}` segment the route requires.
- **The poll loop leaks.** `ModelComparison.tsx:65-84` creates a `setInterval`
  inside an async handler with no ref and no cleanup — navigating away polls
  forever and setStates on an unmounted component. The `job_id` lives only in a
  closure, so a refresh mid-fit strands the user on a page offering to start a
  **duplicate** job. Meanwhile `pollJobUntilComplete` (`client.ts:155`) is a
  correct poller the app ignores, and React Query is installed, provider-wrapped
  (`main.tsx:19`), and **never used** — zero `useQuery` calls.
- **No routing guards, no error boundary.** `/projects/<garbage>/diagnostics`
  renders a raw error card, or a blank page (`Diagnostics.tsx:106` returns bare
  `null`). Any render throw white-screens the app.
- **Recommendations are fully implemented on both ends and surfaced nowhere** —
  `getRecommendations` exists in the client and the API, and no page calls it.
- **Charts are statistically correct but misleading and inaccessible.** The IRT
  math in both D3 components is right. But both overlay two series on
  independently auto-scaled y-axes, so the *crossing points* between curves are
  artifacts of normalisation; `TIFChart.tsx:353` emits `999` as a no-information
  sentinel which renders as a vertical spike; the x-domain is hardcoded `[-4,4]`
  with no clip path. Neither SVG has `role`, `aria-label`, `<title>` or a data
  fallback — to a screen reader the charts do not exist. The "dashed" legend
  swatches use `borderStyle` on a zero-border div and render identically to the
  solid ones, so the legend cannot distinguish the series. Fixed pixel widths
  with no `viewBox` overflow the viewport on mobile.
- `npm run lint` fails outright — four ESLint packages, no config file.
  `index.html:5` references `/vite.svg` with no `public/` directory. `axios` and
  `zustand` are installed and entirely unused.

---

## P7 — Documentation describes a different product

- `examples/sample_datasets/README.md` documents `dichotomous_medium.csv`, which
  **does not exist** — so no shipped dataset can exercise the 3PL path, which
  requires n ≥ 500. It also claims 200 and 300 respondents where the files have
  **190 and 280**; the "small" dataset the README tells you to start with is
  below the platform's own minimum-sample warning threshold, so the recommended
  first run trips a data-quality warning.
- `CONTRIBUTING.md` asserts "CI must pass." There is no `.github/` directory.
- `PROGRESS.md` reports "PHASE 2 COMPLETE" with 28 checked boxes including
  "Connected model fitting worker to database" — the connection that P0.1 shows
  does not exist.
- The README lists DIF and polytomous models as out of scope; both are now in
  scope for v2.
- `test_api.py` cannot run: `TestClient(app)` with no `dependency_overrides` for
  `get_db` and no test database. `python -m pytest --ignore=tests/test_api.py`
  gives **35 passed** — real, meaningful tests, but covering only the three
  original `core/` modules. Every module added in "Phase 2" —
  `services/`, `db/`, `workers/`, `reports/`, `irt/` — has **zero tests**, which
  is precisely how P0.1 and P0.2 survived to a "complete" phase.

---

## What this means for v2

The audit does not describe a codebase to be patched. Fixing P0.1 and P0.2 would
take about ten lines and would make things *worse*: it would connect a working
pipeline to a fabricating fitter, a wrong reliability formula, a model selector
that asserts untested claims, and a report that hardcodes five of its own
fields — and it would start emitting all of that to users through a UI that
renders no warnings.

The rebuild is therefore sequenced so that **honesty comes before features**: a
real estimation engine with real standard errors first, real fit statistics
second, and only then the surfaces that present them.
