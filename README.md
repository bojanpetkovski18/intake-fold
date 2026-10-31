# Intakefold

**Intake Automation.** Reads invoices and receipts with an LLM, checks them against business rules, and sends anything doubtful to a person.

> **Status: planning.** No application code exists yet. Everything below describes the intended product, not a working system. This README is rewritten from verified facts in the final milestone.

Intakefold is an independent portfolio project built with AI assistance. All data is fictional: invented vendors, people and documents.

## What it will do

1. A small business uploads invoices and receipts (PDF, PNG, JPEG).
2. A background worker extracts the vendor, invoice number, dates, currency, line items and totals into a strict schema.
3. Rules written in code check that line items add up, totals reconcile, dates are plausible, the invoice is not a duplicate, and the vendor is known.
4. Clean results are approved automatically. Anything low-confidence or failing a rule goes to a review queue with the reasons shown.
5. A reviewer sees the document beside the extracted fields, corrects them, and approves or rejects.
6. Approved invoices go to a downstream system by signed webhook and can be exported as CSV.
7. Every step is logged with timing, model, token counts and estimated cost.

## Design goals

- **No silent failure.** Invalid or doubtful output goes to a person, and oversized input is refused rather than truncated.
- **Rules live in code, not in the prompt.** The model extracts; deterministic code decides.
- **Document content is untrusted.** Instructions found inside a document are never followed.
- **Honest measurement.** Accuracy comes from a labeled evaluation set and a dated report. Mock runs test the plumbing and are never presented as accuracy.
- **Runs without an API key.** The default demo and CI use a deterministic mock extractor.

## Planned stack

Python, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL (also the job queue; no Redis), Pydantic v2, the Anthropic SDK, React, TypeScript, Vite, pytest, Testcontainers, Vitest, Playwright, Docker Compose, GitHub Actions. Versions and reasons are in [docs/RESEARCH.md](docs/RESEARCH.md) and [DECISIONS.md](DECISIONS.md).

## Project documents

- [docs/SPEC.md](docs/SPEC.md): requirements, data model, API, rules, acceptance criteria
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): system outline
- [DECISIONS.md](DECISIONS.md): numbered decisions
- [PROGRESS.md](PROGRESS.md): milestones, measured results, known issues
- [prompts/](prompts/): one brief per milestone

## Not in the MVP

Arabic and handwriting, email ingestion, multi-tenant accounts, vector search, a hosted public demo.

## Licence

To be chosen before release.
