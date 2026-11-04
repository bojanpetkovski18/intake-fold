# Polish and accessibility audit

M13, 2026-11-02, on the owner's Windows 11 machine. Chromium from Playwright 1.64.1 and axe-core 4.14.0, run from scratch space outside the repository (browser tooling joins the repository in M14).

## Method

- **Stack:** the production build (`npm run build`) served by `frontend/nginx.conf` in `nginxinc/nginx-unprivileged:1.30.6-alpine` (pinned by digest, running as uid 101) and proxying `/api` to the API. The API and worker ran with `DEMO_MODE=true` and the mock extractor, on a scratch Postgres 18.6. The seed queued the 20-document demo batch, and the worker processed it.
- **Contexts:** 1280, 768 and 320 px in light and dark; 375 px in light and dark; 640 px, which is a 1280 px window at 200% zoom. Every dark context also set reduced motion.
- **Each screen and state:** axe with every rule, contrast included; horizontal overflow measured as `scrollWidth - clientWidth`; a full-page screenshot.
- **Console:** every error and warning collected, plus a listener for CSP violation events.
- **Keyboard only:** Tab order and the computed focus outline on the sign-in page and the inbox; the demo reset question opened with Enter and closed with Escape.
- **Error and loading paths:** live where the API produces them (wrong password, unknown document, refused upload). Elsewhere the browser answered for the API, with a 500 problem response or a 3-second delay.
- **Unit level:** `src/a11y.test.tsx` runs axe in Vitest on 24 screen states on every commit (D-079). It has no layout, so contrast is checked only here.

## Results

| Check | Result |
|---|---|
| axe in the browser | 116 runs, 0 violations |
| Horizontal overflow | 0 px in every run |
| CSP violations | 0 |
| Console lines that are not the browser's own "Failed to load resource" | 0 |
| Focus outline | 3 px solid on every element Tab reached |
| Sign-in tab order | Skip link, brand, email, password, Sign in |
| Inbox tab order | Upload file, Upload, status filter, then documents newest first |
| Reset question | Focus starts on Cancel; Escape closes it and returns focus to "Reset demo data" |
| After a reset | Status message "Demo data reset. 20 documents are being processed again."; focus on the main region; 20 rows once processed |

The remaining console lines are the browser reporting each error response that the walk caused on purpose: 401 while signed out and for a wrong password (D-063), 404 for an unknown document, 422 for the refused upload, and the injected 500s.

### Screens and states covered

| Screen | States | Contexts |
|---|---|---|
| Sign in | With demo accounts; wrong password | All 9; error at 1280 |
| Inbox | Success; empty filter; loading; error; refused upload | Success in all 9; the rest at 1280 |
| Demo banner | Reset question open; after reset | All 9; after reset at 320 dark |
| Review | Fields; preview view; reject question; override question; not found | All 9; the preview view at the 7 widths that switch views |
| Document log | Steps, trail and deliveries | All 9 |
| Metrics | Success; loading; error | Success in all 9; the rest at 1280 |
| Dead letters | Empty; a dead job with Requeue; error | Empty in all 9; the rest at 1280 |
| Page not found | Unknown address | All 9 |

There are no menus, toasts or modal dialogs. The questions (reset, override, reject) are inline panels, opened in every context above.

### Response headers

Pages and assets carry the nginx CSP from D-078, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` and `Cross-Origin-Opener-Policy: same-origin`. Assets also get a one-year immutable cache, and pages get `no-cache`. API responses keep the API's own `default-src 'none'` CSP. nginx hides its version.

## Findings and fixes

| # | Finding | Found by | Fix | Regression test |
|---|---|---|---|---|
| 1 | The mock-mode banner sat outside every landmark, so landmark navigation skipped it | axe `region`, Vitest | Banners moved inside the `header` landmark | `src/a11y.test.tsx`, 15 states failed before the fix |
| 2 | "Line items" was an `h3` straight after the page's `h1` | axe `heading-order`, Vitest | Now an `h2`, styled at its old size | `src/a11y.test.tsx`, review with the override question |

## Not covered

- Screen readers were not run. Names and roles come from axe and from the role-based queries in the tests.
- Performance: no page scores or load test. The playbook lists them for this phase and the brief does not; they are left for M14.
- Firefox and Safari were not run.
