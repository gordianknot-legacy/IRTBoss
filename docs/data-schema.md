# Data Schema

What IRTBoss accepts, what it refuses, and why it refuses rather than repairs.

## Overview

Response data is a CSV:

- **Rows** are respondents
- **Columns** are items, plus any respondent-identifier or grouping columns you declare
- **Values** are integer response codes

Ingest and validation are separate steps, deliberately. Ingest records what values it saw in each column but does not act on them, because deciding that `{0, 1, 2}` means three ordered categories is a measurement judgement rather than a parsing one. That judgement is made once, in validation, and every decision it makes is recorded as a note that reaches the report.

## File format

- **Format**: CSV, parsed with pandas defaults
- **Encoding**: UTF-8
- **Headers**: the first row holds column names, which become item identifiers
- **Size cap**: 25 MiB by default. The body is streamed and rejected the moment it exceeds the cap — before parsing, before it is written to disk.
- **Shape caps**: 100,000 rows and 1,000 columns by default, applied after parsing so a small file cannot expand into a 100,000-column frame

The caps are settings (`IRTBOSS_MAX_UPLOAD_BYTES`, `IRTBOSS_MAX_ROWS`, `IRTBOSS_MAX_COLUMNS`) rather than constants buried in a route.

### Example: dichotomous data

```csv
item_1,item_2,item_3,item_4,item_5
1,0,1,1,0
0,0,1,0,1
1,1,1,1,1
0,1,0,1,0
```

### Example: polytomous data with an ID and a grouping column

```csv
respondent,gender,q1,q2,q3,q4,q5
S001,F,4,3,2,4,3
S002,M,2,2,1,3,2
S003,F,5,4,4,5,4
```

Uploaded with `id_column = "respondent"` and `group_columns = ["gender"]`, leaving `q1`–`q5` as the items.

## Column roles

Roles are **declared at upload, never inferred**:

| Parameter | Meaning |
|---|---|
| `id_column` | An optional respondent identifier. Excluded from the item set. |
| `group_columns` | Optional grouping variables, as a JSON array of column names. Excluded from the item set and available to the DIF screen. |
| *(everything else)* | Item columns |

A declared column that is not in the file is an error, as is a file with no item columns left after the exclusions. v1 inferred column roles and would happily fit a respondent-ID column as an item, producing a "result" for it.

You do not need to strip demographics or IDs before uploading. You need to name them.

## Response values

### Dichotomous

`0` / `1` is the usual coding. Any two distinct integer values work: categories are mapped by **value**, in numeric order, so `1`/`2` becomes `0`/`1` with the ordering preserved.

### Polytomous

Consecutive integers, in either a 0-based or 1-based scheme — a 5-point scale as `1..5` or a 4-point one as `0..3`. Values map to 0-based category codes in numeric order.

Items do **not** have to share a scale within a dataset; the category count is recorded per item.

Ordering is by value rather than by order of appearance, and this matters more than it looks. Every polytomous model here treats categories as ordered, so mapping them in the order they happened to appear in the file would silently permute the scale and produce thresholds describing nothing.

### Missing data

Recognised as missing: empty cells and the tokens pandas treats as null (`NA`, `NaN`, `null`, and the rest of its default set).

Missing responses are handled by **full-information maximum likelihood**: each respondent contributes the items they answered, and nothing is imputed. There is no listwise deletion at estimation.

The one exception is the DIF screen, which needs a comparable matching score for every respondent, so incomplete response vectors are excluded there. They are excluded from all three DIF methods rather than from some, so that every DIF statistic describes the same people, and the count is reported.

## Item identifiers

Column headers become item identifiers. They should be unique and descriptive: `item_01`, `q15`, `reading_comp_3`. They are rendered into the HTML report, which is autoescaped, so an unusual header is a legibility problem rather than a safety one.

## What validation refuses

The governing rule is that data is never silently repaired. Each of the following removes a column with a stated reason that reaches the report, rather than coercing it into something fittable:

