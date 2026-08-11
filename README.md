# IRTBoss

An open-source platform for validating assessments with **Item Response Theory (IRT)**, aimed at teams that need a defensible technical report and do not employ a psychometrician.

The premise:

> IRTBoss produces an assessment validation report that a psychometrician would sign, for a team that does not employ one.

---

## What This Is

The platform takes you from:

**Raw response data → fitted item response models → a diagnostic report you can hand to a reviewer**

It is designed for:
- academic researchers
- EdTech product and data teams
- certification and assessment organisations

It is not a quiz builder, an item bank, or a general statistical sandbox.

---

## Why This Exists

IRT is the standard tool for judging whether a test measures what it claims to, and how precisely. In practice the tooling is fragmented across scripts, expensive, or requires training most teams do not have, so real assessments are deployed without statistical validation.

The v1 of this project tried to lower that barrier by hiding complexity, and drew the wrong conclusion from it: that hiding complexity means not computing it. An audit of that codebase found it had never fitted an IRT model at all — it shelled out to R, and when R was missing it silently substituted parameters generated from a fixed random seed and reported them as results. That audit is preserved in [`docs/v2/PROBLEMS.md`](docs/v2/PROBLEMS.md); the design that replaced it is in [`docs/v2/ARCHITECTURE.md`](docs/v2/ARCHITECTURE.md).

The current codebase is a rebuild against three commitments, which are the acceptance criteria for every feature:

1. **Never present a number the system did not compute.** No fallbacks, no placeholders, no defaults standing in for measurements. If something cannot be computed, the product says so in the place the number would have been.
2. **Every claim carries its uncertainty.** Point estimates ship with standard errors. Held-out comparisons ship with the standard error of the difference. Reliability ships with a conditional standard error curve, not only a scalar.
3. **The report is the product.** The interface is how you get to a defensible artefact. Anything that cannot survive being pasted into a technical appendix does not belong in it.

---

## Core Design Principles

- **A comparison dossier, never a single recommended model.** This deliberately reverses the v1 principle of "one recommended model, always". See below.
- **Refuse rather than repair.** Data that cannot be modelled is rejected with a reason, not coerced into something fittable.
- **Non-convergence is terminal.** A fit that did not converge carries no parameters and no fit statistics; there is no partial-credit path by which unconverged estimates reach a report.
- **One implementation per quantity.** Every psychometric statistic is computed in exactly one place, in `backend/app/psychometrics/`, and consumed by the worker, the API and the report alike. The API computes nothing on read.
- **No silent fallbacks.** Where a statistic is refused, the refusal and its reason are part of the output.

### Why there is no recommended model

Model comparison returns a `ComparisonDossier`, which has no `best_model` field by design. The reasons are documented rather than asserted:

- **BIC is directionally biased against the 3PL.** Its lower asymptote is weakly identified, so it buys little likelihood, so a parsimony penalty eats it. A tool that reports "2PL" on multiple-choice data may be reporting its own penalty function rather than a property of the data.
- **The 2PL-vs-3PL likelihood-ratio test is invalid.** The null `c = 0` sits on the boundary of the parameter space, so the statistic is not chi-square. This platform refuses that test and states why, rather than printing a p-value known to be wrong.
- **ΔBIC has no sampling distribution.** An argmin treats a gap of 3 and a gap of 300 identically. "These models are not distinguishable here" has to be a first-class output, and no information criterion can produce it.

So the primary criterion is k-fold held-out predictive log-likelihood, reported with the standard error of the paired per-fold differences, which is what makes an explicit indistinguishability verdict possible. AIC, BIC and — for genuinely nested pairs only — likelihood-ratio tests are reported alongside. Where the criteria disagree, the disagreement is a field in the output. Resolving it silently in favour of one criterion would hide the choice rather than make it.

---

## What It Does

### Models

Seven families, dichotomous and polytomous, sharing one unconstrained parameterisation:

| Family | Models |
|---|---|
| Dichotomous | Rasch, 1PL, 2PL, 3PL |
| Polytomous | GRM, PCM, GPCM |

Rasch and the 1PL are separate models, not synonyms: Rasch fixes every slope at 1 and estimates the latent variance, while the 1PL estimates one common slope with the variance fixed at 1. They place items on different metrics, and the estimated latent standard deviation is carried into every downstream statistic so that moments and parameters stay on the same scale.

### Estimation

Pure-Python marginal maximum likelihood by the Bock–Aitkin EM algorithm, over a fixed quadrature grid (61 points on [−6, 6] by default). Nothing shells out to R at runtime. R `mirt` is used only as a test oracle in a scheduled CI job that fits committed fixtures and fails the build on disagreement in parameters, log-likelihood or free-parameter count.

- Every estimated parameter ships with a standard error, from the observed information matrix with a delta-method transform to the natural scale.
- Missing responses are skipped per cell — full-information maximum likelihood. Nothing is imputed.
- The 3PL carries a Beta(5, 17) prior on the lower asymptote, because an unpenalised fit produces Heywood cases at realistic sample sizes. The fit is therefore Bayes-modal rather than pure ML, and the report says so.
- AIC and BIC are derived from the log-likelihood printed beside them.

### Diagnostics

