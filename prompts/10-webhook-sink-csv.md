# M10: Webhook delivery, sink and CSV export

**Branch:** `#0010-webhook-delivery-sink-and-csv`
**Goal:** approved invoices reach a downstream system reliably, and can be exported safely.
**Estimate:** 7 h

**Context:** SPEC section 9.
**Re-check:** the HTTP client for outbound calls (`httpx` or `httpx2`).

**Scope**
- Delivery jobs created in the approval transaction, for auto-approval and manual approval.
- HMAC signing, retries, delivery log.
- `WEBHOOK_TARGETS` configuration validated at start-up.
- Sink: verify, timestamp window, dedupe by event ID, display, optional fail-first-N.
- `GET /documents/{id}/deliveries`.
- `GET /exports/invoices.csv`, streamed, filtered by date.

**Out of scope:** user-defined targets.

**Tests required:** signature known-answer test; tampered body; old timestamp; constant-time compare; retries against a failing sink; repeat delivery not processed twice; no outbound call inside a transaction; each formula prefix neutralized; a negative amount stays numeric; quoting of commas and newlines.

**Acceptance criteria:** AC-15, AC-16.

**Python notes to flag:** `hmac.compare_digest`, `csv` module quoting, streaming responses.
