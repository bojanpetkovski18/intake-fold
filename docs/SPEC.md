# Intakefold specification

Version 0.1, 2026-10-31. Draft for owner approval. Change this file only with the owner, and note why.

## 1. Purpose

Intakefold is the owner's fifth Upwork portfolio project. The earlier four are Angular + .NET apps and a TypeScript/React developer tool. This one is a Python and LLM project that shows reliable document automation, not a demo.

It must show: structured extraction with strict schemas; validation against business rules; doubtful results going to a human instead of failing silently; background work with retries and idempotency; an auditable log of every run; and honest accuracy measurement.

The audience is prospective Upwork clients and the developers who assess them. It is an independent project built with AI assistance, and all data is fictional.

## 2. Users and roles

One organization. No tenants.

| Role | May |
|---|---|
| Anonymous | Health check, sign in |
| Reviewer | Upload, view documents, review, approve, reject, export CSV, view metrics and logs |
| Admin | Everything a reviewer may do, plus requeue dead jobs and reset the demo |

Accounts are seeded fictional users on the `example` domain. There is no registration or password change in the MVP.

## 3. Features

| ID | Feature |
|---|---|
| F-01 | Upload PDF, PNG and JPEG, checked by content, with size, page and pixel limits |
| F-02 | PostgreSQL job queue: retries with backoff, idempotency, visible dead-letter state |
| F-03 | `Extractor` interface with a deterministic mock (default) and a Claude implementation; model from configuration |
| F-04 | Structured output validated by Pydantic; limited repair retries, then review; oversized input refused |
| F-05 | Prompt-injection defense, proven by tests and by a real-model evaluation |
| F-06 | Validation rules in code, each failure recorded with a reason |
| F-07 | Routing: auto-approve, or review with reasons |
| F-08 | Review screen: preview beside editable fields, failures highlighted, approve and reject, keyboard friendly, all states, usable at 375, 768 and 1280 px |
| F-09 | Signed webhook delivery with retries, idempotency key and delivery log, plus a demo sink |
| F-10 | CSV export of approved invoices, safe against formula injection |
| F-11 | Run log per document: step, timing, model, tokens, estimated cost |
| F-12 | Audit trail: who changed what |
| F-13 | Metrics page: processed, auto-approved share, review share, failure share, average time; real runs only |
| F-14 | Fictional document generator with ground-truth labels |
| F-15 | Evaluation harness scoring field-level accuracy and writing a dated report |
| F-16 | Demo mode with seeded fictional data and a one-click reset |
| F-17 | Sign-in with two roles, so the audit trail's "who" comes from the server |

**V2, not in the MVP:** Arabic and handwriting, email ingestion, multi-tenant accounts, vector search, a hosted public demo.

## 4. Processing flow

```
upload -> checks -> store -> enqueue process_document
worker: render pages -> extract -> validate schema (repair) -> run rules -> route
  clean  -> auto_approved -> enqueue delivery
  doubt  -> needs_review  -> reviewer corrects -> approved -> enqueue delivery
                                               -> rejected
  retries exhausted -> failed (job is dead, shown in the UI)
```

### Document status

`queued -> processing -> auto_approved | needs_review | failed`, and `needs_review -> approved | rejected`.

Refused uploads never become documents. Delivery has its own status and does not change the document status.

A batch is one upload request or one evaluation run, and is the unit for caps and cost.

## 5. Upload rules

Limits are configuration with these defaults.

| Limit | Default | Why |
|---|---|---|
| PDF size | 10 MiB | |
| Image size | 7 MiB | The Claude API limit is 10 MB per image base64-encoded; 7 MiB raw stays under it |
| Pages per PDF | 10 | Invoices are short, and this bounds cost |
| Image dimensions | 8000 px per side, 40 megapixels | 8000 px is the API limit; the pixel cap stops decompression bombs |
| Files per batch | 25 | Also the batch document cap |
| Upload rate | 30 requests per minute per user | |

- Type is decided by magic bytes, then proved by a full decode. The file name and client content type are ignored.
- Encrypted PDFs are refused, because the API does not accept them.
- Images are re-encoded and metadata is stripped. The re-encoded copy is what is previewed and sent to the model.
- A file with the same SHA-256 as an existing document returns that document (`200`, `deduplicated: true`) instead of creating a second one. This is upload idempotency, separate from the invoice duplicate rule.

## 6. Extraction

### Extractor interface

```python
class Extractor(Protocol):
    def extract(self, document: DocumentInput) -> ExtractionResult: ...
```

`ExtractionResult` holds the parsed data or a typed failure, plus extractor name, model, token usage and repair count.

