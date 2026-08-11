# Modelling Decisions

The methods IRTBoss uses, the choices behind them, and — as often as not — the things it deliberately refuses to compute.

## Design philosophy

IRTBoss is opinionated, but the opinions have moved. The v1 opinion was that a tool for non-specialists should make the decision for them: one recommended model, always. That principle is reversed here, because acting on it means resolving genuine statistical disagreement silently and presenting the result as a finding.

The current position: the product does the work a specialist would do, and hands back the evidence with its uncertainty attached. Where a conventional rule of thumb turns out to be indefensible, it is not implemented, and the omission is stated. Where a statistic cannot be computed, its absence is rendered as an absence rather than as a blank or a zero.

Everything below is implemented in `backend/app/irt/` and `backend/app/psychometrics/`, with one implementation per quantity. The API computes nothing on read; it serves what the worker persisted.

---

## Estimation

### The engine

Marginal maximum likelihood by the **Bock–Aitkin EM algorithm**, in pure Python on numpy and scipy.

- **E-step** — each response pattern's posterior over a fixed quadrature grid, accumulating the expected number of respondents at each node choosing each category of each item
- **M-step** — with those expectations held fixed, items become independent, so each item's parameters come from its own small unconstrained optimisation
- Defaults: 61 quadrature points on [−6, 6], convergence when the maximum absolute parameter change falls below 1e-4, a cap of 500 EM cycles

**R is not in the runtime.** v1 shelled out to `mirt` and, when R was unavailable, silently returned parameters generated from a fixed random seed and labelled them results. R is retained only as a test oracle: a scheduled CI job installs R and mirt, fits committed fixtures, and fails the build on disagreement in parameters, log-likelihood or free-parameter count. That last one matters more than it sounds — a wrong parameter count corrupts every AIC and BIC silently.

Two tiers of validation, because they answer different questions. Tier 1 is parameter recovery: simulate from known parameters, check the engine gets them back. It runs on every push. But the simulator and the estimator share this project's reading of each model, so a shared misunderstanding would pass. Tier 2 is agreement with an independent implementation, which is the only thing that catches that.

### Model families

Seven families over one unconstrained parameterisation, in which the first element of every item's parameter vector is the log slope:

```
2PL          u = [log a, b]
3PL          u = [log a, b, logit c]
Rasch / 1PL  u = [log a, b]                    (element 0 fixed or tied)
GRM          u = [log a, b1, log d2, ...]
GPCM / PCM   u = [log a, s1, ..., s_{m-1}]
```

Working in an unconstrained space means the M-step is an ordinary unbounded optimisation: slopes stay positive, guessing stays in (0, 1) and graded thresholds stay ordered, without the boundary handling that makes constrained optimisers fragile.

**Rasch and the 1PL are separate models.** Rasch fixes every slope at 1 and estimates the latent variance; the 1PL estimates one common slope and fixes the variance at 1. v1 conflated them (`RASCH = "1PL"`) while assuming a unit-variance θ everywhere downstream, so for a Rasch fit with free variance every information and reliability figure was computed on the wrong metric. Here the estimated latent standard deviation travels with the fit and is passed explicitly into item fit, global fit, local independence, reliability and scoring.

### The 3PL prior

The 3PL carries a **Beta(5, 17)** prior on the lower asymptote — mean around 0.23, near 1/k for a four-option item.

This is not polish. `mirt` applies no prior to the 3PL by default, and an unpenalised EM fit at realistic sample sizes produces Heywood cases, wild `c` estimates and non-convergence. Because the fit is therefore Bayes-modal rather than pure maximum likelihood, the output says so.

A consequence that follows and must be read alongside any 3PL result: since `c = 0` sits on the boundary of the parameter space, fitting a 3PL to Rasch-generated data produces estimates of `c` systematically above zero. "The 3PL estimated non-zero guessing" is not, by itself, evidence of guessing.

### Standard errors

Every estimated parameter ships with one, from the observed information matrix with a delta-method transform back to the natural scale. v1 produced none at all — it never passed `printSE=TRUE` — so there was no parameter uncertainty anywhere in the product.

### Non-convergence

Terminal. A fit that does not converge carries no parameters, no log-likelihood and no fit statistics, only a failure reason. There is no partial-credit path by which unconverged estimates reach a report, and no downgrade to a warning that no caller reads.

### Missing data

