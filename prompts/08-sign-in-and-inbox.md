# M8: Sign-in and inbox screens

**Branch:** `#0008-sign-in-and-inbox-screens`
**Goal:** a person can sign in, upload and see what is happening.
**Estimate:** 6 h

**Context:** SPEC section 12.
**Re-check:** React Router, TanStack Query. Decide how API types reach the front end and log the decision.

**Scope**
- API client with cookie session, CSRF header and problem-details handling.
- Sign-in screen, route guards, sign-out.
- Inbox: upload with progress and per-file errors, document list, status filters, polling while work is active.
- Dead-letter view: `GET /jobs?status=dead`, `POST /jobs/{id}/retry` (admin), with their API routes.
- Mock-mode banner.

**Out of scope:** review screen.

**Tests required:** component tests for loading, empty, error and success states, and for focus after actions. Busy buttons keep focus, using `aria-disabled`.

**Acceptance criteria:** AC-05 end to end, and the AC-14 subset for these screens.

**Verification:** real browser at 375, 768 and 1280 px; console clean; keyboard walk-through.
