# M12: Evaluation harness

**Branch:** `#0012-evaluation-harness`
**Goal:** a scorer that can be trusted before it is pointed at a real model.
**Estimate:** 6 h

**Context:** SPEC section 13. D-009.

**Scope**
- CLI: choose set (development, held out, injection), extractor, model. Runs as one batch through the real pipeline, so caps apply.
- Field comparison with explicit normalization for dates, money and whitespace.
- Line-item alignment, documented.
- Counts for correct, wrong, missing and invented. Field-level accuracy. Document exact match. Routing confusion with false auto-approvals. Tokens and cost.
- Injection comparison between paired documents.
- Dated Markdown and JSON reports, with method, model, date and machine. Mock reports carry the plumbing heading.

**Out of scope:** any real-model run.

**Tests required:** a hand-built perturbed fixture scoring to known numbers; normalization cases; every error type counted; report heading for mock.

**Acceptance criteria:** AC-21.

The mock output is expected to score near 100%, because it reads the labels. That number is a test of the harness and must never appear as accuracy.

**From M7:** the injected twin of each pair is a real duplicate of its clean twin, so do not score that as a routing miss (D-059).