Skipped per cell. A respondent who skipped item 7 contributes to every other item's accumulators and to their own posterior. That is full-information maximum likelihood behaviour and requires no substitution of invented data. Nothing is imputed and no listwise deletion is applied at estimation.

(DIF is the exception, and for a reason: observed-score matching needs a comparable total for every respondent, so incomplete response vectors are excluded there — from all three methods rather than from some, so that every DIF statistic describes the same people.)

---

## Model comparison

### Why there is no recommended model

`ComparisonDossier` has no `best_model` field. Four documented reasons:

- **BIC is directionally biased against the 3PL.** Whittaker, Chang and Dodd (2012) found BIC never selected the 3PL correctly in any condition they examined; the cause is structural rather than a small-sample artefact. `c` is weakly identified, so it buys little likelihood, so a parsimony penalty eats it. A tool that reports "2PL" on multiple-choice data may be reporting its own penalty function.
- **The 2PL-vs-3PL likelihood-ratio test is invalid.** The null `c = 0` is on the boundary of the parameter space, violating a regularity condition of Wilks' theorem (Brown, Templin & Cohen 2015). The statistic is not chi-square and any p-value printed for it is wrong.
- **ΔBIC has no sampling distribution.** An argmin treats a gap of 3 and a gap of 300 identically. "These models are not distinguishable here" must be a first-class output, and no information criterion can produce it.
- **Criteria routinely disagree** (Kang & Cohen 2007). That disagreement is the most honest signal available, and it is shown rather than resolved.

For contrast, v1's selector took `argmin BIC` unconditionally while printing a hardcoded sentence claiming the AIC difference had been checked. It had not been: the value was computed and never read.

### The primary criterion

**k-fold cross-validated held-out predictive log-likelihood**, five folds by default, split by respondent.

Each fold fits the model on the training respondents, then scores the held-out respondents' full response patterns under those item parameters, marginalising θ over the quadrature prior the fit produced. Splitting by respondent rather than by cell keeps every held-out pattern intact, which is what a marginal likelihood is a probability of; holding out scattered cells would score partial patterns, a different and weaker question.

This works for non-nested comparisons, needs no boundary-valid reference distribution, and — unlike an information criterion — comes with a standard error, which is what makes an indistinguishability verdict possible at all.

Comparisons between two models use **paired per-fold differences**: the same respondents are held out for both models in each fold, so the fold-to-fold variation they share cancels. Two models are declared indistinguishable when the total difference does not exceed the standard error of those paired differences.

### Secondary evidence

AIC and BIC from the full-sample fit, both derived from the log-likelihood reported beside them. And the nested likelihood-ratio ladder, in which every pair is either performed or refused with a reason:

| Pair | Test |
|---|---|
| 1PL vs 2PL, Rasch vs 2PL | Performed |
| PCM vs GPCM | Performed |
| Rasch vs 1PL | Refused — not nested; same parameter count, different metrics |
| anything vs 3PL | Refused — the boundary problem |
| GRM vs GPCM, PCM vs GRM | Refused — different link functions, neither a restriction of the other |

For the non-nested polytomous pairs the principled tool is the Vuong test. It is not implemented, because the held-out predictive likelihood already answers the non-nested question with one fewer asymptotic approximation. The refusal states this rather than hiding it.

### Estimability

Hulin, Lissak and Drasgow's minima for the 3PL are a **joint** requirement on test length and sample size — roughly 60 items with 1,000 respondents, or 30 with 2,000 — not a threshold on N alone, which is what v1 checked. A model below those minima is entered into the comparison with a caveat rather than excluded, because the comparison is what shows whether the extra parameter earned anything.

### The reference model

Item fit and local independence must be computed against some parameterisation, so one converged model is designated the reference — normally the leader on held-out log-likelihood. This is a choice of vantage point, not a verdict, and the rationale is recorded with the result. Where the leading models are indistinguishable, the record says explicitly that the choice was near-arbitrary and that a different reference could change which items are flagged.

---

## Item fit

Three statistics, reported together because each is blind to something the others see.

