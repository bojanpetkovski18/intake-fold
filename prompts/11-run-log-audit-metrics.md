# M11: Run log, audit trail and metrics

**Branch:** `#0011-run-log-audit-trail-and-metrics`
**Goal:** every document can be explained after the fact.
**Estimate:** 6 h

**Context:** SPEC sections 10, 11 and 12.

**Scope**
- `GET /documents/{id}/run-log`, combining steps and audit events.
- `GET /metrics`: processed, auto-approved share, review share, failure share, average time. In SQL, split by extractor.
- Document log screen. Metrics screen, labeled by extractor, with an honest empty state.
- Check that all pipeline steps from earlier milestones actually write `run_steps`, and fill gaps.

**Out of scope:** charts beyond what the five measures need.

**Tests required:** metrics against a hand-computed fixture; zero-document case with no division by zero; run log for a real worker pass; mock runs show no fake token counts; component states.

**Acceptance criteria:** AC-14 for these screens, AC-17, AC-18, AC-19.

**Verification:** real browser at all three widths. Check the numbers on screen against a direct SQL query.
