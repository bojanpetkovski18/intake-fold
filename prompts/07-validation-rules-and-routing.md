# M7: Validation rules and routing

**Branch:** `#0007-validation-rules-and-routing`
**Goal:** deterministic code decides what happens to each document.
**Estimate:** 6 h

**Context:** SPEC section 7. D-012, D-013.

**Scope**
- Normalization for vendor names and invoice numbers.
- The six rules as pure functions, with thresholds from configuration.
- `not_duplicate` query, race-safe under concurrent workers.
- `route()` and its wiring into the worker, writing `rule_results` and status reasons.
- `known_vendor` against seeded vendors and aliases.

**Out of scope:** UI, delivery.

**Tests required**
- Table tests for each rule, including boundaries at the tolerance.
- Hypothesis property tests for total arithmetic.
- `route()` table covering every condition.
- Two duplicates processed concurrently.
- End to end through the worker with the mock.
- **A compromised double cannot get an injected, rule-breaking document auto-approved, and the flag alone forces review.**

**Acceptance criteria:** AC-10, AC-11, AC-12, and AC-07 up to the routing step.

**Python notes to flag:** `Decimal` context and rounding, and why values are built from strings.