- **S-X²** (Orlando & Thissen 2000), with the polytomous generalisation. Bins on the *rest score* — the total on every other item — via the Lord–Wingersky recursion. Conditioning on an observed score rather than an estimated θ is what makes it a genuine chi-square: no estimated conditioning variable, so no capitalisation on its error. This is the statistic to trust when the three disagree.
- **Infit and outfit mean-square**, as descriptive effect sizes. They are divided by their model-implied expectation under a posterior that excludes the item being judged, so a fitting item scores exactly 1 rather than approximately 1. **No p-value is attached to a mean-square** — the t-transformations have a null distribution so sample-size dependent that at a few thousand respondents almost every item is "significantly" misfitting, which tells the reader nothing. The familiar 0.5–1.5 range is a convention that holds only at modest N and was never simulation-derived.
- **RMSD** — root-mean-square distance between observed and expected category curves, on the probability scale. It does not grow with sample size, so it answers "how wrong is this item?" rather than "how confident are we that it is wrong at all?"

**Flagging is on effect size, not significance.** An item is flagged when RMSD exceeds 0.10 (the large-scale-assessment convention) or a mean-square falls outside 0.7–1.3. Both are stated as conventions wherever the flag appears. The band is asymmetric in practice: an item that discriminates better than the fitted model allows produces unusually small residuals and drifts towards the lower edge rather than past it, which is one reason the report never reduces to mean-squares alone.

Item fit statistics were absent from v1 entirely. What it called item fit was a check of whether `a`, `b` and `c` fell inside hardcoded boxes — parameter plausibility bounds, not fit — so a grossly misfitting item with ordinary-looking parameters was reported as good.

---

## Global fit

**M2** for binary items, **M2\*** — the collapsed-category variant, built from cumulative dichotomisations — for ordinal ones. For binary items every cut is the same and M2\* reduces exactly to M2, so one implementation serves both and the reported name says which it is.

Full-information X² or G² over the response-pattern table is unusable: with 20 binary items there are a million cells and a few thousand respondents, so almost every cell is empty and the asymptotic approximation fails in a direction nobody can predict. M2 tests only the low-order marginals — univariate proportions and bivariate cross-products — which are estimated from the whole sample and so behave well at realistic N.

Reported with **RMSEA2** and a Steiger noncentral-chi-square confidence interval (90% by default), and **SRMSR**. The interval is reported because M2's own p-value is effectively a sample-size test: at n = 3000 it rejects models that are fit for use, and at n = 300 it accepts models that are not.

**No CFI or TLI.** Both are ratios against a null model, and there is no defensible null for a limited-information categorical fit statistic. Reporting a number whose reference point we invented would be worse than reporting nothing.

**No 0.05 / 0.06 / 0.95 verdicts.** Hu and Bentler's cutoffs were derived from maximum-likelihood fit to continuous, normally distributed data. Population RMSEA2 *falls as items are added* at constant misspecification (Maydeu-Olivares 2014), so a fixed cutoff is implicitly a cutoff on test length: a 60-item test and a 12-item test with identical per-item misfit land on opposite sides of 0.05. SRMSR is preferred precisely because it lacks that dependence.

One property worth knowing before reading an M2 result about guessing: **M2's power against a 3PL lower asymptote is modest.** The 2PL absorbs univariate margins almost exactly, so detecting real guessing needs roughly 25 items and n = 4000 at c = 0.35 before the statistic fires reliably. A non-significant M2 is not evidence against guessing. M2 is also insensitive to within-item multidimensionality, so a passing M2 is not proof of unidimensionality and is not reported as such.

---

## Assumptions

### Unidimensionality

Assessed from the **polychoric** correlation matrix, not the Pearson matrix. Pearson correlations between binary or coarsely ordered items are attenuated by the coarseness itself and generate spurious "difficulty factors" that group items by p-value rather than content.

Three procedures, reported together because they fail differently — parallel analysis is sensitive to sample size, MAP under-extracts when factors are thin, and ECV and ω<sub>h</sub> assume the bifactor pattern they are computed from. Agreement between them is what carries weight:

- **Parallel analysis** against a seeded simulated null, comparing observed eigenvalues to a high percentile of the simulated distribution
- **Velicer's MAP**
- **Bifactor ECV / PUC / ω<sub>h</sub>**, with the conditional interpretation. This is a **Schmid–Leiman-style approximation built from principal components, not a fitted bifactor model** — the general factor is a first principal component, so ECV is biased upward, and the output says so rather than leaving the reader to assume otherwise.

**The eigenvalue-ratio > 4 heuristic is not implemented.** It traces to PROMIS-era practice and was never validated as a decision rule.