| Condition | Outcome |
|---|---|
| Column is not numeric | **Rejected.** A non-numeric column has no defensible order, and alphabetical order is an arbitrary one — for an ordered model, wrong rather than merely untidy. Recode to integers before uploading. |
| Values are not whole numbers | **Rejected.** A fractional score is not a category. |
| Every observed response is identical | **Dropped.** The item cannot discriminate. |
| Every response is missing | **Dropped.** |
| More than 12 distinct values | **Dropped.** Far more likely a misidentified continuous measure — a raw score, an age, a timestamp — than a genuine rating scale. Refusing is safer than fitting a 40-category GRM that will not converge and will spend an hour not converging. |
| Response codes are consecutive but do not start at 0 — the 1–5 rating scale | **Shifted** to 0-based codes, with a note saying so and stating that no category was removed. |
| Response codes have gaps | **Renumbered**, with a note. A category nobody chose is not distinguishable from one that does not exist, so it is removed rather than estimated. Reported separately from the case above: telling a user their scale lost a category when it did not is the same defect as failing to tell them when it did. |
| Respondent answered no items at all | **Excluded**, with a count, so that a reported sample size means people who actually responded. |

Validation raises only when nothing usable survives — no item columns, no respondents, or every column dropped. Everything salvageable is salvaged, and everything discarded to get there is listed.

Note what is *not* in that table: v1's automatic recoding of "other binary codings" and its advice to hand-recode text to numbers before upload remain the right advice, but the platform now tells you it refused rather than guessing on your behalf.

## Sample size

There are no hardcoded minimum-sample gates on fitting. What exists instead:

| Requirement | Where it applies |
|---|---|
| At least 3 items | Dimensionality assessment |
| At least `2 × folds` respondents (10 at the default 5 folds) | Cross-validated model comparison |
| At least 100 respondents per group | DIF; below it the statistics are `None` with the reason stated |
| Roughly 60 items × 1,000 respondents, or 30 × 2,000 | Stable 3PL estimation. Reported as a caveat on the comparison, not a hard exclusion. |

These are floors for a statistic to be computable, not guidance on what sample you need. As a rule of thumb, a 2PL wants a few hundred respondents and the 3PL wants both a long test and a large sample; the standard errors on your parameters will tell you more about whether you had enough than any threshold table.

More items than respondents, or very sparse data, will usually show up as non-convergence — which is reported as non-convergence, with no parameters attached.

## What ingest records

For every upload:

- SHA-256 checksum of the raw bytes
- Size in bytes, and the parsed shape
- The full column list, the item columns, the declared ID column and grouping columns
- The distinct non-missing values observed in each item column (capped for storage)

The checksum, the engine version and the analysis seed are carried into the report, which is the reproducibility metadata v1 promised in three documents and delivered in none.

## Sample files

`examples/sample_datasets/` contains four simulated datasets, each generated by `backend/scripts/generate_sample_datasets.py` from `backend/app/irt/simulate.py`:

| File | Respondents | Items | Responses | Generated from |
|---|---|---|---|---|
| `dichotomous_small.csv` | 200 | 20 | 0/1 | 2PL |
| `dichotomous_medium.csv` | 500 | 30 | 0/1 | 3PL |
| `polytomous_likert.csv` | 300 | 15 | 1–5, 6% missing | GRM |
| `dichotomous_dif.csv` | 800 | 20 | 0/1, `respondent_id` + `group` | 2PL, DIF planted on three items |

The generating parameters are in a sibling `<name>.parameters.csv` for each, and `MANIFEST.json` records the seed, shape and SHA-256 of every file — checked by `backend/tests/test_sample_datasets.py`, so a hand-edited example fails the suite rather than silently outliving its documentation.

They are still examples rather than validation data: they exercise the platform, and the estimator's correctness is the job of `backend/tests/validation/`. Two of them are deliberately instructive about their own limits — `dichotomous_medium.csv` carries real lower asymptotes that a 3PL fit at n = 500 cannot recover, and `dichotomous_dif.csv` has no group difference in the trait distribution, which is the best case for Mantel-Haenszel rather than a representative one. See the README in that directory.

## Best practices

1. **Declare, do not delete.** Keep your ID and demographic columns in the file and name them at upload; you will want the grouping columns for the DIF screen.
2. **Recode before uploading** if your responses are text. The platform will refuse them, correctly, but it cannot know that "Strongly agree" outranks "Agree".
3. **Read the validation notes** on the run before reading anything else. They tell you which columns took no part in any statistic below.
4. **Keep a codebook** separate from the data recording what each response value means. The platform preserves your ordering; it cannot preserve your meaning.
5. **Keep the original file unchanged** and upload a clean copy. The checksum on the run refers to what you uploaded.
