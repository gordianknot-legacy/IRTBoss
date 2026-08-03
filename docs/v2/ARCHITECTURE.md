# IRTBoss v2 — Target Architecture

Companion to [PROBLEMS.md](PROBLEMS.md). Decisions here were made explicitly by
the project owner on 2026-08-03; where a decision reverses the committed README,
that is noted.

---

## 1. Product premise, restated

The v1 premise — *"raw response data → validated IRT model → interpretable
report, for people without a psychometrician"* — is sound and worth keeping. What
v1 got wrong was the implicit corollary: that hiding complexity means *not
computing* it.

The v2 premise sharpens this:

> **IRTBoss produces an assessment validation report that a psychometrician
> would sign, for a team that does not employ one.**

Three commitments follow, and they are the acceptance criteria for every feature:

1. **Never present a number the system did not compute.** No fallbacks, no
   placeholders, no defaults standing in for measurements. If it cannot be
   computed, the product says so in the place the number would have been.
2. **Every claim carries its uncertainty.** Point estimates ship with standard
   errors; model recommendations ship with the statistic and threshold that
   drove them; reliability ships with its conditional profile, not just a scalar.
3. **The report is the product.** The UI is how you get to a defensible artifact,
   not the end in itself. Anything that cannot survive being pasted into a
   technical appendix does not belong in it.

### Scope changes from v1

| | v1 README | v2 |
|---|---|---|
| Polytomous (GRM/PCM/GPCM) | out of scope | **in scope** — a polytomous dataset already ships (P2) |
| DIF / fairness | out of scope | **in scope** — table stakes for the certification segment |
| Item fit statistics | not mentioned | **in scope** — AIC/BIC alone is not defensible (P1.3) |
| Model recommendation | "one recommended model, always" | **reversed** — a comparison dossier with an explicit indistinguishability verdict (§3.3) |
| Model comparison basis | BIC, falling back to AIC | **held-out predictive log-likelihood**, with IC and LRT as secondary evidence (§3.3) |
| Assumption checks | promised, absent | **in scope** — unidimensionality, local independence |
| Estimation engine | R `mirt` subprocess | **pure Python**; mirt demoted to a CI validation harness |
| Deployment | local Docker | **hosted, multi-user**, with auth |
| Multidimensional IRT, CAT, item authoring, LMS integration | out of scope | **still out of scope** |

---

## 2. Estimation engine

**Decision: pure-Python marginal maximum likelihood. R is removed from the
runtime entirely and retained only as a test oracle.**

Rationale: the R dependency bought a gold-standard implementation and cost us a
brittle subprocess/JSON boundary, a 1.5GB image, an untestable failure mode, and
— through `is_available()` swallowing errors — the fabrication path that is the
single worst thing in v1 (P0.3, P0.4). A native engine is debuggable, unit
testable, deployable anywhere, and can be validated *once* against mirt and then
kept honest by CI.

### 2.1 Method

Bock–Aitkin EM with Gauss–Hermite quadrature over a fixed θ grid (default 61
points on [−6, 6], normal weights).

- **E-step:** posterior over the quadrature grid per respondent; accumulate the
  expected number of respondents at each node (`n_k`) and expected number correct
  per item per node (`r_jk`). Missing responses are skipped per-cell, which gives
  FIML behaviour without imputation.
- **M-step:** per-item Newton–Raphson on the expected complete-data
  log-likelihood. Items are independent given the E-step accumulators, so this
  parallelises across items.
- **Convergence:** max absolute parameter change < 1e-4, with a hard iteration
  cap. **Non-convergence is a terminal state**, reported as such, never
  downgraded to a warning that reaches nobody (contrast P0.3 `converged=True`).

### 2.2 Models

| Family | Models | Parameterisation |
|---|---|---|
| Dichotomous | Rasch, 1PL, 2PL, 3PL | `P = c + (1−c)·logistic(a(θ−b))` |
| Polytomous | GRM | cumulative boundaries `b_1..b_{m−1}`, common `a` |
| Polytomous | PCM, GPCM | step parameters `d_1..d_{m−1}`, `a` fixed (PCM) or free (GPCM) |