**The categorical-CFA trap is avoided.** Hu and Bentler's CFI ≥ .95 / RMSEA ≤ .06 were derived under normal-theory ML on continuous data and are systematically over-optimistic under WLSMV or DWLS on polychorics (Xia & Yang 2019). Wherever a fit index appears, the estimator that produced it is named.

There is a convenience summary — parallel analysis retaining one factor, ECV above 0.85 and ω<sub>h</sub> above 0.80 — but it returns three states, not two. Mixed evidence returns "unresolved", which is a genuine outcome and not a failure: the report shows the components and the reader decides.

### Local independence

**Q3\* = Q3,max − mean(Q3)** (Christensen, Makransky & Horton 2017), which corrects Q3's structural negative bias of about −1/(k−1). That bias means absolute cutoffs are miscalibrated by test length.

**The |Q3| > 0.2 rule is not hardcoded.** The source paper explicitly states that a single critical value is not appropriate across situations and recommends bootstrapping the null for the dataset at hand, which is what happens here: a seeded parametric bootstrap generates the reference distribution. On clean 15-item data, observed maxima land around 0.13–0.14, well inside the folk cutoff, which is the point.

Chen and Thissen's standardised LD X² is reported alongside. One scope limit is stated rather than hidden: the bootstrap null holds the fitted item parameters fixed rather than refitting each replication.

---

## DIF

Three methods, because each sees something the others cannot.

- **Mantel–Haenszel** with the **ETS A/B/C classification**, implemented as the conjunction it is defined as. C requires |Δ<sub>MH</sub>| ≥ 1.5 *and* Δ<sub>MH</sub> significantly larger than 1 in absolute value — a one-sided test against 1 using the standard error of Δ<sub>MH</sub> itself, via Robins–Breslow–Greenland, **not** the Mantel–Haenszel chi-square, which only ever tests against zero. B requires |Δ<sub>MH</sub>| ≥ 1.0 *and* significance at 5%. A is everything else. Thresholding on the effect size alone labels a noisy estimate from a thin stratum as category C; thresholding on the p-value alone labels a trivially small but precisely estimated difference as DIF on a large sample. Mantel–Haenszel is blind to non-uniform DIF, which is the main reason it is not used alone.
- **Logistic regression** DIF (Swaminathan & Rogers), which sees the interaction term Mantel–Haenszel cannot. **Flagging is keyed on ΔMcFadden ≥ 0.02 (after lordif), not on the p-value**: with a few thousand respondents the likelihood-ratio test finds statistically real differences far too small to matter to anyone. Its weakness is the same observed-score matching — the total score is measured with error, and under large impact that error correlates with group, inflating Type I error.
- **IRT likelihood ratio** (Thissen, Steinberg & Wainer), which matches on the latent trait rather than a fallible observed score and says *which* parameter differs. It depends on the anchor set: leaving a contaminated item in the anchors links the groups on a crooked metric and smears the contamination across every other item, so a purification loop runs and the anchors actually used are reported. **Structural limitation, stated in the module rather than hidden:** the estimator has a single latent population, so group differences in the ability distribution are not modelled. Under substantial impact the IRT-LR results are approximate, and the observed-score methods — which condition on a quantity no model had to get right — are the ones to trust.

Across items, p-values are adjusted by **Benjamini–Hochberg**, and both raw and adjusted values are reported. The ETS classification deliberately uses the raw p-value, because that is how the classification is defined and how published DIF tables are read.

**A minimum of 100 respondents per group is enforced, not assumed.** Below it the statistics are `None` and the reason is in the notes: "no DIF detected" on a thin group is absence of evidence, not evidence of absence.

With more than two groups, each is compared with the reference group (the largest by default) in turn. There is no omnibus test, the comparisons share the reference sample and are therefore not independent, and the FDR adjustment is applied within each comparison rather than across them — all of which is stated in the output.

DIF requires grouping columns, which are declared at upload. This is a schema change from v1, which handled no ID or covariate columns at all.

---

## Reliability

The v1 implementation computed `1 - 1/mean(information)`. That is not marginal reliability, and by Jensen's inequality it is always at least as large, so every test the platform ever scored was reported as more precise than it was — and the overstatement grew with how peaked the information function was, which is exactly the short tests most in need of an honest number. It also returned exactly 0.0 below average information 1, and because 0.0 is falsy, a total measurement failure fell through a truthiness check and read to the user as "functioning adequately".