- **Item fit** — S-X² over a Lord–Wingersky rest-score distribution, plus infit, outfit and RMSD as effect sizes. No p-value is attached to a mean-square.
- **Global fit** — M2 for binary items, M2\* for ordinal, with RMSEA2 and a Steiger noncentral-chi-square interval, and SRMSR. No CFI or TLI, and no 0.05/0.06/0.95 verdicts; the reasons are in `backend/app/psychometrics/globalfit.py`.
- **Assumptions** — unidimensionality via parallel analysis and Velicer's MAP on a polychoric matrix, with a bifactor ECV/PUC/ω<sub>h</sub> approximation that states it is an approximation. Local independence via Q3\* — Q3 corrected for its structural negative bias — against a critical value from a seeded parametric bootstrap rather than the folk |Q3| > 0.2 cutoff.
- **DIF** — Mantel–Haenszel with the ETS A/B/C classification implemented as the conjunction it is defined as, logistic-regression DIF keyed on ΔMcFadden rather than its p-value, and IRT likelihood-ratio DIF with anchor purification. Benjamini–Hochberg across items, with raw and adjusted p-values both reported.
- **Reliability** — marginal reliability in both its Bayesian and information-based forms, empirical reliability from the observed scores where available, McDonald's ω, a conditional standard error curve, and the contiguous trait ranges over which the test meets a given precision bar. Cronbach's α is deliberately excluded: it assumes equal discriminations, which fitting a 2PL, GRM or GPCM explicitly denies.
- **Person scores** — EAP, MAP and Warm's WLE, each with a standard error. A respondent who answered nothing is reported as unscored rather than handed the prior mean.

---

## Explicitly Out of Scope

- Multidimensional IRT
- Computerised adaptive testing
- Item authoring
- LMS integrations
- Real-time scoring APIs

DIF and polytomous models were out of scope in v1. Both are now implemented.

---

## Workflow

1. **Register and create a project.** Projects are per-user; stakes level and intended use are recorded on the project, because a report that lists statistics without stating the intended score interpretation satisfies no reporting standard.
2. **Upload response data.** CSV, one row per respondent, one column per item. Any respondent-ID column and any grouping columns for DIF are *declared* in the upload, never inferred.
3. **Request an analysis.** You choose which model families to fit. The request is persisted and queued; the API returns 202 with a run id and does no estimation.
4. **Poll the run.** The worker fits every requested model, runs the diagnostics, and persists the result. A diagnostic that fails is recorded as a failure with its reason rather than omitted.
5. **Read the results.** The comparison dossier, per-model fit and reliability, assumption checks, DIF, and the reference model used for item-level diagnostics together with the rationale for that choice.
6. **Render the report.** A self-contained HTML document rendered from the persisted run only. Nothing is recomputed at render time, so re-rendering an old run reproduces the old document.

---

## Architecture

### Backend
- Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL
- RQ on Redis for the analysis queue; the worker runs the same image with a different entrypoint
- numpy/scipy for the estimator and the diagnostics; no R, no compiled extensions of our own
- Argon2id password hashing with signed, timed session tokens; every owned row carries `owner_id` and the repository layer filters on it, so an authorisation check cannot be forgotten one route at a time

### Frontend
- React 18, TypeScript, Vite, TanStack Query, Tailwind

### Repository structure

```
backend/
  app/
    irt/            estimation engine: families, EM, standard errors, simulation
    psychometrics/  information, scoring, reliability, item fit, assumptions, DIF,
                    global fit, comparison — one implementation each
    analysis/       validation and the orchestrator the worker calls
    api/            routers, schemas, upload ingest, auth dependencies
    auth/           password hashing, session tokens, login throttling
    db/             SQLAlchemy models
    repositories/   owner-scoped data access
    workers/        the queue and the analysis job
    storage/        upload storage: the reference format and its two backends
    reports/        Jinja templates and the render path
  alembic/          migrations
  tests/            including tests/validation, the mirt agreement harness
frontend/
docker/
docs/
examples/
```

The two files to read first are `backend/app/psychometrics/comparison.py` and `backend/app/analysis/validate.py`. They encode the two decisions that most distinguish this platform: refusing to name a winning model, and refusing to repair data.

---

## Getting Started

See:
- [`docs/getting-started.md`](docs/getting-started.md)
- [`docs/data-schema.md`](docs/data-schema.md)
- [`docs/modeling-decisions.md`](docs/modeling-decisions.md)
- [`docs/irt-basics.md`](docs/irt-basics.md) if you are new to IRT

Example datasets are in `examples/sample_datasets/`.

---

## Project Status

Early-stage. The estimation engine, the diagnostics suite, persistence, the queue, the API, auth, upload object storage and HTML report rendering exist and are tested. See [`PROGRESS.md`](PROGRESS.md) for what is done, and — more usefully — for the list of known gaps, which includes login rate limiting being in-process, login CSRF being undefended, session revocation being all-or-nothing, no automated test having seen a real RQ worker dequeue a real job, and no test having talked to a real S3 endpoint.

We are especially interested in:
- research collaborators
- early adopters with real assessment data
- contributors who value careful, opinionated design

---

## Contributing

Before proposing a change, consider:

> Does this make it easier for a user to produce a valid, interpretable assessment result — and can every number it puts on the page be defended?

Contributions that increase complexity without improving clarity may be declined. So will contributions that add a statistic without its uncertainty, or a verdict without the quantity that produced it.

---

## License

MIT License
