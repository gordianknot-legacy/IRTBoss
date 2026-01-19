# Data Schema

This document describes the required format for response data in IRTBoss.

## Overview

IRTBoss accepts response data in CSV format with a specific structure:
- **Rows** represent respondents (test-takers)
- **Columns** represent items (questions)
- **Values** represent responses

## File Format

### Requirements

- **Format**: CSV (Comma-Separated Values)
- **Encoding**: UTF-8
- **Headers**: First row must contain item identifiers
- **Size**: No explicit limit, but files over 100MB may be slow

### Example: Dichotomous Data

```csv
item_1,item_2,item_3,item_4,item_5
1,0,1,1,0
0,0,1,0,1
1,1,1,1,1
0,1,0,1,0
1,1,0,0,1
```

### Example: Polytomous Data

```csv
q1,q2,q3,q4,q5
4,3,2,4,3
2,2,1,3,2
5,4,4,5,4
1,2,3,2,1
3,3,3,3,3
```

## Response Values

### Dichotomous (Binary) Responses

For correct/incorrect or agree/disagree:
- `0` = incorrect / disagree / no
- `1` = correct / agree / yes

Other binary codings (e.g., 1/2) will be automatically recoded to 0/1.

### Polytomous (Ordinal) Responses

For Likert scales or partial credit:
- Values should be consecutive integers starting from 0 or 1
- Example 5-point scale: 1, 2, 3, 4, 5
- Example 4-point scale: 0, 1, 2, 3

All items must use the same scale within a dataset.

### Missing Data

Missing responses can be represented as:
- Empty cells
- `NA`
- `NaN`
- Blank strings

Missing data is handled using maximum likelihood estimation (not listwise deletion).

## Item Identifiers

Column headers serve as item identifiers:
- Must be unique
- Should be descriptive but concise
- Avoid special characters except underscores
- Examples: `item_1`, `q15`, `reading_comp_3`

## Data Quality Requirements

### Minimum Sample Size

| Model | Minimum | Recommended |
|-------|---------|-------------|
| 1PL   | 100     | 300+        |
| 2PL   | 100     | 500+        |
| 3PL   | 500     | 1000+       |

### Minimum Items

- At least 5 items required
- 10+ items recommended for reliable estimation

### Missing Data Limits

| Level        | Threshold | Consequence        |
|--------------|-----------|-------------------|
| Per item     | 20%       | Warning           |
| Per person   | 30%       | Warning           |
| Total        | 10%       | Error             |

### Item Variance

- Items must have response variance
- Items where everyone gives the same answer cannot be analyzed

## Validation Process

When you upload data, IRTBoss automatically:

1. **Parses** the CSV file
2. **Detects** the response type (dichotomous vs polytomous)
3. **Counts** respondents and items
4. **Calculates** missing data percentages
5. **Checks** for zero-variance items
6. **Identifies** extreme items (too easy/hard)
7. **Validates** sample size for requested models

You'll receive immediate feedback with:
- Summary statistics
- Warnings for potential issues
- Errors for critical problems

## Common Issues

### Non-Numeric Values

**Problem**: Cells contain text like "yes", "no", "N/A"

**Solution**: Recode to numeric values before upload:
- "yes" → 1
- "no" → 0
- "N/A" → leave empty for missing

### Inconsistent Coding

**Problem**: Some items use 0/1, others use 1/2

**Solution**: Standardize all items to the same scale before upload.

### Extra Columns

**Problem**: File includes respondent IDs, demographics, or other non-response data

**Solution**: Remove all non-response columns. The file should only contain item responses.

### Respondent Identifiers

**Problem**: First column contains IDs like "student_001"

**Solution**: Remove the ID column. If you need to match results back to respondents, keep a separate mapping file.

## Best Practices

1. **Clean your data** before upload:
   - Remove non-response columns
   - Handle missing data consistently
   - Verify coding schemes

2. **Use clear item names**:
   - `math_01` instead of `1`
   - `reading_comp` instead of `item`

3. **Document your coding**:
   - Keep a codebook separate from the data
   - Record what each response value means

4. **Preserve originals**:
   - Keep your original data file unchanged
   - Create a clean copy for IRTBoss

## Sample Files

Example datasets are available in the `examples/sample_datasets/` directory:

- `dichotomous_small.csv`: 200 respondents, 20 items, binary
- `dichotomous_medium.csv`: 500 respondents, 30 items, binary
- `polytomous_likert.csv`: 300 respondents, 15 items, 5-point scale

These can be used to explore the platform before using your own data.
