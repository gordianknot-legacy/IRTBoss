# Getting Started with IRTBoss

This guide will help you set up IRTBoss and run your first IRT analysis.

## Prerequisites

- Python 3.10 or later
- R 4.0 or later (with the `mirt` package)
- Node.js 18+ (for frontend development)
- Docker (optional, for containerized deployment)

## Installation

### Backend Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/irtboss.git
   cd irtboss
   ```

2. Create a Python virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install backend dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

4. Install R and the mirt package:
   ```R
   install.packages("mirt")
   install.packages("jsonlite")
   ```

5. Start the backend server:
   ```bash
   uvicorn app.main:app --reload
   ```

   The API will be available at `http://localhost:8000`.

### Frontend Setup

1. Install frontend dependencies:
   ```bash
   cd frontend
   npm install
   ```

2. Start the development server:
   ```bash
   npm run dev
   ```

   The frontend will be available at `http://localhost:3000`.

## Quick Start: Your First Analysis

### 1. Prepare Your Data

Your response data should be in CSV format:
- Rows represent respondents
- Columns represent items
- Values should be integers (0/1 for dichotomous, 0-n for polytomous)

Example (`responses.csv`):
```csv
item_1,item_2,item_3,item_4,item_5
1,0,1,1,0
0,0,1,0,1
1,1,1,1,1
0,1,0,1,0
...
```

### 2. Create a Project

Navigate to the dashboard and click "New Project". Provide:
- **Project name**: A descriptive name
- **Stakes level**: How high-stakes is this assessment?
  - Low: Classroom quizzes, practice tests
  - Medium: Course grades, placement tests
  - High: Certification, licensure
- **Intended use**: How will the results be used?
  - Research: Academic research, exploratory
  - Operational: Regular use in production
  - Certification: High-stakes decisions

### 3. Upload Data

Upload your CSV file. The system will automatically:
- Detect the number of items and respondents
- Determine if responses are dichotomous or polytomous
- Check for data quality issues
- Provide warnings if sample size is concerning

### 4. Review Data Validation

Before fitting models, review the validation results:
- Are all items detected correctly?
- Are there any data quality warnings?
- Is the sample size adequate?

### 5. Fit Models

Click "Fit Models" to start the analysis. The system will:
- Fit 1PL (Rasch), 2PL, and (if sample permits) 3PL models
- Compare models using AIC and BIC
- Select the best model for your context

This runs in the background - you can close the browser and return later.

### 6. Review Recommendations

Once fitting completes, review:
- **Selected Model**: Which model was chosen and why
- **Item Parameters**: Difficulty and discrimination for each item
- **Flags**: Items that may need attention
- **Reliability**: Overall test reliability

### 7. Export Report

Generate a report for stakeholders:
- **Executive Summary**: High-level findings
- **Technical Appendix**: Full parameter estimates
- **Reproducibility Metadata**: For audit trails

Available formats: PDF, HTML, JSON

## Understanding the Results

### Model Selection

The system recommends one model based on:
1. Statistical fit (AIC/BIC comparison)
2. Sample size constraints
3. Your assessment context

Trust the recommendation unless you have specific reasons not to.

### Item Parameters

- **Difficulty (b)**: Higher values = harder items
- **Discrimination (a)**: Higher values = better differentiation
- **Guessing (c)**: Probability of correct guess (3PL only)

### Reliability

Marginal reliability estimates test precision:
- < 0.70: Inadequate for most purposes
- 0.70-0.80: Acceptable for low-stakes
- 0.80-0.90: Good for most purposes
- > 0.90: Required for high-stakes

## Next Steps

- Read [IRT Basics](./irt-basics.md) to understand the theory
- Review [Data Schema](./data-schema.md) for data requirements
- Explore [Modeling Decisions](./modeling-decisions.md) for technical details

## Getting Help

- Check the [FAQ](#faq)
- Open an issue on GitHub
- Join our community discussions

## FAQ

**Q: My model didn't converge. What should I do?**

A: Non-convergence usually indicates data issues:
- Too few respondents (need 200+ for 2PL, 500+ for 3PL)
- Items with no variance (everyone got it right/wrong)
- Too much missing data

Review your data quality warnings and address any issues.

**Q: Why can't I fit a 3PL model?**

A: The 3PL model requires estimating a guessing parameter, which needs at least 500 respondents for stable estimation. With smaller samples, we only fit 1PL and 2PL.

**Q: How do I know if my test is "good enough"?**

A: Check the recommendations report. If there are no critical issues and reliability meets your stakes level threshold, your test is likely adequate.