- **Mock:** looks up the document's SHA-256 in the labels. Unknown documents get a fixed low-confidence result, so they go to review. No network. The UI shows a banner while the mock is active.
- **Claude:** uses the Anthropic SDK. `EXTRACTOR=claude` plus an API key is required, and start-up fails fast if the key is missing. The model comes from `CLAUDE_MODEL`, with `output_config.effort` from `CLAUDE_EFFORT`.

### Schema

The model-facing schema is strict: every field required, nullable where a value may be absent, `additionalProperties: false`.

| Field | Type |
|---|---|
| `document_type` | `invoice`, `receipt`, `other` |
| `vendor_name`, `invoice_number` | string or null |
| `issue_date`, `due_date` | ISO date or null |
| `currency` | ISO 4217 string or null |
| `subtotal`, `tax_total`, `adjustments_total`, `total` | decimal string or null |
| `line_items[]` | `description`, plus `quantity`, `unit_price`, `amount` as decimal string or null |
| `overall_confidence` | `high`, `medium`, `low` |
| `uncertain_fields[]` | enum of field names |
| `contains_embedded_instructions` | boolean |

Money and quantities are strings in the model schema and `Decimal` in the domain. The API rejects schemas with lookahead patterns or numeric constraints, and allows at most 16 union parameters; this schema has 12 by design. Numeric range checks run in Pydantic after the response.

### Failure handling

| Case | Result |
|---|---|
| Output fails Pydantic validation | Repair retry, at most `EXTRACTION_MAX_REPAIRS` (default 2), then review with reason `extraction_invalid` |
| `stop_reason: max_tokens` | Treated as invalid output |
| `stop_reason: refusal` after any fallback | Review with reason `extraction_refused` |
| Input over `MAX_INPUT_TOKENS_PER_DOC` by token count | Refused, review with reason `input_too_large`; no model call; nothing truncated |
| Batch token cap reached | Review with reason `budget_exceeded`; no model call |
| 429, 5xx, connection failure | Job retried with backoff; dead after `max_attempts`; document `failed` |
| 400, 401, 403 | Not retried: job dead with error code |

A repair resends the original request with a note describing the validation error. It never appends a partial assistant turn.

### Prompt-injection defense

1. The system prompt says the document is untrusted data and that instructions inside it must never be followed.
2. Document content goes only in document or image blocks, never interpolated into a prompt.
3. The model has no tools. Output is constrained to the schema, so there is nothing to call.
4. The model reports `contains_embedded_instructions`; true sends the document to review.
5. Model output only ever proposes data. Rules and routing run in code on top of it, and `overall_confidence` can only lower trust, never raise it.

**What each test proves.** A mock cannot show that a model resists injection. So there are two tests, and neither is described as the other:

- **Automated, in CI:** a test double behaves like a *compromised* model that obeys the injected instruction. The test proves code rules and routing still stop the document, and that the request keeps document content out of the system prompt.
- **Real model, owner-authorized:** paired documents, with and without injected text, are extracted and compared field by field. The result is reported in `PROGRESS.md` and never claimed before it is run.

## 7. Validation rules

Rules are pure functions in code. Each produces `pass`, `fail` or `skip`, with a reason code and readable detail. All thresholds are configuration.

| Rule | Check | Skips when |
|---|---|---|
| `required_fields` | `vendor_name`, `issue_date`, `currency`, `total` present; `invoice_number` too for invoices | never |
| `line_items_total` | Each `quantity * unit_price` equals `amount`, and amounts sum to `subtotal`, within 0.01 per line and 0.02 overall | no line items or no subtotal |
| `total_reconciles` | `subtotal + tax_total + adjustments_total = total` within 0.02 | subtotal or total missing |
| `date_plausible` | Issue date not after tomorrow and not older than 5 years; due date not before issue date | no issue date |
| `not_duplicate` | No other non-rejected document has the same normalized vendor and invoice number; without a number, same vendor, date and total | vendor missing |
| `known_vendor` | Normalized name or alias matches a vendor exactly; no fuzzy matching | vendor missing |

A skip is never a pass for routing purposes if the field is required: `required_fields` already fails in that case.

### Routing

`route()` is a pure function. It auto-approves only when **all** of these hold, and otherwise sends the document to review with every reason listed:

- no rule failed
- `overall_confidence` is `high`
- `uncertain_fields` is empty
- `contains_embedded_instructions` is false
- `document_type` is `invoice` or `receipt`

## 8. Job queue

| Column | Notes |
|---|---|
| `kind` | `process_document`, `deliver_webhook` |
| `idempotency_key` | Unique; enqueueing twice is a no-op |
| `status` | `queued`, `running`, `succeeded`, `dead` |
| `attempts`, `max_attempts` | Default 5 |
| `run_after` | Exponential backoff with jitter |
| `locked_by`, `locked_until` | Lease; expired leases are reclaimed |
| `last_error` | Error code and short message, no document content |

