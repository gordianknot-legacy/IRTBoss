# Getting Started with IRTBoss

This guide gets the stack running and walks one dataset through to a report.

## Prerequisites

- Docker and Docker Compose, for the quickest route
- Or, for local development: Python 3.12, Node.js 20+, a PostgreSQL 16 instance and a Redis instance

**R is not required.** The estimator is pure Python. R and the `mirt` package are needed only if you want to run the Tier-2 agreement tests, which compare our estimates against an independent implementation; they are skipped with an explanatory reason when R is absent, and CI runs them on a schedule rather than on every push.

## Running the stack

### With Docker Compose

```bash
docker compose -f docker/docker-compose.yml up --build
```

This brings up PostgreSQL, Redis, a migration container that runs `alembic upgrade head` to completion, the API, the RQ worker and the frontend dev server. The API and the worker wait on the migration, so neither can start against a schema that does not match the code.

- API: `http://localhost:8000`, versioned under `/api/v1`
- Interactive schema: `http://localhost:8000/docs`
- Frontend: `http://localhost:5173`

Compose is also the only way to exercise the parts of the system the test suite cannot reach on a developer machine: the tests run against SQLite and a fake Redis, so PostgreSQL-specific behaviour and a real worker dequeuing a real job are only covered here.

### Locally

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
cd backend
pip install -r requirements.txt
```

Point the application at your database and Redis. Every setting is read with the `IRTBOSS_` prefix and is declared in `backend/app/core/config.py`:

```bash
export IRTBOSS_DATABASE_URL="postgresql+asyncpg://irtboss:irtboss@localhost:5432/irtboss"
export IRTBOSS_REDIS_URL="redis://localhost:6379/0"
export IRTBOSS_SECRET_KEY="something-random"
```

The database URL must use an async driver. Then:

```bash
alembic upgrade head
uvicorn app.main:app --reload            # API
python -m app.workers.main               # worker, in a second shell
```

The worker is not optional. The API never estimates anything: it validates, persists, enqueues and returns. With no worker running, analyses stay `queued` forever.

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Two notes on configuration that will bite otherwise. `IRTBOSS_SECRET_KEY` has a development placeholder that is rejected outright when `IRTBOSS_ENVIRONMENT` is `production`, so a deployment that forgot to set it fails to start rather than signing session tokens with a value that is in the git history. And `IRTBOSS_CORS_ALLOW_ORIGINS` is an explicit allowlist — `*` is rejected by a validator, because the combination the product needs (cookies) is one browsers refuse against a wildcard anyway.

---

## Your first analysis

### 1. Prepare your data

CSV, one row per respondent, one column per item, integer response codes:

```csv
item_1,item_2,item_3,item_4,item_5
1,0,1,1,0
0,0,1,0,1
1,1,1,1,1
0,1,0,1,0
```

You do not have to strip respondent IDs or demographic columns. You declare them at upload instead, and they are excluded from the item set. See [Data Schema](./data-schema.md) for what is accepted and what is refused.

### 2. Register and create a project

Registration creates a per-user account; every project, dataset and analysis is scoped to its owner, and another user's row is indistinguishable from one that does not exist.

A project records a **stakes level** (low, medium, high) and an **intended use** (research, operational, certification). These are not decoration and they are not used to silently change a model choice. They are carried into the report, because a set of statistics without a stated intended score interpretation does not satisfy any reporting standard.

### 3. Upload data

The upload is streamed under a size cap and rejected the moment it exceeds it, before parsing and before it is written to disk. Row and column caps are applied afterwards, on shape. You declare:

- `id_column` — an optional respondent identifier, excluded from the items
- `group_columns` — optional grouping variables, excluded from the items and available to DIF

Everything not declared is treated as an item column. Nothing is inferred: v1 guessed, and fitted respondent-ID columns as items.

### 4. Request an analysis

You choose which families to fit — any of `rasch`, `1pl`, `2pl`, `3pl`, `grm`, `pcm`, `gpcm`. Requesting a dichotomous model for polytomous data is not an error: the model is skipped, and the reason is a note on the run, because collapsing a five-category item to right/wrong would discard the distinctions it was written to capture.

The run is committed as `queued` before the job reaches Redis, so a queue outage leaves a visible stuck run rather than a run id for a row that was never written. A seed is recorded on every run, along with the engine version, so the analysis is attributable to the code that produced it.

### 5. Wait

Fitting several families with cross-validated comparison is minutes of numerical work, not seconds — the comparison alone fits every candidate once on the full sample and once per fold. Poll the run; you can close the browser.

Each diagnostic is attempted independently. One failing does not fail the run: it is recorded as a failure with its reason, and the count of failures is part of the output. A report can never show fewer diagnostics than were attempted without saying so.

### 6. Read the results

What comes back:

- **The comparison dossier.** Every candidate's held-out predictive log-likelihood with a standard error, AIC, BIC, the nested likelihood-ratio ladder with each test either performed or explicitly refused with its reason, a list of criteria that disagree about which model is first, and a verdict that may be "these models are not distinguishable here". There is no recommended model. See [Modeling Decisions](./modeling-decisions.md) for why.
- **The reference model.** Item fit and local independence have to be computed against some parameterisation, so one model is designated the reference — with its rationale recorded, and, where the candidates are indistinguishable, an explicit statement that a different reference could change which items are flagged.
- **Per-model diagnostics.** Item fit, global fit and reliability for each converged model.
- **Assumption checks.** Unidimensionality and local independence.
- **DIF**, if you supplied grouping columns.
- **Person score summary** for the reference model, including how many respondents could not be scored at all.
- **Validation record.** Which columns were dropped and why, which items were renumbered, how many respondents were excluded, and the missing-data rate.

### 7. Render the report

A self-contained HTML document, rendered from the persisted run only. Nothing is recomputed at render time, so re-rendering a year-old run reproduces the document rather than producing a fresh analysis wearing an old id. A run that did not succeed returns 409 rather than a document of absent numbers laid out as findings.

There is currently no PDF or JSON export.

---

## Reading the output

### Model comparison

The dossier does not name a winner, and reading it as though it did is the main way to misuse this product. The questions it answers, in order of usefulness:

1. Are the candidates distinguishable at all on held-out prediction? If not, the model choice should be made on grounds outside this comparison — interpretability, an existing scale, or programme policy.
2. Do the criteria agree? Disagreement between criteria is informative and is shown rather than resolved.
3. Does the likelihood-ratio ladder apply? For some pairs it is refused, and the refusal carries the reason.

### Item parameters

- **Difficulty (b)** — higher means harder. On the θ metric.
- **Discrimination (a)** — higher means the item separates ability levels more sharply.
- **Guessing (c)** — the lower asymptote, 3PL only, estimated under a Beta(5, 17) prior.
- **Thresholds** — category boundaries or step parameters, polytomous models.

Every one of these ships with a standard error. An estimate whose standard error could not be computed is still shown, because it is a real estimate, but the missing precision is stated: an unqualified number reads as a precise one.

### Reliability

Two model-implied figures are reported, because "standard error" means different things depending on how scores were produced. The **Bayesian** form matches EAP and MAP scores and is the one to quote when this platform's scores are used; the **information-based** form matches ML or WLE scores and is unbounded where the test carries little information. Where they diverge, the divergence is the finding.

**Empirical reliability**, computed from the observed sample rather than the assumed prior, is reported alongside when scores are available. A gap of more than 0.10 usually means the trait distribution in your sample is not the normal distribution the model assumed.

The conditional standard error curve and the trait ranges over which the test meets a precision bar are more informative than any scalar. A test with marginal reliability 0.85 that measures nothing above θ = 1 is a different instrument from one that measures evenly, and only the conditional profile distinguishes them.

Cronbach's α is not reported. See [Modeling Decisions](./modeling-decisions.md).

---

## FAQ

**My model did not converge. What now?**

A non-converged fit carries no parameters and no fit statistics, deliberately: there is no path by which partial estimates reach a report. The usual causes are too few respondents for the family requested, items with no response variance, a very high missing rate, or a model that does not suit the data. The failure reason is recorded on the fit. Check the validation notes on the run first — they list every column that was dropped and why.

**Why does the report not tell me which model to use?**

Because the criteria genuinely disagree, and resolving that disagreement silently in favour of one criterion hides the choice rather than making it. The dossier gives you the evidence and, where the data do not separate the candidates, says so. `ComparisonDossier` has no `best_model` field by design.

**Can I fit a 3PL on 300 respondents?**

You can request it, and it will be fitted and entered into the comparison with a caveat attached. The stable-estimation minimum is a *joint* requirement on test length and sample size — roughly 60 items with 1,000 respondents, or 30 with 2,000 — not a threshold on N alone, and a hard exclusion would pre-empt the comparison that shows whether the extra parameter earned anything. Note also that because `c = 0` sits on the boundary of the parameter space, fitting a 3PL to Rasch-generated data produces estimates of `c` systematically above zero. "The 3PL estimated non-zero guessing" is not by itself evidence of guessing.

**How do I know if my test is good enough?**

There is no single number that answers this, and the product does not print one. Read the conditional standard error over the range you actually make decisions in, the item fit effect sizes, the assumption checks, and — if you have grouping data — the DIF screen. "Good enough" is a judgement about intended use, which is why intended use is recorded on the project.

**An item is flagged for DIF. Is it biased?**

Not necessarily. The screen says the item behaves differently between groups conditional on the trait. Deciding whether that difference is bias requires knowing what the item is asking, which no statistic in the report can see.

**Where is the JSON export? The PDF?**

Not implemented. The report renders as HTML; the results endpoint returns the persisted analysis as JSON, which is the structured data, not a formatted export.

## Next steps

- [IRT Basics](./irt-basics.md) — the concepts, if this is new
- [Data Schema](./data-schema.md) — what is accepted and what is refused
- [Modeling Decisions](./modeling-decisions.md) — the methods and the reasoning behind them