The correct definition integrates the error *variance*:

```
rho = 1 - E_theta[SE^2(theta)] / var(theta)
```

Two forms are reported, because SE means different things depending on how scores were produced:

- **Bayesian** — `SE² = 1 / (I(θ) + 1/σ²)`. Matches EAP and MAP, bounded above by the trait variance, and the figure to quote when this platform's scores are used.
- **Information-based** — `SE² = 1 / I(θ)`. The classical test-information form, matching ML or WLE. Unbounded where the test carries little information, so it can be far lower and, for a 3PL, can be dominated by the low-ability tail. That instability is a finding and is flagged rather than smoothed away.

Alongside them:

- **Empirical reliability** from the observed sample's scores and realised standard errors — the only figure computed from respondents rather than from the model, and therefore the only one that can disagree with it. A gap above 0.10 is flagged, because it usually means the sample's trait distribution is not the normal one the model assumed.
- **Conditional SEM** across the θ range, in both forms.
- **Precision bands**: the contiguous trait ranges over which the standard error stays at or below 0.50 and 0.33 (reliability-equivalents of 0.75 and 0.89). If no part of the range meets even the 0.50 bar, that is stated outright — the test does not support individual-level interpretation anywhere on the scale.
- **McDonald's ω**, from the model-implied factor loadings, with the logistic-to-normal-ogive scaling constant applied. Not reported for polytomous models or for the 3PL, where the factor-model equivalence ω relies on does not hold; the reason is reported in its place.

**Cronbach's α is deliberately excluded.** It is exact only under essential tau-equivalence — equal item discriminations — which fitting a 2PL, GRM or GPCM explicitly denies. Reporting it beside those models would contradict the model that produced the scores. Where α is defensible at all (Rasch, PCM) it adds nothing the model-based figures do not already give with a conditional standard error attached.

Conventional adequacy levels — 0.70 for group-level reporting, 0.90 for individual decisions — appear in the notes as conventions. They are not thresholds the software enforces, and they do not silently change a model choice.

---

## Person scoring

