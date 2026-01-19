# IRT Basics

This document provides a conceptual introduction to Item Response Theory (IRT) for users of IRTBoss who may not have a psychometrics background.

## What is IRT?

Item Response Theory is a family of statistical models that describe how people respond to test items. Unlike classical test theory (which focuses on total scores), IRT models the probability of a correct response based on:

1. The respondent's ability (often called "theta" or θ)
2. Characteristics of the item (difficulty, discrimination, etc.)

## Why Use IRT?

IRT offers several advantages over simpler approaches:

1. **Item-level insight**: Understand how individual items function
2. **Ability estimation**: Get more precise estimates of what respondents know
3. **Test design**: Build tests with known measurement properties
4. **Comparability**: Compare scores across different test forms
5. **Quality assurance**: Identify items that aren't working well

## The Core Concept

In IRT, we model the probability of a correct response as a function of ability:

```
P(correct | θ, item parameters) = some function of θ and item parameters
```

As ability increases, the probability of a correct response increases. This relationship is captured by the Item Characteristic Curve (ICC).

## The Three Main Models

### 1PL (Rasch) Model

The simplest IRT model. Each item has one parameter:

- **Difficulty (b)**: The ability level where P(correct) = 0.5

Assumes all items are equally good at discriminating between ability levels. Best when:
- Items are carefully constructed to similar standards
- You need easily interpretable results
- Sample size is limited (200-300 respondents)

### 2PL Model

Adds discrimination to the Rasch model:

- **Difficulty (b)**: Where P(correct) = 0.5
- **Discrimination (a)**: How steeply probability changes with ability

More realistic for most tests, as items naturally vary in quality. Best when:
- Items vary in how well they measure the construct
- Sample size is moderate (300-500+ respondents)
- You need more accurate fit to real data

### 3PL Model

Adds guessing for multiple-choice items:

- **Difficulty (b)**: Where P(correct) = 0.5 (adjusted for guessing)
- **Discrimination (a)**: Steepness of the curve
- **Guessing (c)**: Probability of correct response at very low ability

Appropriate when low-ability respondents might guess correctly. Best when:
- Items are multiple-choice
- Guessing is a realistic concern
- Sample size is large (500+ respondents)

## Understanding Item Parameters

### Difficulty (b)

- Measured on the same scale as ability (typically -4 to +4)
- Higher values = harder items
- b = 0 means average difficulty
- b = -2 is easy; b = 2 is hard

Example interpretation:
- b = -1.5: Easy item, most people get it right
- b = 0: Average difficulty
- b = 2.0: Hard item, only high-ability people get it right

### Discrimination (a)

- Typically ranges from 0.5 to 2.5
- Higher values = item better differentiates abilities
- Low discrimination (< 0.5) = item is essentially random
- Very high (> 3.0) may indicate estimation issues

Example interpretation:
- a = 0.4: Poor discrimination, item doesn't help much
- a = 1.0: Typical, decent item
- a = 2.0: Excellent discrimination

### Guessing (c)

- Ranges from 0 to about 0.35
- Represents the "floor" probability
- For 4-option multiple choice, theoretical chance = 0.25

Example interpretation:
- c = 0.15: Low guessing, good distractors
- c = 0.30: High guessing, weak distractors

## The Item Characteristic Curve (ICC)

The ICC is a graph showing the probability of a correct response (y-axis) across ability levels (x-axis). Key features:

1. **Shape**: S-curve (ogive) that increases with ability
2. **Location**: Determined by difficulty (b)
3. **Steepness**: Determined by discrimination (a)
4. **Lower asymptote**: Determined by guessing (c), if present

Reading an ICC:
- Find where the curve crosses 0.5 → that's roughly the difficulty
- Steeper curve → higher discrimination
- Curve doesn't reach 0 → there's a guessing parameter

## Test Information Function (TIF)

The TIF shows how much "information" (measurement precision) the test provides at each ability level.

Key concepts:
- Information is highest where items are most discriminating
- Standard error of measurement = 1 / √(Information)
- A good test has high information across the target range

Interpreting the TIF:
- Peak location: Where the test measures best
- Peak height: How precise measurement is at its best
- Width: Range of abilities measured well

## Reliability in IRT

Marginal reliability is analogous to classical reliability:
- Based on test information across the ability distribution
- Typically 0.70-0.95 for good tests
- Higher is better, but diminishing returns above 0.90

## Common Issues and What They Mean

### Low Discrimination

Item doesn't differentiate abilities well:
- May be poorly written
- May measure something other than the target construct
- Consider revising or removing

### Extreme Difficulty

Item is too easy or too hard:
- Provides little information for most respondents
- May indicate mismatch with target population
- Consider revising or replacing

### High Guessing

Low-ability respondents answer correctly too often:
- Distractors may be obviously wrong
- Item may have multiple defensible answers
- Consider improving distractors

### Non-Convergence

Model estimation didn't complete successfully:
- Usually indicates data problems
- Check sample size
- Check for items with no variance
- Check for excessive missing data

## How IRTBoss Uses IRT

IRTBoss automates the IRT workflow:

1. **Detects** your data structure and response type
2. **Fits** appropriate models (1PL, 2PL, and sometimes 3PL)
3. **Compares** models using statistical criteria
4. **Recommends** the best model for your context
5. **Flags** items that may need attention
6. **Reports** results in plain language

You don't need to understand the math. Trust the recommendations, review the flags, and focus on improving your assessment.

## Further Reading

For deeper understanding:
- *Item Response Theory for Psychologists* by Embretson & Reise
- *The Basics of Item Response Theory* by Frank Baker (free online)
- *Handbook of Modern Item Response Theory* by van der Linden & Hambleton
