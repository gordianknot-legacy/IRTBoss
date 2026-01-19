# Contributing to IRTBoss

Thank you for considering contributing to IRTBoss.

## Philosophy

Before proposing a change, ask yourself:

> Does this make it easier for a user to produce a valid, interpretable assessment result?

Contributions that increase complexity without improving clarity may be declined.

## Design Principles

This project is opinionated by design. We value:

- **Fewer options over more options**
- **Strong defaults over configurability**
- **Clarity over flexibility**
- **Guidance over exposure**

If a proposed feature trades usability for power-user flexibility, it likely does not belong in the core.

## What We Welcome

- Bug fixes with clear reproduction steps
- Documentation improvements
- Performance optimizations that do not compromise clarity
- Accessibility improvements
- Test coverage improvements

## What We Are Cautious About

- New configuration options
- Additional IRT models beyond the MVP scope
- Features that require users to make statistical decisions
- Integrations with external systems

## How to Contribute

### Reporting Bugs

1. Check existing issues first
2. Provide a minimal reproduction case
3. Include your environment details (OS, Python version, etc.)

### Proposing Features

1. Open an issue describing the problem you want to solve
2. Wait for maintainer feedback before investing in implementation
3. Keep scope minimal

### Submitting Code

1. Fork the repository
2. Create a feature branch from `main`
3. Write tests for new functionality
4. Ensure all tests pass
5. Submit a pull request with a clear description

## Code Style

- Python: Follow PEP 8, use type hints
- TypeScript: Use strict mode, prefer explicit types
- Comments: Explain *why*, not *what*
- Functions: Prefer small, focused functions

## Testing

All code changes must include appropriate tests:

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

## Documentation

- Update relevant docs when changing behavior
- Use plain language
- Include examples where helpful

## Review Process

1. All PRs require at least one maintainer review
2. CI must pass
3. Breaking changes require discussion in an issue first

## Code of Conduct

Be respectful, constructive, and patient. We are building something useful together.

## Questions?

Open an issue with the "question" label.
