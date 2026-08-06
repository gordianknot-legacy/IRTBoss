# IRT Basics

A conceptual introduction to Item Response Theory for users of IRTBoss who do not have a psychometrics background. It covers the ideas the output refers to; [Modelling Decisions](./modeling-decisions.md) covers how they are computed here and why.

## What is IRT?

Item Response Theory is a family of statistical models describing how people respond to test items. Unlike classical test theory, which works with total scores, IRT models the probability of each response as a function of two things:

1. The respondent's standing on a latent trait, conventionally called theta (θ)
2. Properties of the item — its difficulty, how sharply it separates people, and so on

Both are estimated from the same response matrix, on the same scale, which is what makes the item-level statements possible.

## Why use it?

1. **Item-level insight** — how each individual item behaves, not just how the test scores
2. **Precision that varies by ability** — a test can measure sharply in the middle of the range and barely at all at the top, and IRT shows you that; a single reliability coefficient hides it
3. **Test design** — build a form with known measurement properties over the range you care about
4. **Comparability** — place different forms on a common scale
5. **Quality assurance** — identify items that are not working, and items that work differently for different groups

## The core idea

```
P(response | θ, item parameters) = a function of θ and the item parameters
```

For a right/wrong item, the probability of a correct response rises with θ. That relationship is the **Item Characteristic Curve (ICC)**. For an item with ordered categories, each category has its own curve, and they sum to one at every θ.

## The dichotomous models

### Rasch

Every item has one parameter, its **difficulty (b)**. All slopes are fixed at 1 and the variance of the latent trait is estimated instead.

Good when items were written to a common standard, when interval-level measurement and specific objectivity matter to you, or when the sample is small. The Rasch tradition treats the model as prescriptive: misfit indicts the items, not the model.

### 1PL

Also one parameter per item, but here a single **common discrimination** is estimated across all items and the latent variance is fixed at 1.

Rasch and the 1PL are not the same model, and IRTBoss keeps them separate. They have the same number of free parameters and place items on different metrics, so neither is nested in the other and no likelihood-ratio test between them is defined.

### 2PL

Adds a per-item **discrimination (a)**: how steeply the probability changes with θ.

Realistic for most tests, since items genuinely vary in how well they measure the construct. Fitting a 2PL is an explicit statement that discriminations differ, which has consequences elsewhere — it is the reason Cronbach's α is not reported.

### 3PL

Adds a **lower asymptote (c)**, usually read as guessing: the probability a respondent far below the item's difficulty still answers correctly.

Appropriate for multiple-choice items where guessing is plausible. It is also the hardest of the four to estimate: `c` is weakly identified and needs both many items and many respondents. IRTBoss fits it under a Beta(5, 17) prior on `c` for that reason, and says so in the output.

## The polytomous models

For items with more than two ordered categories — Likert scales, partial credit, rubric scores.

### GRM (graded response model)

Models the *cumulative* probabilities: for each category boundary, the probability of scoring at or above it. Each item has one discrimination and a set of ordered boundary locations. The natural choice for rating scales.

### PCM (partial credit model)

Models the probability of each step being taken given that the previous one was, with the discrimination fixed at 1 — the polytomous member of the Rasch family. Each item has a set of step parameters, which need not be ordered.

### GPCM (generalised partial credit model)

The PCM with a free discrimination per item.

The GRM and the GPCM are not nested in each other. They are different link functions on the same categories, so neither an ordinary likelihood-ratio test nor a naive information-criterion difference has a distribution to be read against. This is one of the reasons the comparison here is built on held-out prediction.

## Reading item parameters

### Difficulty (b)

On the θ metric, typically between −4 and +4. Higher means harder; b = 0 is around average for a standard-normal population.

For polytomous items, the analogous quantities are the boundary or step locations, one per category transition.

### Discrimination (a)

Roughly 0.5 to 2.5 in practice. Higher means the item separates ability levels more sharply, and contributes more information over a narrower band. Very low discrimination means the item is close to uninformative. Very high values are worth checking rather than celebrating: they can indicate an item that duplicates another, or an estimation problem.

