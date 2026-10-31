# M9: Review screen

**Branch:** `#0009-review-screen`
**Goal:** the core human-in-the-loop screen.
**Estimate:** 9 h

**Context:** SPEC sections 11 and 12.

**Scope**
- `PATCH /documents/{id}/fields` re-running the rules, `POST approve`, `POST reject`, with optimistic-concurrency protection against two reviewers.
- Every correction writes `audit_events`.
- Page preview with zoom and page navigation, beside editable fields.
- Rule failures highlighted on their fields, with reasons in plain words.
- Editable line items.
- Keyboard: next field, approve, reject, next document. Shortcuts documented on screen.
- At 375 px, preview and fields stack and switch.

**Out of scope:** run-log screen (M11).

**Tests required:** API tests for correction, re-validation, approval, rejection, override reason and concurrent edits. Component tests for all states, highlights and keyboard flow. Money stays a string in the client and is never parsed to `number`.

**Acceptance criteria:** AC-13, AC-14 for this screen, and the audit half of AC-18.

**Verification:** real browser at all three widths; keyboard-only run through a full review; console clean.
