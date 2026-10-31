# M15: Real-model measurement

**Owner-gated.** Do not start without the owner's explicit go-ahead, including the model list and a spending limit.

**Branch:** `#0015-real-model-measurement`
**Goal:** measured extraction accuracy, injection resistance and cost.
**Estimate:** 3 h plus API spend. The planning estimate of spend is in `docs/RESEARCH.md`; it is not a quote.

**Context:** SPEC sections 6 and 13. D-009, D-012, D-013, D-024.
**Re-check:** model IDs and prices. Update the price table if they changed.

**Preconditions:** M12 complete. The owner has stored the key in local `.env` and set a spend limit in the Claude Console. To check the key, inspect only its prefix and length.

**Scope**
- Small smoke batch first. Compare tokens with the planning estimate before going further.
- Development set: tune the prompt if needed, recording each change. Held-out set: run once at the end.
- Injection pairs.
- Requested model comparison, if authorized.
- Reports in `reports/eval/`, and rows in `PROGRESS.md` under "Measured results".
- Update the README and portfolio kit from those rows.

**Out of scope:** changing the default model without the owner's decision.

**Acceptance criteria:** AC-28. Every published number has a method, model, date and machine. Weak results are reported as they are.

**Before committing reports:** check they contain no API key, and no prompt or response bodies beyond what is intended.
