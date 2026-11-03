# Upwork portfolio entry

For the owner's Upwork profile. Every fact here is a verified feature or a measured number with a row in `PROGRESS.md`. There are no clients, results or testimonials, because there were none: this is a portfolio project with fictional data.

**Field limits:** title up to 70 characters, role up to 100, description up to 600, checked 2026-11-02. Upwork's help page answered 403 to a direct read, so the limits come from that page as quoted in search results; confirm them in the form. `node scripts/portfolio-count.mjs docs/portfolio/upwork.md` measures each field below and fails if one is over.

## Title (up to 70 characters)

```text
Invoice Intake Automation: LLM Extraction with Human Review
```

## Role (up to 100 characters)

```text
Full-stack developer: Python and FastAPI back end, React front end, LLM extraction, Docker
```

## Description (up to 600 characters)

```text
Small teams retype invoices by hand. Intakefold has an LLM extract them into a strict schema, then rules in code check the totals, dates, vendor and duplicates. Clean documents are approved automatically; anything doubtful goes to a reviewer, who fixes it beside the page and approves with the keyboard. Approved invoices go out by signed webhook and CSV. A Postgres job queue retries and dead-letters work, and every step and correction is logged. Document text is never trusted. Runs with one Docker command and no API key. Accuracy on a real model has not been measured yet.
```

## Skills

Five, to be picked from Upwork's own skill list, where the names may differ slightly:

1. Python
2. FastAPI
3. React
4. PostgreSQL
5. Generative AI

Alternatives if one is missing from the list: TypeScript, Docker, API Development.

## Problem and solution

- **Problem:** invoices and receipts arrive as PDFs and photos, and someone types them into the books. Mistakes and duplicates get through, and nobody can say who changed what.
- **Solution:** a worker extracts the fields with an LLM, deterministic rules check them, and only doubtful documents reach a person. The reviewer sees why, corrects beside the page, and the result is delivered and logged.

## Key decisions

- Rules live in code, not in the prompt. The model proposes; code decides.
- Document text is untrusted. A document with instructions aimed at the extractor always goes to a person.
- PostgreSQL is the job queue (`SKIP LOCKED`, leases, retries, dead letters), so there is one datastore to run.
- A mock extractor behind the same interface runs the demo and CI for free, and is labelled everywhere as saying nothing about accuracy.

## Measured facts

All from `PROGRESS.md`, "Measured results", 2026-11-02, on the owner's Windows 11 machine with Docker Desktop:

- 685 backend tests (315 against a real PostgreSQL) and 128 front-end tests pass.
- One Playwright journey passes three times in a row against the built stack, failing on any console error, CSP violation or accessibility finding.
- No axe violations in 116 browser runs across nine widths and both themes.
- From a fresh clone, `docker compose up --build` with an empty build cache served the app in 112 seconds.
- Extraction accuracy: **not measured yet.**

## Services demonstrated

LLM document extraction with schema validation; business rules and routing; human-in-the-loop review UI; background jobs with retries; signed webhooks; CSV export safe against formula injection; audit trail; accessibility; Docker packaging; CI.

## Screenshots, in order

Files are in `docs/screenshots/`. Fictional data only.

1. `review-light.png`: **Review beside the page.** The extracted fields next to the document, with a duplicate flagged on two fields and the reason at the top.
2. `inbox-dark.png`: **Inbox, dark theme.** Upload, CSV export, and documents with their status.
3. `log-light.png`: **Every step on record.** Run steps with timings, and the audit trail.
4. `review-light-phone.png`: **Works on a phone.** Fields and preview switch at narrow widths.
5. `metrics-light.png`: **Honest metrics.** Labelled by extractor; the mock says it is a plumbing test, not accuracy.
6. `sign-in-light.png`: **Demo accounts on the page.** Shown only in demo mode.

## Short video script

About 75 seconds, 1920×1080, no audio, captions on each frame. Recorded from a fresh stack with seed data only.

| # | Seconds | Screen | Caption |
|---|---|---|---|
| 1 | 4 | Title slide | **Intakefold.** Invoice intake with LLM extraction, rules in code and human review. |
| 2 | 6 | Sign-in page | **Demo accounts on the page.** One Docker command, no API key, fictional data. |
| 3 | 8 | Inbox | **The inbox.** Twenty fictional documents, some approved automatically, the rest waiting for review. |
| 4 | 10 | Review, reasons highlighted | **Why it needs review.** The reasons sit at the top, and the flagged fields are outlined. |
| 5 | 10 | Review, a field corrected and saved | **Correct and re-check.** Saving runs the rules again on the corrected fields. |
| 6 | 8 | Review, override question | **Rules decide.** Approving past a failed rule needs a written reason. |
| 7 | 8 | Document log | **Every step on record.** Timings, who changed what, and the signed webhook delivery. |
| 8 | 6 | Sink page | **Delivered.** The downstream receiver verified the signature. |
| 9 | 6 | Metrics | **Honest numbers.** The mock is labelled a plumbing test, not accuracy. |
| 10 | 5 | Phone width | **Works on a phone.** |
| 11 | 4 | End slide | Repository link. Built with AI assistance. All data is fictional. |