**Rasch and 1PL are separated**, fixing P1.5: Rasch fixes `a ≡ 1` and estimates
the latent variance; 1PL estimates a common `a` with variance fixed at 1. They
are different metrics and the engine tracks which one it is on, so downstream
θ-grid computations are never silently wrong.

3PL uses a Beta prior on `c` (default Beta(5, 17), mean ≈ 0.23, centred near
`1/k` for a four-option multiple-choice item) to keep the lower asymptote
identified at realistic sample sizes. This is an explicit, documented modelling
choice reported in the analysis metadata, rather than the v1 approach of
refusing to fit below n=500 and then emitting a warning no caller could reach
(P1.3).

The prior is not optional polish. `mirt` applies **no priors to the 3PL by
default**, and an unpenalised EM fit at realistic N produces Heywood cases,
wild `c` estimates, and non-convergence — a failure mode `mirt_wrapper.py`
inherited silently. Because the fit is Bayes-modal rather than pure ML, the
report says so.

A related consequence that the report must state: since `c = 0` sits on the
boundary of the parameter space, **fitting a 3PL to Rasch-generated data
produces `ĉ` systematically above zero.** "The 3PL estimated non-zero guessing"
is therefore not, by itself, evidence of guessing.

### 2.3 Standard errors

From the observed information matrix (Louis' identity for the EM case), inverted
per item. **Every parameter ships with an SE**, closing P1.2 — v1 never extracted
one because it never passed `printSE=TRUE`.

### 2.4 Person scores

EAP (default), MAP, and WLE (Warm), each with a posterior SD / SE. v1 produced
**no person parameters at all** — `estimate_abilities` was dead code (P3).

### 2.5 Validation against mirt

- **Tier 1 — parameter recovery, runs on every commit.** Simulate from known
  parameters at several (n, items, model) points with a fixed seed; assert the
  engine recovers them within a documented tolerance (bias and RMSE bounds).
  Pure Python, no R needed.
- **Tier 2 — mirt agreement, runs in a scheduled CI job.** Stored golden fixtures
  of mirt output for the same datasets; assert our estimates agree within
  tolerance on `a`, `b`, `c`, log-likelihood and AIC/BIC. A GitHub Actions job
  installs R + mirt and regenerates the fixtures to catch drift.

This is the credibility story: *we do not ask you to trust our arithmetic, we
show you it matches the reference implementation.*

---

## 3. Psychometrics

Everything below is absent from v1 (P1.2) and is required for the report to be
defensible. The specifics are grounded in a literature review conducted for this
rebuild; where a widely used rule of thumb turns out to be indefensible, that is
called out, because v1's failure mode was precisely to hardcode conventions
whose source papers reject them.

**The governing rule, borrowed from the ETS DIF framework: an item is flagged
only when it is both statistically significant *and* past an effect-size
threshold.** That conjunction governs every flag the product emits, not just DIF.
It is the single best defence against the large-N problem, where every fit test
rejects everything.

### 3.1 Item fit

- **Standardised S-X² (Orlando & Thissen 2000; Han, Sinharay, Johnson & Liu
  2023)**, with the polytomous generalisation S-G². Bins on the *observed summed
  score* via the Lord–Wingersky recursion, so unlike Q1, Bock's χ² or G² it does
  not bin on θ̂ and therefore does not inherit θ̂ bias from a misfitting model.
  Three properties must be **disclosed in the output**, not hidden:
  - **df is data-dependent.** Sparse cells force adjacent score groups to be
    collapsed, so df differs item to item. Printing S-X² and *p* without df and
    the collapsing detail is not auditable.
  - **The reference χ² is not exactly right** (the Chernoff–Lehmann problem:
    parameters are estimated from ungrouped data). The standardised form is used
    because it produces fewer false positives.
  - **At large N every item fails.** The report states the N-sensitivity
    explicitly rather than letting a wall of red flags imply a broken test.
- **Infit / outfit mean-square** as a **descriptive effect size**. Outfit is not
  a chi-square statistic, so **no p-value is attached to a mean-square** — doing
  so is a category error. The familiar 0.5–1.5 range is *not* used as a fixed
  rule: it holds only for roughly N ≤ 150 and was never simulation-derived
  (Müller 2020; Wu & Adams 2013). Control limits are computed as a function of N.
- **RMSD** from the posterior expectations the E-step already produces — the
  large-scale-assessment workhorse, and cheap given our estimator.
- **Empirical vs. model-implied ICC overlay** per flagged item: the visual
  companion that makes misfit legible to a non-specialist.

### 3.2 Global fit

**M2 / M2\* / C2** limited-information statistics with **RMSEA2** and **SRMSR**.
Full-information G²/X² is unusable — 2^J cells means the asymptotic χ²
approximation collapses under sparseness.

Two cautions the report must carry:
- **RMSEA2 cutoffs do not transfer across test lengths.** Population RMSEA falls
  as items are added at constant misspecification (Maydeu-Olivares 2014), so the
  .05/.06 conventions are length-dependent. **SRMSR is preferred** precisely
  because it lacks this dependence.
- **M2 is insensitive to within-item multidimensionality.** A passing M2 is not
  proof of unidimensionality and is not reported as such.

### 3.3 Model comparison — a dossier, not a winner

**This reverses the v1 README's flagship principle, "One recommended model,
always."** That principle is not merely unimplemented (P1.3); it is
indefensible, for four documented reasons:

- **BIC has a directional bias against the 3PL.** Whittaker, Chang & Dodd (2012)
  found BIC *never* correctly selected the 3PL in any condition examined; Luo &
  Al-Harbi (2017) put BIC's power at 0.67 against LOO/WAIC's 0.98. The cause is
  structural: `c` is weakly identified, so it buys little likelihood, so
  parsimony penalties eat it. This persists at large N — it is not a small-sample
  artefact. A tool that recommends "2PL" on multiple-choice data is reporting its
  own bias, not a finding.
- **The 2PL-vs-3PL LRT is invalid.** The null `c = 0` sits on the boundary of the
  parameter space, violating a regularity condition of Wilks' theorem (Brown,
  Templin & Cohen 2015). The statistic is not χ²; any p-value printed for it is
  wrong. We either implement the corrected test or **suppress the p-value and say
  why**. The nested 1PL-vs-2PL comparison is an interior restriction and remains
  valid, so the ladder is honest on the lower rung and silent on the upper one.