- Claiming uses `FOR UPDATE SKIP LOCKED` in a short transaction that commits before work starts, so no transaction is held during external calls.
- Delivery is at-least-once. Handlers are idempotent: extraction reuses a successful result for the same document and prompt version, and webhook events carry a stable ID.
- Workers poll, with a lease heartbeat for long jobs. No `LISTEN/NOTIFY` in the MVP.
- Delivery jobs are created in the same transaction as the approval.

## 9. Webhooks and CSV

- `WEBHOOK_TARGETS` is JSON configuration of name, URL and secret. There is no API to set a URL.
- Event `invoice.approved` with a stable `event_id`.
- Headers: `Intakefold-Event-Id` (idempotency key) and `Intakefold-Signature: t=<unix>,v1=<hex>`, where `v1` is HMAC-SHA-256 over `t.body`.
- Success is any 2xx. Other results retry with backoff, then dead. Every attempt is logged with status code and duration.
- The sink verifies the signature, rejects timestamps older than 5 minutes, deduplicates by event ID, and displays what it received. It can fail the first N attempts of an event, to demonstrate retries.
- CSV has one row per line item. A text cell starting with `=`, `+`, `-`, `@`, tab or carriage return is neutralized with a leading `'`. Money columns are written from `Decimal` and stay numeric, so a real negative amount survives.

## 10. Data model

All IDs are UUIDs. All timestamps are `timestamptz` in UTC. Money is `NUMERIC(14,4)`.

| Table | Key columns |
|---|---|
| `users` | email, display_name, role, password_hash |
| `sessions` | token_hash, user_id, csrf_token_hash, expires_at |
| `batches` | created_by, source (`upload`, `demo`, `eval`), doc_cap, token_cap, tokens_used, estimated_cost_usd |
| `documents` | batch_id, sha256 (unique), original_filename, media_type, size_bytes, page_count, storage_key, status, status_reasons, received_at, finished_at |
| `vendors` | name, normalized_name, aliases |
| `extractions` | document_id, attempt, extractor, model, prompt_version, schema_version, outcome, raw_output |
| `invoices` | document_id (unique), extraction_id, vendor_id, the extracted fields, normalized dedupe keys |
| `line_items` | invoice_id, position, description, quantity, unit_price, amount |
| `rule_results` | document_id, extraction_id, rule, outcome, reason_code, detail |
| `jobs` | see section 8 |
| `run_steps` | document_id, job_id, attempt, step, status, started_at, finished_at, duration_ms, extractor, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, estimated_cost_usd, error_code |
| `audit_events` | document_id, actor_user_id (null for system), action, field, old_value, new_value, created_at. Append-only, enforced by a database trigger |
| `webhook_deliveries` | document_id, target, event_id (unique per target), payload, status |
| `delivery_attempts` | delivery_id, attempt, status_code, duration_ms, error_code, created_at |

Files live on a volume under a generated `storage_key`, never under a user-supplied name.

## 11. API

Base path `/api`. JSON. Errors are RFC 9457 problem details with `traceId`. Money is a string. Lists use `limit` plus an opaque cursor. Unsafe methods need a valid session, an allowed `Origin` and `X-CSRF-Token`.

| Method and path | Who | Purpose |
|---|---|---|
| `GET /health` | Public | Liveness and database check |
| `POST /auth/login` | Public, rate-limited | Sign in; sets HttpOnly cookie |
| `POST /auth/logout` | Signed in | End the session |
| `GET /auth/me` | Signed in | Current user and CSRF token |
| `POST /documents` | Reviewer | Multipart upload of one batch |
| `GET /documents` | Reviewer | List; filter by status, sort from an allow-list |
| `GET /documents/{id}` | Reviewer | Detail: fields, rule results, reasons |
| `GET /documents/{id}/pages/{n}` | Reviewer | Rendered page as PNG |
| `PATCH /documents/{id}/fields` | Reviewer | Save corrections; re-runs the rules |
| `POST /documents/{id}/approve` | Reviewer | Approve; blocked if a required rule fails, unless an override reason is given |
| `POST /documents/{id}/reject` | Reviewer | Reject with reason |
| `GET /documents/{id}/run-log` | Reviewer | Steps and audit events |
| `GET /documents/{id}/deliveries` | Reviewer | Delivery log |
| `GET /exports/invoices.csv` | Reviewer | Approved invoices, filtered by date |
| `GET /metrics` | Reviewer | Aggregates, computed in SQL, split by extractor |
| `GET /jobs?status=dead` | Reviewer | Dead-letter list |
| `POST /jobs/{id}/retry` | Admin | Requeue a dead job |
| `POST /demo/reset` | Admin | Restore seed data; only when `DEMO_MODE=true` |

