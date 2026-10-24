# Contributing to CopBot AI

Thanks for taking a look! This is a student/portfolio project, so the bar
is "keep it simple and tested," not "enterprise process."

## Local setup

```bash
git clone <your-fork-url>
cd CopBotAI
make dev          # creates .venv, installs runtime + dev/test deps
cp .env.example .env
make test         # run the test suite
make run          # start the server on http://localhost:8000
```

## Before opening a PR

1. `make test` — all tests must pass.
2. Add a test for any new endpoint or non-trivial function (see `tests/`
   for the existing patterns — `tests/conftest.py`'s `client` fixture
   gives you an isolated, rate-limit-free FastAPI test client).
3. Keep functions documented with a short docstring explaining *why*, not
   just *what*.
4. If you touch the data schema (`data/*.json`) or the database schema
   (`backend/database.py`'s `SCHEMA`), update `ARCHITECTURE.md` too.

## Code style

- Standard PEP 8 / Black-ish formatting (no enforced formatter yet — feel
  free to add one).
- Prefer small, single-purpose functions (see `backend/rag_engine.py` or
  `backend/database.py` for the general shape).
- Frontend is intentionally framework-free vanilla JS — keep it that way
  unless there's a strong reason to introduce a build step.

## Reporting issues

Open a GitHub issue with: what you ran, what you expected, what happened
instead, and your Python version / OS.