- **ΔBIC has no sampling distribution.** ΔBIC = 3 and ΔBIC = 300 are treated
  identically by an argmin. **"These models are not distinguishable here" must be
  a first-class output**, which no information criterion can ever produce.
- **GRM and GPCM are not nested**, so neither the LRT nor a naive IC difference
  has a distribution. The **Vuong test** is the principled tool, and it carries a
  formal indistinguishability pre-test.

What v2 outputs instead:

1. **An estimability gate, before any comparison.** Hulin, Lissak & Drasgow's
   minima are a **joint** requirement on test length *and* N — 3PL needs ~60
   items × 1,000, or 30 × 2,000. v1 checked N alone (`config.py:48`). Models that
   cannot be estimated from the data at hand are not entered into the comparison,
   and the report says why.
2. **Held-out predictive log-likelihood as the primary criterion** (k-fold over
   response cells). Valid for non-nested comparisons, needs no boundary-valid
   reference distribution, and beat AIC/BIC in the one head-to-head IRT study.
3. **A disagreement matrix across criteria.** Kang & Cohen (2007) showed criteria
   routinely disagree; that disagreement is the most honest signal available and
   is shown rather than resolved by fiat.
4. **An explicit indistinguishability zone**, and a refusal to name a winner
   inside it.
5. **Consequence analysis** (Robitzsch 2022): how much do θ estimates, SEs and
   cut-score classifications actually change across the candidates? If the
   substantive conclusions are stable, the selection question is moot — and
   saying so is more useful than a false winner.
