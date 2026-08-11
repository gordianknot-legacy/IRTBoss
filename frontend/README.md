# IRTBoss frontend

React + TypeScript + Vite + Tailwind SPA for the IRTBoss v2 API.

The product reports a **comparison dossier** and deliberately never names a
winning model. The v1 idea — "pick the best model for you" — has been reversed;
this frontend is written so that reinstating it would require changing types,
not just copy.

---

## Running it

```bash
npm install
npm run dev      # http://localhost:5173, proxies /api -> http://localhost:8000
npm run build    # tsc -b && vite build
npm run lint     # eslint (flat config, eslint 9 + typescript-eslint)
npm run test     # vitest run
```

The dev server proxies `/api` to `http://localhost:8000`, which keeps the browser
on a single origin. That matters: the session is an **HttpOnly cookie** set by
`POST /api/v1/auth/{login,register}` (see `_start_session` in
`backend/app/api/routers/auth.py`), issued with `SameSite=Lax`. Script cannot
read it, so there is no token to attach by hand — every request in
`src/api/client.ts` sets `credentials: 'include'` instead. Running against a
different origin works too (the backend's CORS middleware uses an explicit
allowlist with `allow_credentials=True`), but the proxy avoids needing
`SameSite=None`.

The same call sets a second cookie, `irtboss_csrf`, which script **is** meant to
read: `client.ts` echoes it in an `X-CSRF-Token` header on every non-GET request,
and the backend rejects a cookie-authenticated mutation that arrives without it
(`backend/app/auth/csrf.py`). It carries no authority on its own — a session
cookie is still required — so exposing it to script costs nothing an XSS able to
read it would not already have. `GET /auth/me` reissues it, which is how a
browser whose CSRF cookie expired recovers without logging out.

### Stack

React 18, Vite 6, TypeScript 5.7, Tailwind 3, React Query 5, React Router 6,
`clsx`. No charting library — every figure is hand-written SVG in
`src/components/charts.tsx`. `axios`, `d3` and `zustand` from v1 are gone: the
first is one `fetch` wrapper, the second is a polyline, and the third had no
state left to hold once React Query owned the server cache.

---

## Design tokens

Colour lives in exactly one file: **`src/styles/tokens.css`**. Values are
space-separated RGB channels so Tailwind's `<alpha-value>` slot works.
`tailwind.config.js` *names* those variables and **replaces** the default
Tailwind palette rather than extending it — there are no raw hex values to reach
for, so no component can invent a colour outside the system. Dark mode is a
single block of variable overrides under `prefers-color-scheme: dark`, re-stepped
for the dark surface rather than flipped.

### Colour

| Token | Role |
| --- | --- |
| `canvas` / `surface` / `raised` / `sunken` | Page, panels, inputs, wells |
| `ink` / `ink-muted` / `ink-faint` / `ink-inverse` | Text weights |
| `rule` / `rule-strong` | Hairlines and borders |
| `accent` (+`-soft`) | The product's own voice: links, active nav |
| `attention` (+`-soft`) | **"Look at this."** Item-fit and DIF flags. Never "this is wrong" |
| `absent` (+`-soft`) | **"There is no number here."** Its own hue, so it can never be misread as a value |
| `alarm` (+`-soft`) | A computation or a run failed |
| `steady` (+`-soft`) | A computation completed. Used sparingly, never as a verdict |
| `series-1` / `series-2` | Chart series, in fixed order, never cycled |

The semantic names describe **epistemic states, not outcomes**. There is no
`success` or `error` colour for statistics because nothing in this product
passes or fails.

The two chart series colours pass all six checks of the `dataviz` skill's
`validate_palette.js` — lightness band, chroma floor, CVD separation,
normal-vision floor, and contrast — separately in each mode against that mode's
surface (light `#2E6FC4`/`#C2621A` on `#FFFEFC`; dark `#5C93DC`/`#C87E2C` on
`#1B1B1E`).

### Type

A six-step scale, in `tailwind.config.js`. Anything off it is a mistake, not a
nuance.

`micro` (11px, uppercase eyebrows) · `small` (13px) · `body` (15px) ·
`lede` (17px) · `title` (22px) · `display` (32px)

Three families: `sans` (Inter/system) for UI, `display` (Iowan/Palatino/Georgia)
for headings — the printed-dossier register the whole design is going for — and
`mono` for every numeral. `font-variant-numeric: tabular-nums` is set on `body`,
because a column of statistics that does not align is a column nobody can scan.

### Spacing

4px base, named by step `1`–`9` (`0.25rem`, `0.5rem`, `0.75rem`, `1rem`,
`1.5rem`, `2rem`, `3rem`, `4rem`, `6rem`). Radii: `sm` 2px, default 4px, `lg`
8px. `max-w-prose` is `68ch`; `max-w-page` is `82rem`.

---

## The three invariants

### 1. An absent number is never rendered as a value

`backend/app/analysis/serialise.py` maps **every non-finite float to `null`**, so
every numeric field in the diagnostics payload is `number | null`. `src/api/types.ts`
transcribes this literally — `number | null`, never an optional property, so a
stray `?? 0` has nowhere to hide.