**EAP**, **MAP** and **WLE** (Warm's weighted likelihood), each with a standard error. They shrink differently at the extremes and the choice matters when scores are reported to individuals: EAP and MAP pull the highest and lowest scorers towards the population mean, while WLE removes the first-order bias of maximum likelihood without a prior doing so, and stays finite for perfect and zero scores where plain ML diverges.

All three skip missing responses per cell. A respondent who answered nothing is not scored, rather than being handed the prior mean, which would be a number about the population wearing a person's name. The count of unscorable respondents is part of the score summary.

The estimator is chosen per run — `score_method` on the analysis request, defaulting to EAP — recorded on the run row, and stated in the report's notes along with what that choice costs. The pipeline reports a distribution summary rather than one row per respondent, because the full θ vector is a per-respondent result and does not belong inlined in every payload. v1 produced no person parameters at all: its ability-estimation function had no call sites.

---

## Data validation

The governing rule is **never silently repair data**. An item that cannot be modelled is dropped with a reason attached, not coerced into something fittable.

- **Non-numeric columns are rejected**, not alphabetised. Every polytomous model here treats categories as ordered, and alphabetical order is an arbitrary order, which for an ordered model is wrong rather than merely untidy. The message says to recode to integers before uploading.
- **Fractional responses are rejected.** A genuinely fractional score is not a category.
- **Constant items are dropped** — an item where every observed response is the same cannot discriminate.
- **Columns with more than 12 distinct values are dropped** as probable continuous measures: a raw score, an age, a timestamp. Refusing is safer than fitting a 40-category GRM that will not converge and will take an hour not doing so.
- **Categories are mapped by value**, numerically where the column is numeric, so a file whose first row happens to read 2, 0, 1 does not end up with an inverted scale.
- **Codes that do not start at zero are shifted**, with a note that says no category was removed — the 1–5 rating scale, which is how survey data usually arrives.
- **Codes with gaps are renumbered**, with a different note. A category nobody chose is not distinguishable from one that does not exist, so it is removed rather than estimated. The two are reported separately because they are different claims about the data, and a note asserting a removal that did not happen is exactly the kind of plausible falsehood the validation record exists to prevent.
- **Respondents who answered nothing are excluded**, with a count, so that a reported sample size means people who actually responded.
- **Item, ID and grouping columns are declared, never inferred.** v1 inferred, and would fit a respondent-ID column as an item.

Every one of these decisions is recorded as a note that reaches the report. Validation raises only when nothing usable survives.

---

## Reproducibility

Recorded on every run and carried into the report:

- **SHA-256 checksum** of the uploaded file
- **Engine version** — bumped whenever a change to the estimator or the diagnostics could move a number, so a stored run stays honestly attributable to the code that produced it
- **Seed** — one seed governs the cross-validation folds, the parallel-analysis simulation and the Q3 bootstrap
- **Requested models**, the fit outcome for each, and the timestamps
- **The full validation record** — dropped columns and their reasons, recodings, excluded respondents
- **The diagnostic failure list** — what was attempted and could not be computed, with reasons

The report is rendered from the persisted run alone. Nothing is recomputed at render time, so re-rendering an old run reproduces the old document rather than producing a fresh analysis wearing an old id.

---

## Deliberately not implemented

| | Why |
|---|---|
| A recommended or "best" model | The criteria disagree; resolving that silently hides the choice rather than making it |
| Cronbach's α | Assumes equal discriminations, which the fitted models deny |
| CFI / TLI for global fit | No defensible null model for a limited-information categorical statistic |
| Fixed RMSEA / SRMSR cutoffs | Derived under continuous normal-theory ML; RMSEA2 is test-length dependent |
| The eigenvalue-ratio > 4 rule | Never validated as a decision rule |
| A fixed \|Q3\| > 0.2 cutoff | Test-length dependent; the source paper recommends bootstrapping instead |
| A p-value for the 2PL-vs-3PL LRT | Boundary null; the statistic is not chi-square |
| p-values on infit/outfit mean-squares | A category error; the null distribution is not chi-square |
| The Vuong test | Held-out prediction answers the same question with one fewer approximation |
| Multidimensional IRT | Requires domain expertise to specify dimensions; misspecification risk is high |
| Computerised adaptive testing | Different product: item bank management and real-time scoring |
| Consequence analysis across models | Built: `psychometrics/consequence.py`. Per pair of models — score correlation and rank agreement, differences in sample-SD units after standardising each model's metric, a median SE ratio, and reclassification at illustrative selection rates with Cohen's κ. Verdict thresholds are stated as conventions, with the computed numbers beside them |

---

## Configuration

Application settings — database and Redis URLs, the secret key, upload caps, the CORS allowlist, session TTL and login throttling — are in `backend/app/core/config.py` and are read from the environment with the `IRTBOSS_` prefix. Two are enforced rather than documented: the development secret is rejected in production, and `*` is rejected as a CORS origin.

Statistical constants live with the code that uses them, in the module that owns the quantity, alongside the reasoning for the value. They are not exposed as user-facing settings. Changing one should be a reviewed diff with a justification in the commit, not a configuration change nobody sees.

---

## References

1. Orlando, M., & Thissen, D. (2000) — S-X² item fit
2. Maydeu-Olivares, A., & Joe, H. — limited-information M2 and RMSEA2
3. Cai, L., & Hansen, M. (2013) — M2\* for ordinal items
4. Christensen, K. B., Makransky, G., & Horton, M. (2017) — Q3\* and its critical value
5. Whittaker, T. A., Chang, W., & Dodd, B. G. (2012) — information criteria and the 3PL
6. Brown, G., Templin, J., & Cohen, A. (2015) — the boundary problem in IRT model comparison
7. Kang, T., & Cohen, A. S. (2007) — disagreement among selection criteria
8. Rodriguez, A., Reise, S. P., & Haviland, M. G. (2016) — ECV, PUC and ω<sub>h</sub>
9. Xia, Y., & Yang, Y. (2019) — fit indices under categorical estimation
10. Holland, P. W., & Thayer, D. T. — Mantel–Haenszel and the ETS classification
11. Swaminathan, H., & Rogers, H. J. — logistic-regression DIF
12. Thissen, D., Steinberg, L., & Wainer, H. — IRT likelihood-ratio DIF
13. Warm, T. A. (1989) — weighted likelihood estimation
14. AERA, APA, & NCME (2014) — *Standards for Educational and Psychological Testing*
15. International Test Commission — *Quality Control Guidelines*, §2.4.1
