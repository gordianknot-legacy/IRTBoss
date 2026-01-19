# Open-Source IRT Assessment Platform

An opinionated, open-source platform for building and validating assessments using **Item Response Theory (IRT)**  (without requiring deep psychometric expertise or extensive custom scripting).

This project prioritizes clarity, guidance, and trust over flexibility for its own sake.

---

## What This Is

This platform helps teams go from:

**Raw response data → validated IRT model → interpretable report**

It is designed for:
- academic researchers
- EdTech product and data teams
- certification and assessment organisations

It is not designed to be a general-purpose quiz builder or a statistical sandbox.

---

## Why This Exists

Item Response Theory is widely regarded as the gold standard for assessing test quality and measurement precision.  
In practice, however, IRT tooling is often:
- difficult to use without specialised training
- fragmented across scripts and legacy software
- expensive or inaccessible
- hard to explain to non-technical stakeholders

As a result, many real-world assessments are built and deployed without strong statistical validation.

This project exists to lower that barrier while preserving rigor.

---

## Core Design Principles

- Opinionated by design  
- Strong defaults instead of extensive configuration  
- One recommended model, always  
- Explicit warnings when assumptions are violated  
- No silent fallbacks  

If a feature increases flexibility but makes correct use harder, it does not belong here.

---

## MVP Features

- CSV data ingestion with schema validation  
- Automatic fitting of 1PL, 2PL, and 3PL models (when appropriate)  
- Model comparison with a clear recommendation and explanation  
- Visual diagnostics, including:
  - Item Characteristic Curves
  - Test Information Function
- Exportable reports (PDF, HTML, JSON)

---

## Explicitly Out of Scope (for Now)

The following are intentionally not part of the initial scope for now:
- Multidimensional IRT  
- Computerised adaptive testing (CAT)  
- Item authoring tools  
- LMS integrations  
- DIF or fairness analysis  
- Real-time scoring APIs  

These may be considered later, if there's demonstrated need and adoption.

---

## Guided Workflow

1. **Upload response data**  
   - CSV format  
   - Automatic structure detection  
   - Early warnings for data quality issues

2. **Specify assessment context**  
   - Stakes level  
   - Intended use  
   These inputs constrain later recommendations.

3. **Automatic model fitting**  
   - Runs asynchronously  
   - Progress and logs are visible

4. **Model recommendation**  
   - Models compared using AIC/BIC  
   - One model is recommended  
   - Rationale is explained in plain language

5. **Diagnostics**  
   - Item-level flags for poor fit or low discrimination  
   - Test-level information summaries

6. **Export results**  
   - Executive summary  
   - Technical appendix  
   - Reproducibility metadata

---

## Architecture Overview

### Backend
- Python
- FastAPI
- Dockerised services

### Modeling
- Short term: R `mirt`, wrapped behind a clean interface  
- Long term: native PyTorch-based IRT

### Frontend
- React with TypeScript
- D3 or Observable Plot for visualisations

---

## Repository Structure

irt-platform/
├── backend/
├── frontend/
├── docs/
├── examples/
├── docker/
└── README.md


Two files are especially important:
- `model_selection.py`
- `recommendations.py`

These encode the decision logic that distinguishes this platform from generic IRT tooling.

---

## Open Source Model

This project follows an **open-core** approach.

### Open Source
- Core modeling and validation logic  
- Data schema and ingestion  
- Guided workflow and recommendations  
- Basic user interface  

---

## Who This Is For (and Who It Isn’t)

This project will be a good fit if you care about:
- statistical rigor
- reproducibility
- usability for non-specialists
- real-world assessment quality

It is likely not a good fit if you prefer:
- highly configurable, low-level toolkits
- exposing all model parameters by default
- prioritising theoretical completeness over usability

---

## Getting Started

See the following documentation:
- `docs/getting-started.md`
- `docs/data-schema.md`
- `docs/modeling-decisions.md`

Example datasets are available in the `examples/` directory.

---

## Contributing

Before proposing a change, consider:
> Does this make it easier for a user to produce a valid, interpretable assessment result?

Contributions that increase complexity without improving clarity may be declined.

---

## License

MIT License

---

## Project Status

Early-stage, development at snail's pace.

We are especially interested in:
- research collaborators
- early adopters with real assessment data
- contributors who value careful, opinionated design