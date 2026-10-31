# M6: Extraction

**Branch:** `#0006-extraction-mock-claude-repair-injection`
**Goal:** the mock and Claude extractors behind one interface, with strict output, repair, limits and injection defense.
**Estimate:** 10 h

**Context:** SPEC section 6. D-008, D-009, D-010, D-011, D-012, D-013, D-015, D-023, D-024.
**Re-check, using the Claude API skill and live docs:** SDK version and API version, model IDs, prices, structured-output limits, refusal fallback with structured outputs, `count_tokens` on PDF input.

**Scope**
- `Extractor` protocol and `ExtractionResult`.
- Mock keyed by SHA-256 from the labels. Compromised-model test double.
- Claude implementation: request builder, parse, error-handling chain, usage capture, cost from a dated price table.
- Model-facing schema and `Decimal` conversion. Confirm the claim in D-011.
- Repair loop. Handling of `max_tokens` and `refusal`.
- Pre-flight token count. Refusal of oversized input, with no truncation.
- Atomic batch token reservation.
- Versioned system prompt in `extraction/prompt.py`.
- Worker handler wired through to storing `extractions` and `invoices`.

**Out of scope:** rules and routing. Any real-model call unless the owner says so in this session.

**Tests required**
- Recorded-response tests using a fake transport, so no network in tests.
- Valid, invalid then repaired, repairs exhausted, `max_tokens`, refusal, 429, 500, 400.
- Oversized input is refused and no request is sent.
- Token cap stops calls, with a concurrency test.
- Request shape: document content only in document or image blocks; system prompt has the untrusted-data rule; no tools.
- Schema stays inside API limits.

The compromised double is exercised fully in M7, once routing exists.

**Acceptance criteria:** AC-08, AC-09, AC-26, and the extraction half of AC-07.

**Not verified until M15:** real extraction quality and real token counts. The report must say so.

**Python notes to flag:** `Protocol` versus C# interfaces, Pydantic validators, the SDK exception hierarchy.