6. **Paradigm awareness.** The Rasch tradition rejects fit-based model selection
   as a category error: the model is prescriptive, so misfit indicts the *items*,
   not the model. v1 silently took a side. v2 asks the user's purpose and, in
   Rasch mode, reports item-level diagnostic evidence rather than a model verdict.
7. **Operational reality.** Real programmes fix the model by item format as
   standing policy (NAEP: 3PL for MC, 2PL for short CR, GPCM for polytomous) and
   do not re-select per administration, because switching families breaks the
   equating chain. Where a user declares an existing scale, the product says so
   and confines itself to diagnostics.

Every sentence in the rationale is generated from a computed quantity. The v1
pattern of hardcoded prose asserting an untested fact (`model_selection.py:374`)
is prohibited, and the test suite asserts that each rationale string carries the
statistic that produced it.

### 3.4 Assumptions

- **Unidimensionality:** parallel analysis on the **polychoric/tetrachoric**
  matrix (not Pearson), Velicer's MAP, and bifactor **ECV / PUC / ωh** with the
  conditional interpretation (when PUC < .80, ECV > .60 and ωh > .70 suggest
  multidimensionality is not severe enough to disqualify unidimensional scoring).
  **The eigenvalue-ratio > 4 heuristic is not implemented** — it traces to
  PROMIS-era practice and was never validated as a decision rule.
  **⚠ The categorical-CFA trap is explicitly avoided:** Hu & Bentler's CFI ≥ .95
  / RMSEA ≤ .06 were derived under normal-theory ML on continuous data and are
  systematically over-optimistic under WLSMV/DWLS on polychorics (Xia & Yang
  2019). Wherever a fit index is shown, **the estimator is named** and the
  benchmark is estimator-appropriate.
- **Local independence:** **Q3\* = Q3,max − Q̄3** (Christensen, Makransky &
  Horton 2017), which corrects Q3's negative bias of ≈ −1/(k−1) — meaning
  absolute cutoffs are miscalibrated *by test length*. **The |Q3| > 0.2 rule is
  not hardcoded**; the source paper explicitly states a single critical value is
  not appropriate across situations, and recommends **parametric-bootstrapping
  the null for the dataset at hand**, which is what we do. Chen & Thissen's
  standardised LD X² is reported alongside, with the surface-vs-underlying
  distinction attempted, since the remedies differ (testlet model vs. bifactor)
  and a flag without that distinction is unactionable.

The README's promise of *"explicit warnings when assumptions are violated"*
becomes true for the first time.

### 3.5 DIF

- **Mantel–Haenszel** with the **ETS A/B/C classification** — the conjunction
  rule: A is negligible (n.s. **or** |Δ_MH| < 1.0), B is significant **and**
  1.0 ≤ |Δ_MH| < 1.5, C is significant **and** |Δ_MH| ≥ 1.5.
- **Logistic regression** DIF for uniform vs. non-uniform, with the ΔR² effect
  size and the lordif ΔMcFadden ≥ 0.02 threshold.
- **IRT-LR** where sample size allows.
- **Per-group N is always reported**, and below ~200/group (2PL) or ~500/group
  (3PL) **"no DIF detected" is labelled as absence of evidence**, not evidence of
  absence.

Requires optional grouping columns in the upload — a schema change from v1,
which has no ID or covariate column handling at all (P2).

### 3.6 Reliability

- **Marginal reliability computed correctly** as `ρ = 1 − E_θ[SE²(θ)]`, closing
  the Jensen bias in P1.1. Both v1 copies of the wrong formula are deleted.
- **Empirical reliability** reported *alongside* it, using the observed sample's
  θ̂ distribution and realised SEs. The two diverge whenever the sample departs
  from the assumed prior — which is most real data — and reporting only one hides
  that. The assumed θ distribution is stated.