### Guessing (c)

The floor of the curve. For a four-option multiple-choice item, chance is 0.25. Because c = 0 sits on the boundary of the parameter space, an estimated c above zero is the normal outcome even for data generated without guessing, so a non-zero estimate is not by itself evidence that guessing occurred.

### Standard errors

Every estimate above ships with one. A difficulty of 1.2 with a standard error of 0.08 and a difficulty of 1.2 with a standard error of 0.60 are very different findings, and only one of them supports an item-level decision.

## The Item Characteristic Curve

Probability on the vertical axis, θ on the horizontal.

- **Location** — where the curve rises is set by difficulty
- **Steepness** — set by discrimination
- **Lower asymptote** — set by guessing, if the model has one
- The curve crossing 0.5 is roughly the difficulty for a 2PL; for a 3PL that crossing sits above b

An **empirical ICC overlay** — observed proportions plotted against the model's curve — is the fastest way to see what a fit statistic is objecting to.

## Test Information and standard error

The **Test Information Function (TIF)** shows how much information the test provides at each θ. Information is additive over items, and each item contributes most near its own difficulty.

```
SE(θ) = 1 / sqrt(I(θ))
```

So high information means a small standard error, and the shape of the TIF *is* the precision profile of the test. Read three things from it:

- **Where it peaks** — where the test measures best
- **How high it peaks** — how precisely
- **How wide it is** — over what range measurement is usable

A test whose information collapses above θ = 1 cannot support decisions about high scorers, however good its overall reliability looks.

## Reliability

IRTBoss reports several figures rather than one, because they answer different questions.

- **Marginal reliability (Bayesian)** — one minus the expected posterior error variance over the trait distribution. Matches EAP and MAP scores. Bounded above by the trait variance, and the figure to quote when this platform's scores are used.
- **Marginal reliability (information-based)** — the classical test-information form, matching ML or WLE scores. Unbounded where the test carries little information, so it can be far lower and, for a 3PL, can be dominated by the low-ability tail. That instability is itself a finding.
- **Empirical reliability** — computed from the observed sample's scores and their realised standard errors. It diverges from the model-implied figure whenever the sample departs from the assumed trait distribution, which is most real data.
- **McDonald's ω** — the internal-consistency supplement, from the model-implied loadings.
- **Conditional standard error and precision bands** — the standard error across the θ range, and the contiguous ranges over which the test meets a given precision bar.

Conventionally, below 0.70 is inadequate for most purposes, 0.80–0.90 is adequate for many, and individual high-stakes decisions are usually held to 0.90. Treat these as conventions, not thresholds the software enforces, and read the conditional profile before quoting any of them.

Cronbach's α is not reported. It is exact only under equal item discriminations, which fitting a 2PL, GRM or GPCM explicitly denies.

## Person scores

Three estimators, offered because they fail in different directions:

