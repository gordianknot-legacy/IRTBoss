# Modeling Decisions

This document explains the technical decisions and rationale behind IRTBoss's model selection and recommendation logic.

## Design Philosophy

IRTBoss is **opinionated by design**. We make decisions on behalf of users based on psychometric best practices, rather than exposing every possible option. This section explains our rationale.

## Model Selection

### Criteria Used

We compare models using:

1. **BIC (Bayesian Information Criterion)**: Primary criterion
2. **AIC (Akaike Information Criterion)**: Secondary criterion
3. **Convergence status**: Models must converge
4. **Sample size constraints**: Complex models need more data

### Why BIC Over AIC?

BIC penalizes model complexity more heavily than AIC:

```
AIC = -2 * log_likelihood + 2 * k
BIC = -2 * log_likelihood + k * log(n)
```

Where k = number of parameters, n = sample size.

For assessment contexts, we prefer BIC because:
- It's more conservative (less likely to overfit)
- It's consistent (selects true model as n → ∞)
- Assessment requires stable, interpretable models

### Meaningful Differences

We require a BIC difference of at least 10 before preferring a more complex model:

```python
BIC_DIFFERENCE_MEANINGFUL = 10.0
```

This follows standard interpretation:
- Δ BIC < 2: Negligible difference
- Δ BIC 2-6: Positive evidence for lower BIC
- Δ BIC 6-10: Strong evidence
- Δ BIC > 10: Very strong evidence

### Sample Size Constraints

We apply hard constraints based on psychometric simulation research:

| Model | Minimum (error) | Warning | Recommended |
|-------|-----------------|---------|-------------|
| 1PL   | 100            | 200     | 300         |
| 2PL   | 100            | 250     | 500         |
| 3PL   | 500            | 500     | 1000        |

The 3PL is particularly sensitive because:
- Guessing parameters require many low-ability respondents
- With small samples, guessing is confounded with difficulty
- Simulation studies show instability below n=500

### Context-Specific Adjustments

For high-stakes assessments, we increase conservatism:

```python
if stakes == HIGH and selected == TWO_PL:
    if bic_diff < BIC_DIFFERENCE_MEANINGFUL * 2:
        selected = RASCH
```

Rationale:
- High-stakes decisions need stable, auditable results
- The Rasch model produces interval-level measurements
- Simpler models are easier to defend to stakeholders

## Item Parameter Thresholds

### Discrimination

```python
MIN_DISCRIMINATION = 0.25  # Flag if below
MAX_DISCRIMINATION = 4.0   # Flag if above
```

Items with a < 0.25:
- Contribute little to measurement
- May be measuring something else
- Recommend review/removal

Items with a > 4.0:
- May indicate estimation issues
- Possibly too similar to other items
- Recommend verification

### Difficulty

```python
MIN_DIFFICULTY = -4.0  # Extremely easy
MAX_DIFFICULTY = 4.0   # Extremely hard
```

Items at extremes:
- Provide information only for extreme respondents
- May indicate poor match with target population
- Recommend review for construct alignment

### Guessing

```python
MAX_GUESSING = 0.35  # Flag if above
```

High guessing (c > 0.35):
- Distractors may be too obviously wrong
- May indicate item quality issues
- Compare to theoretical chance (1/options)

## Reliability Thresholds

Based on professional standards (AERA, APA, NCME):

```python
MIN_RELIABILITY_LOW_STAKES = 0.70
MIN_RELIABILITY_MEDIUM_STAKES = 0.80
MIN_RELIABILITY_HIGH_STAKES = 0.90
```

These are marginal reliabilities computed from test information.

## Data Quality Thresholds

### Missing Data

```python
MAX_MISSING_PER_ITEM = 0.20       # Warning
MAX_MISSING_PER_RESPONDENT = 0.30 # Warning
MAX_MISSING_TOTAL = 0.10          # Error
```

Rationale:
- Per-item > 20%: Item may have been skipped systematically
- Per-person > 30%: Respondent engagement questionable
- Total > 10%: Too much information missing for reliable estimation

### Item Means (Dichotomous)

```python
MAX_ITEM_MEAN = 0.95  # Too easy
MIN_ITEM_MEAN = 0.05  # Too hard
```

Items at ceiling/floor:
- Little variance means little information
- May indicate mismatch with population
- Not necessarily bad, but flag for review

## Estimation Methodology

### Algorithm

We use the Expectation-Maximization (EM) algorithm via R's `mirt` package:

```python
estimation_method = "EM"
max_iterations = 500
convergence_threshold = 0.001
quadrature_points = 61
```

EM was chosen over alternatives (MHRM, MCMC) because:
- Well-understood convergence properties
- Deterministic (reproducible)
- Fast for typical assessment sizes

### Ability Estimation

We default to EAP (Expected A Posteriori):

```python
default_scoring_method = "EAP"
```

EAP advantages:
- Accounts for uncertainty via posterior distribution
- Less biased than ML for extreme scores
- Standard practice in operational assessment

## Reproducibility

Every analysis includes:

```python
@dataclass
class ReproducibilityMetadata:
    software_version: str
    model_type: str
    fitting_timestamp: datetime
    data_hash: str  # SHA-256 of input
    random_seed: Optional[int]
    convergence_settings: dict
```

This enables:
- Audit trails for high-stakes use
- Debugging when results seem unexpected
- Replication for research purposes

## Rationale for Not Including

### Multidimensional IRT

Not included in MVP because:
- Requires domain expertise to specify dimensions
- Model selection becomes much more complex
- Risk of misspecification is high

### DIF Analysis

Deferred because:
- Requires demographic data we don't collect
- Interpretation requires expertise
- False positive risk without proper training

### Adaptive Testing

Out of scope because:
- Requires item bank management
- Real-time scoring infrastructure
- Different product category entirely

## References

Our thresholds and decisions are based on:

1. Embretson, S. E., & Reise, S. P. (2000). *Item Response Theory for Psychologists*
2. de Ayala, R. J. (2009). *The Theory and Practice of Item Response Theory*
3. AERA, APA, & NCME (2014). *Standards for Educational and Psychological Testing*
4. Simulation studies on sample size requirements (various)

## Modifying Thresholds

These thresholds are defined in `backend/app/core/config.py`.

While we intentionally don't expose these to end users, enterprise deployments may need customization. Any modifications should be:
- Documented with rationale
- Validated through simulation
- Reviewed by qualified psychometricians