## 12. Screens

| Screen | Content |
|---|---|
| Sign in | Demo credentials shown only in demo mode |
| Inbox | Upload, document list, status filters, dead-letter view |
| Review | Page preview beside editable fields, rule failures highlighted, reasons, approve and reject with keyboard shortcuts |
| Document log | Run steps, audit events, deliveries |
| Metrics | Five measures, labeled by extractor |

Every screen has loading, empty, error and success states, and works at 375, 768 and 1280 px without horizontal scroll. At 375 px the preview and the fields stack and can be switched between. Banners show mock mode and demo mode.

## 13. Fictional data and evaluation

The generator is seeded, so output is reproducible. It produces at least 5 layouts from at least 8 invented vendors, as PDF and image, with rotation, noise, missing fields and deliberately wrong totals. Each document has a ground-truth label and an expected routing outcome.

The evaluation set is 60 documents: 20 for development, 40 held out. The held-out labels are never used to tune the prompt. It also has 8 injection pairs.

The harness reports, per field, correct, wrong, missing and invented counts; field-level accuracy; document-level exact match; routing confusion, including **false auto-approvals**, the costliest error; tokens and estimated cost.

Reports go to `reports/eval/YYYY-MM-DD-<extractor>-<model>.md` with method, model, date and machine. A mock report is headed "plumbing test, not accuracy". Accuracy on synthetic documents is stated as such and is not a claim about real-world invoices.

## 14. Non-functional requirements

- **Cost:** `EXTRACTOR=mock` by default and in CI. Document and token caps per batch. Estimated cost uses a dated price table in code.
- **Security:** as in `CLAUDE.md`, plus strict CSP, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` and `frame-ancestors 'none'`.
- **Logging:** structured JSON with trace IDs. No secrets or document contents.
- **Packaging:** `docker compose up --build` from a fresh clone runs everything with no API key; migrations and seed data run on start; ports on `127.0.0.1`; non-root containers.
- **Demo:** no hosting in the MVP.

## 15. Acceptance criteria

| ID | Criterion |
|---|---|
| AC-01 | A file with a `.pdf` name and other content is refused; a real PDF with a wrong name is accepted |
| AC-02 | Files over each limit, encrypted PDFs and pixel bombs are refused with a clear error |
| AC-03 | Uploading the same file twice creates one document |
| AC-04 | Two workers racing never process the same job, tested with real concurrency |
| AC-05 | A failing job retries with backoff and reaches a visible dead state; an admin can requeue it |
| AC-06 | A worker killed mid-job has its job reclaimed after the lease, with no duplicate side effects |
| AC-07 | The default stack runs end to end with no API key |
| AC-08 | Invalid model output is repaired within the limit, then sent to review; never silently accepted |
| AC-09 | Oversized input is refused, never truncated |
| AC-10 | A compromised-model test double cannot get an injected document auto-approved when a rule fails, and `contains_embedded_instructions` alone forces review |
| AC-11 | Each rule has passing, failing and edge tests, with the reason recorded |
| AC-12 | `route()` auto-approves only under the listed conditions, covered by a table test |
| AC-13 | A reviewer can correct, approve and reject using only the keyboard, at 375, 768 and 1280 px |
| AC-14 | All screens show loading, empty, error and success states |
| AC-15 | Webhooks verify against the signature; a tampered body fails; a failed target retries; a repeat event is not processed twice by the sink |
| AC-16 | CSV cells that start with a formula character are neutralized, and a negative amount stays numeric |
| AC-17 | Every processed document has a run log with timing, and real-model steps have tokens and estimated cost |
| AC-18 | Every reviewer correction appears as who changed what, and `audit_events` rows cannot be updated or deleted through SQL |
| AC-19 | Metrics match a hand-computed fixture and are labeled by extractor |
| AC-20 | The generator is reproducible from a seed and contains no real brands |
| AC-21 | The harness scores a known perturbed fixture to the expected numbers and writes a dated report; a mock report carries the plumbing heading |
| AC-22 | Demo reset restores the seed state, admin only, and only in demo mode |
| AC-23 | Anonymous, wrong-role and missing-CSRF requests are refused across the whole route table |
| AC-24 | One Playwright journey passes three times in a row against the built stack, failing on console errors and CSP violations, with accessibility checks on each page |
| AC-25 | A fresh clone following the README runs the demo |
| AC-26 | The batch document cap and token cap stop further model calls |
| AC-27 | Every number in the README and portfolio kit has a row in `PROGRESS.md` |
| AC-28 | A real-model run has been measured and reported, or the README says plainly that it has not |