- **Conditional SEM** across the θ range, with **precision at the cut score**
  called out, since that is what governs classification accuracy.
- **The usable θ range** — e.g. "SE ≤ 0.32, i.e. ρ ≥ .90, for θ ∈ [−1.8, +2.1]"
  — which is far more informative than any scalar.
- **McDonald's ω** as the scalar internal-consistency supplement.
  **⚠ Cronbach's α is deliberately not reported for an IRT-calibrated scale.**
  α assumes essential tau-equivalence — equal loadings — which fitting a 2PL or
  GRM *explicitly denies*. (An earlier draft of this document listed α; the
  literature review corrected it.)

### 3.7 Reporting standards the output is built against

- **AERA/APA/NCME (2014) Standard 4.10** — when an IRT model is used, evidence of
  model fit **must be obtained and documented**. This is the direct mandate for
  §3.1–3.2.
- **Chapter 2** — reliability reported as *conditional* SEMs at relevant score
  levels, especially near cut scores (§3.6).
- **Chapter 3** — subgroup comparability evidence (§3.5).
- **Chapter 7** — the real bar: documentation sufficient for a **qualified
  independent reviewer to evaluate technical adequacy**. Every report is tested
  against the question *could a competent psychometrician reproduce and critique
  this?*
- **ITC Quality Control Guidelines 2.4.1** — item analysis must report per-item
  IRT parameters, reliability/SE, and **test information** by name.
- **ITC 2.4.1.2** — where an analysis program is new, *"run two programs
  simultaneously and compare results."* Our mirt validation harness (§2.5) is not
  marketing; it is a documented quality-control practice we can cite.

Note that the Standards mandate **evidence and documentation, not cutoffs**, and
place the burden on **intended use**. A report that lists statistics without
stating the intended score interpretation satisfies nothing, so the intended use
captured at project creation is carried into the report rather than being a
throwaway form field.

### 3.7 One implementation each
P3 showed the same quantity computed up to four ways with different answers. In
v2, every psychometric quantity has **exactly one implementation**, in
`app/psychometrics/`, consumed by the API, the worker and the report alike. The
API computes nothing on read; it serves what the worker persisted.

---

## 4. Application architecture

```
backend/app/
  irt/              estimation engine — models, EM, SEs, scoring. Pure numpy/scipy.
  psychometrics/    fit stats, assumptions, DIF, reliability. One implementation each.
  domain/           dataclasses: the analysis vocabulary, no I/O
  services/         orchestration; the only layer that touches both DB and domain
  api/              FastAPI routers, Pydantic schemas, auth dependencies
  db/               SQLAlchemy models + Alembic migrations
  workers/          job definitions; the queue consumer
  reports/          Jinja templates (real files, autoescaped) → HTML/PDF/JSON
```

### 4.1 The job pipeline (fixing P0.1)

`POST /analyses` → validate → persist → **enqueue** → return `202` with a job id.
The enqueue call is covered by an integration test that asserts a job lands on
the queue; the class of bug where a dispatcher has zero call sites cannot recur
silently.

Queue: **RQ on Redis** (already in the compose file, just never used). Jobs are
idempotent and re-runnable; progress is written to the DB by the worker and read
by the API, so it survives a worker restart and an API restart alike. WebSocket
progress is a later enhancement — polling with a durable job row is correct and
sufficient first.

### 4.2 Async discipline (fixing P5)

The API is async; **nothing CPU-bound or blocking runs on the event loop.** CSV
parsing, file writes and report rendering move to `asyncio.to_thread`; all
estimation happens in the worker process. This is enforced by review, and the
heavy paths are simply no longer reachable from a request handler.

### 4.3 Auth and tenancy

Email + password (Argon2id), session cookies with rotation, per-user projects.
Every project-scoped query filters by `owner_id` at the repository layer — not at
the route layer, so a forgotten check cannot expose data. This closes the total
absence of authz and the report-download IDOR in P5.

### 4.4 Data handling

