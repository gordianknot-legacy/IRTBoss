# Sample Datasets

This directory contains example datasets for testing and learning IRTBoss.

## Available Datasets

### dichotomous_small.csv
- **Respondents**: 200
- **Items**: 20
- **Response type**: Binary (0/1)
- **Description**: Small dataset suitable for testing 1PL and 2PL models

### dichotomous_medium.csv
- **Respondents**: 500
- **Items**: 30
- **Response type**: Binary (0/1)
- **Description**: Medium dataset suitable for all models including 3PL

### polytomous_likert.csv
- **Respondents**: 300
- **Items**: 15
- **Response type**: 5-point Likert (1-5)
- **Description**: Polytomous data using a typical survey scale

## Data Generation

These datasets were generated using realistic IRT parameters:
- Item difficulties uniformly distributed from -2 to +2
- Item discriminations ranging from 0.5 to 2.0
- Ability distribution: standard normal N(0,1)

They represent "clean" data with no missing values and reasonable item properties.
For testing edge cases, you may want to:
- Introduce missing data
- Add items with extreme difficulty
- Include low-discrimination items

## Usage

Upload any of these files through the IRTBoss interface to explore the platform's features.

Example workflow:
1. Create a new project
2. Select "Low" stakes (for testing)
3. Upload `dichotomous_small.csv`
4. Review validation results
5. Fit models
6. Explore diagnostics and recommendations