- **EAP** (posterior mean) — always finite, lowest average error, but shrinks the highest and lowest scorers towards the population mean. Fine for group-level work.
- **MAP** (posterior mode) — shares EAP's shrinkage.
- **WLE** (Warm's weighted likelihood) — removes the first-order bias of maximum likelihood without a prior pulling scores inward, and stays finite for perfect and zero scores where plain ML diverges. The right default when scores are reported back to individuals.

A respondent who answered nothing is reported as unscored rather than assigned the prior mean, which would be a number about the population wearing a person's name.

## Fit: does the model describe the data?

### Item fit

- **S-X²** — compares observed and model-expected proportions within groups defined by the score on every *other* item. Conditioning on an observed score rather than an estimated θ is what makes it a genuine chi-square.
- **Infit and outfit mean-square** — average squared standardised residuals, information-weighted and unweighted. Reported as effect sizes only; no p-value is attached to a mean-square, because that is a category error, and the familiar 0.5–1.5 range holds only at modest sample sizes.
- **RMSD** — distance between observed and expected category curves, on the probability scale. Unlike the other two it does not grow with sample size, so it answers "how wrong is this item?" rather than "how sure are we that it is wrong at all?"

At large N every item will fail a significance test. That is a property of the test, not of your items, and it is why effect sizes are ranked alongside p-values with the sample size stated.

### Global fit

**M2** (binary) and **M2\*** (ordinal) test the low-order marginals — the univariate proportions and the bivariate cross-products — rather than the full response-pattern table, which is far too sparse to have a usable reference distribution. Reported with **RMSEA2** and a confidence interval, and with **SRMSR**.

No pass/fail verdict is attached. The conventional cutoffs come from continuous, normally distributed data in covariance-structure models, and RMSEA2 in particular falls as items are added at constant misspecification, so a fixed cutoff is implicitly a cutoff on test length.

## Assumptions

Every unidimensional IRT model rests on two things the data has to be asked about.

### Unidimensionality

One latent trait accounts for the covariation among items. If two traits are present, the single θ scale is a blend of them and every parameter, curve and reliability figure describes a construct nobody defined.

Assessed from the **polychoric** correlation matrix rather than the Pearson matrix — Pearson correlations between coarse categories are attenuated by the coarseness itself and produce spurious "difficulty factors" that group items by p-value rather than content. The evidence is parallel analysis, Velicer's MAP, and a bifactor ECV / PUC / ω<sub>h</sub> approximation. They are reported together because they fail differently, and agreement between them is what carries weight.

### Local independence

Conditional on θ, responses are independent. When a pair of items shares something the trait does not explain — a common stimulus, a cue in one that gives away another — that pair effectively counts as less than two items, so test information is overstated and reliability inflated, in the direction that flatters the test.

Assessed with **Q3\***, Yen's Q3 corrected for its structural negative bias, against a critical value obtained by parametric bootstrap for your dataset rather than a fixed cutoff.

## DIF

Differential item functioning asks whether two respondents at the *same* trait level, drawn from different groups, have the same chance of a given response. It is not the question of whether the groups differ overall — that is impact, and it is usually a fact about the world rather than a defect in the item.

Three methods are reported because each is blind to something the others see: Mantel–Haenszel with the ETS A/B/C classification (blind to non-uniform DIF), logistic regression (which sees the interaction Mantel–Haenszel cannot), and an IRT likelihood-ratio test with anchor purification (which matches on the latent trait rather than a fallible observed score).

DIF is a screen, not a verdict. A flag means the item behaves differently between groups conditional on the trait; whether that is bias depends on what the item is asking.

## Common findings and what they mean

**Low discrimination.** The item contributes little; it may be poorly written, or measuring something other than the target construct.

**Extreme difficulty.** The item gives information only for people at the extreme, and may indicate a mismatch with the population. Not necessarily a defect.

**High estimated guessing.** Distractors may be too obviously wrong, or the item may have more than one defensible answer. Remember that the estimate is bounded below by zero and biased upward near it.

**Misfit on S-X² with a small RMSD.** Very likely a large-sample artefact rather than a problem with the item.

**Non-convergence.** The fit produced nothing, and nothing is reported for it. Usually too few respondents for the family requested, items without variance, or a heavy missing rate.

## How IRTBoss uses all this

1. **Validates** your data, refusing what cannot be modelled rather than repairing it
2. **Fits** the model families you requested, with standard errors, and reports non-convergence as non-convergence
3. **Compares** them on held-out predictive log-likelihood, with information criteria and valid likelihood-ratio tests alongside
4. **Reports the disagreement** between criteria rather than resolving it, and refuses to name a winner where the data do not separate the candidates
5. **Diagnoses** item fit, global fit, assumptions, DIF and precision, each with its own uncertainty or its own stated limits
6. **Renders** the whole picture as a document, from persisted data only

You do not have to do the mathematics. You do have to make the judgements, which is why the output gives you evidence rather than verdicts.

## Further reading

- Embretson, S. E., & Reise, S. P. — *Item Response Theory for Psychologists*
- Baker, F. — *The Basics of Item Response Theory* (freely available)
- van der Linden, W. J., & Hambleton, R. K. — *Handbook of Modern Item Response Theory*
- AERA, APA, & NCME (2014) — *Standards for Educational and Psychological Testing*