No component formats a number itself. Everything goes through
**`src/lib/absence.ts`**, whose `present()` returns a discriminated union:

```ts
type Presented =
  | { kind: 'value'; text: string; value: number }
  | { kind: 'absent'; text: 'not computed'; reason: string | null }
```

There is no code path from `{ kind: 'absent' }` to a numeral. `formatNumber`
accepts only `number` and throws on NaN/Infinity. `<Value>`
(`src/components/Value.tsx`) is the only component that renders a statistic; it
takes a `Presented`, never a raw number, and an absence gets the `absent` hue,
a `∅` glyph, the literal words "not computed", and `data-absent="true"` in the
DOM. `<Stat>` prints the reason as body text rather than burying it in a
tooltip.

Helpers exist for the shapes where absence is subtle:
`presentP` (never prints `0.000` for a p-value — `< 0.001`),
`presentInterval` (absent unless *both* endpoints exist; half an interval is not
an interval), `presentWithError` (keeps a point estimate whose SE is missing and
renders `1.23 ± not computed`, never `± 0`), and `finitePairs` (charts break at a
gap rather than interpolating across it, and report how many points were dropped).

Covered by `src/lib/absence.test.ts` and `src/components/Value.test.tsx`.

### 2. No model is named a winner

`ComparisonDossier` has no `best_model` field, deliberately.
**`src/lib/dossier.ts`** is the only place the frontend interprets it, and its
output type makes a winner unrepresentable: there is no `winner`, `best` or
`recommended` key, and rows carry a neutral `RowRole` vocabulary —
`'leads-on-held-out' | 'tied-with-leader' | 'ranked' | 'not-ranked'`.

- `leader` is a rank position on one criterion. It always travels with
  `leaderCaveat`, a sentence saying what leading does and does not mean.
- When `indistinguishable` is `true`, **no row is highlighted at all** — the flag
  withdraws the top of the ordering as meaningful, so singling out a row would
  contradict it. Every row becomes `'tied-with-leader'`.
- `verdict` and `notes` are passed through **verbatim**. They are written for
  display; paraphrasing would put a second, unreviewed voice over a carefully
  hedged one.
- Held-out log-likelihood is charted as a **forest plot with ± 1 SE bars**, so
  overlapping uncertainty is visible rather than inferred from a table.
- `disagreements` get their own block; when there are none, the screen says the
  criteria agreeing is not evidence the model is correct.
- Refused likelihood-ratio tests show the full refusal reason. A refusal is a
  result, not an absence.

Covered by `src/lib/dossier.test.ts` (22 tests) and `src/results/Results.test.tsx`.

### 3. Notes and failures are content, not debug output

`run.notes`, every `*.notes` array, and `diagnostics.failures` render through
`<Notes>` at full size, numbered — never as small print. The results screen opens
with **"What was not computed"**: `n_diagnostics_failed` and the full failure list
appear *before the first statistic*, because a report that leads with numbers and
buries "three diagnostics did not run" at the bottom will be read as complete.

---

## How the results screen maps onto the diagnostics payload

`src/results/Results.tsx` fixes the reading order. Every section is driven by one
branch of the `diagnostics` dict assembled at the end of
`backend/app/analysis/orchestrator.run_analysis`.

| Screen section | Payload source | Notes |
| --- | --- | --- |
| **What was not computed** — `FailuresSection` | `failures[]`, `n_diagnostics_failed` | First, always. Reports the gap if the count exceeds the list length. |
| **What this run decided** — `SampleSection` | `run.notes`, `reference_model`, `reference_model_rationale`, `sample`, `validation` | The rationale is shown as prose, in a callout titled "a vantage point, not a verdict". Dropped columns get a table with their reasons; renumbered items get a callout. |
| **Model comparison** — `ComparisonSection` | `comparison` (`ComparisonDossier`) | Forest plot + ranked table + per-criterion orderings + disagreements + LRT ladder + collapsible per-fold detail. See invariant 2. |
| **Assumptions** — `AssumptionsSection` | `assumptions.unidimensionality`, `assumptions.local_independence` | Scree plot (observed vs random 95th percentile), ECV/PUC/ω<sub>h</sub>, MAP series, Q3/Q3*/LD X² pairs. When nothing is flagged, the ten largest \|Q3*\| are shown so the absence of flags is legible rather than inferred from an empty table. |
| **Fit & reliability** — `PerModelSection` | `per_model[key]` + the matching entry in `fits[]` | Model switcher; the reference model is marked `ref`. Global fit (M2/M2*, RMSEA₂ with its interval, SRMSR), reliability (four figures + **conditional SEM curve** + test information in a **separate figure**, never a second y-axis), item fit table, collapsible item parameters with SEs. |
| **DIF** — `DifSection` | `dif` (keyed by grouping column) | One tab per grouping variable, one block per `GroupComparison`. Framed as a screen throughout. When `dif` is null the screen enumerates the four reasons that can cause it and states that nothing should be read as "no DIF was found". |
| **Person scores** — `PersonScoresSection` | `person_scores` | Percentile strip. `n_unscorable` is a callout, not a footnote — those respondents are absent, not at the prior mean. |
| **Reproducibility** — `ReproducibilitySection` | `seed`, `run.engine_version`, dataset checksum, `requested_models`, timestamps, `elapsed_seconds`, per-model convergence | A section of the report, not a footer. |

