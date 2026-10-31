# M13: Polish, accessibility and demo mode

**Branch:** `#0013-polish-accessibility-and-demo-mode`
**Goal:** every screen and interaction audited, and the demo ready to show.
**Estimate:** 8 h

**Context:** SPEC sections 12 and 14. Playbook Phase 7.

**Scope**
- Seed batch processed by the real pipeline with the mock, so demo metrics are real runs labeled as mock.
- `POST /demo/reset`, admin only, `DEMO_MODE` only, plus a one-click control with confirmation.
- Audit in `docs/AUDIT.md`: all states; 320, 375, 768 and 1280 px; 200% zoom; keyboard only; screen-reader names; light and dark if themed; reduced motion; every dialog, menu and toast opened; every error path triggered.
- Automated accessibility checks.
- Production build under real security headers, with CSP checked.
- Work through known issues with the owner.

**Out of scope:** new features.

**Tests required:** reset tests, including role and mode; accessibility checks; a regression test for anything the audit finds.

**Acceptance criteria:** AC-14, AC-22.

**Verification:** a real browser against the production build, with the console clean.