- Streamed upload with a hard size cap, row/column caps, and a per-user quota.
- Explicit schema: an optional respondent-ID column and optional grouping columns
  for DIF, declared in the upload step rather than inferred (v1 would fit an ID
  column as a bogus item, P2).
- SHA-256 of the raw file, the engine version, the seed, and the full parameter
  set are stored and **plumbed into the report** — the reproducibility metadata
  v1 promised in three places and delivered in none (P4).

### 4.5 Reports

Real Jinja template files with `select_autoescape` genuinely active, killing the
stored-XSS path in P5. **Zero hardcoded fields** — the report is rendered from
the persisted analysis record only, so the five fabricated values in P4 have
nowhere to live. HTML and PDF render from the same template and the same data as
the JSON export, so the three formats cannot disagree.

---

## 5. Frontend

React + TypeScript on Vercel, API on Fly/Railway.

- **React Query for all server state** — it is already installed and unused
  (P6). This deletes the hand-rolled fetching, the leaking `setInterval`, and the
  refresh-loses-your-job bug in one move, since a job id lives in the URL and the
  query polls with `refetchInterval` until terminal.
- **Generated types.** The TS client is generated from the FastAPI OpenAPI
  schema, so the seven `undefined`-vs-`null` mismatches and the three
  too-narrow unions in P6 become structurally impossible. Backend enums replace
  the bare `str` fields that made the unions a fiction.
- **Charts rebuilt** with a shared scale system: no dual auto-scaled axes (the
  misleading crossings in P6), explicit clip paths, no sentinel values reaching
  the renderer, `role="img"` + `aria-label` + `<title>`/`<desc>`, a keyboard-
  navigable data table behind every chart, and `viewBox`-based responsiveness.
- **Warnings and uncertainty are first-class UI.** Standard errors render beside
  every parameter; engine identity and any degradation are shown on every results
  view. The v1 situation — a `warnings` field that exists in the type and is
  rendered nowhere (P0.3) — is treated as a product bug, not a nicety.
- Error boundary, route guards, empty states, and a real design system with a
  considered type scale, palette and dark mode.

---

## 6. Deployment

| Piece | Where |
|---|---|
| Frontend | Vercel |
| API + worker | Fly.io or Railway, same image, different entrypoint |
| Postgres | managed (Fly Postgres / Railway) |
| Redis | managed |
| Object storage | uploads and generated reports, so nothing depends on container-local disk (P5) |

- **Alembic migrations from the first commit**; `create_all` is never used
  outside tests.
- **Pinned dependencies with a lockfile.** A product that sells reproducibility
  cannot have unbounded `>=` ranges (P5).
- **CI on GitHub Actions**, which does not currently exist despite
  `CONTRIBUTING.md` claiming it does (P7): lint, typecheck, backend tests with a
  real Postgres service, frontend typecheck and build, and the Tier-1 parameter
  recovery suite on every commit; Tier-2 mirt agreement on a schedule.
- Health checks that probe a path that exists, in an image that contains the tool
  doing the probing (P5).

---

## 7. Build sequence

Ordered so that honesty precedes surface area. Nothing user-facing ships on top
of a number we cannot defend.

1. **Engine** — EM, all six model families, SEs, scoring, parameter-recovery tests.
2. **Psychometrics** — fit, assumptions, reliability, DIF, each with tests.
3. **mirt validation harness** — the credibility gate for 1 and 2.
4. **Domain + persistence** — schema, migrations, the single analysis record.
5. **Worker + queue** — the pipeline that v1 never connected, with an integration
   test that proves it is connected.
6. **API + auth** — generated OpenAPI contract.
7. **Reports** — templates, reproducibility metadata.
8. **Frontend** — design system, charts, generated client.
9. **Deployment** — CI, migrations, hosting.

Docs (`README.md`, `PROGRESS.md`, `docs/*`, `examples/`) are rewritten at the end
against what actually exists, since P7 shows every one of them currently
describes a different product.