### Flags the payload does not carry

`to_jsonable` walks `dataclasses.fields()`, so Python `@property` accessors
**never reach the wire**. Several of them are the flags the report is built
around. They are recomputed in **`src/lib/derive.ts`** against the same
thresholds, with the source cited so the two definitions can be diffed:

| Recomputed here | Python source |
| --- | --- |
| `itemFitFlagged` (RMSD > 0.10, or a mean-square outside 0.7–1.3) | `itemfit.ItemFitResult.flagged` |
| `difFlaggedBy` (ETS class B/C; \|SMD\| ≥ 0.25; ΔR² ≥ 0.02; adjusted IRT-LR p < 0.05) | `dif.DIFResult.flagged_by` |
| `essentiallyUnidimensional` (`true`/`false`/**`null` for mixed**) | `assumptions.UnidimensionalityReport.essentially_unidimensional` |
| `isUsable` in `dossier.ts` (`converged && cv_log_likelihood != null`) | `comparison.ModelEvidence.usable` |
| `criteriaAgree` | `comparison.ComparisonDossier.criteria_agree` |

`ItemPairStatistic.flagged` and `EigenvalueRow.retained` *are* real fields and
are used directly.

`THRESHOLD_NOTES` in the same file carries the sentence that must accompany each
flag. Every threshold is a convention, and a flag shown without its threshold
reads as a measurement rather than a screening rule.

---

## API contract

Transcribed from `backend/app/api/schemas.py` into `src/api/types.ts`; hooks in
`src/api/hooks.ts`. Base path `/api/v1`.

| Route | Hook |
| --- | --- |
| `POST /auth/register`, `/auth/login`, `/auth/logout`, `GET /auth/me` | `useRegister`, `useLogin`, `useLogout`, `useCurrentUser` |
| `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}` | `useProjects`, `useCreateProject`, `useProject`, `useUpdateProject`, `useDeleteProject` |
| `POST /projects/{id}/datasets` (multipart: `file`, `id_column`, `group_columns` as a JSON array), `GET /projects/{id}/datasets`, `GET /datasets/{id}` | `useUploadDataset`, `useDatasets`, `useDataset` |
| `POST /datasets/{id}/analyses` → 202, `GET /analyses/{id}`, `GET /datasets/{id}/analyses`, `GET /analyses/{id}/results` | `useCreateAnalysis`, `useRun`, `useRuns`, `useResults` |

`useCurrentUser` turns a 401 into `null` rather than an error — "nobody is signed
in" is an answer, not a failure to answer, and treating it as an error would put
a red banner on every first-time visitor's login screen.

`useRun` polls every 2s and stops on `succeeded`/`failed`. `useResults` is gated
on `succeeded`: the backend returns **409** for an incomplete run by design,
because a results document for one would be a page of absent numbers presented as
findings.

`ApiError` preserves the backend's `detail` verbatim — the ingest layer's
validation messages are authored for users, and replacing them with a generic
string would discard the only part that says what to change. Pydantic's array-shaped
422 bodies are normalised into `fieldErrors`.

---

## Layout

```
src/
  api/        types.ts (wire + diagnostics types), client.ts (fetch + ApiError), hooks.ts
  lib/        absence.ts  ← invariant 1      dossier.ts ← invariant 2
              derive.ts   (missing @property flags)     format.ts
  components/ Value.tsx (the only statistic renderer), ui.tsx, charts.tsx,
              Layout.tsx, RequireAuth.tsx, RunStatusBadge.tsx
  pages/      AuthPage, ProjectsPage, ProjectPage (upload), DatasetPage (run), RunPage (poll)
  results/    Results.tsx + one file per section
  styles/     tokens.css  ← the only place colour is defined
```

## Tests

`npm run test` — 57 tests across four files.

- `src/lib/absence.test.ts` (21) — null/undefined/NaN are absent; zero is a
  value; reasons propagate; `presentP` never prints an exact zero;
  `presentWithError` never prints `± 0`; `finitePairs` drops gaps but keeps zeros.
- `src/lib/dossier.test.ts` (22) — no winner-shaped key exists; role vocabulary
  is rank-only; no *affirmative* winner claim in any caveat the module can emit
  (negated clauses are stripped before the check, since denying a winner is the
  point); `indistinguishable` highlights nothing; a lone candidate is not called
  leading; verdict and notes pass through verbatim; unranked models carry a reason.
- `src/components/Value.test.tsx` (8) — an absent value is never an empty node or
  an empty `<td>`; zero and absence are distinguishable in the DOM.
- `src/results/Results.test.tsx` (6) — the whole screen renders against a
  null-heavy payload and against an indistinguishable comparison, without
  inventing a value anywhere.

There is **no Postgres or Redis on this machine**, so the API has not been
exercised live. Everything above is verified against payloads hand-built to the
shapes in `schemas.py` and `orchestrator.py`, not against a running server.
