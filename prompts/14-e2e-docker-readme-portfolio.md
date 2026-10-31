# M14: End-to-end test, Docker, README and portfolio kit

**Branch:** `#0014-e2e-docker-readme-and-portfolio-kit`
**Goal:** a fresh clone runs the demo, and the docs state only what is true.
**Estimate:** 9 h

**Context:** SPEC sections 14 and 15. D-020, D-021, D-022. Playbook sections 13, 15 and 16.
**Re-check:** image digests, Upwork field limits, Python and Node security releases.

**Scope**
- Multi-stage images, non-root, health checks, `.dockerignore`. Migrations and seed on start.
- Run uvicorn with `--no-proxy-headers`, set `TRUSTED_PROXIES` to the Compose network, and decide `ALLOW_INSECURE_COOKIES` for the demo (D-041, D-042).
- `docker compose up --build` with no API key.
- One Playwright journey against the built stack: sign in, upload, review, correct, approve, see the delivery, export, read metrics. Fails on console errors and CSP violations, with axe checks per page. CI job.
- `README.md` rewritten for visitors. `docs/ARCHITECTURE.md` written from the code.
- `docs/portfolio/upwork.md`: title up to 70 characters, role up to 100, description up to 600, five skills, screenshot order, short video script. Character counts by script.
- Fresh-clone test in a temporary directory, following the README exactly.
- Full-history and working-tree scan for secrets and personal data, with findings reported. Licence recommendation.
- Decide the Codespaces dev container with the owner.

**Out of scope:** making anything public, tagging a release. Those are the owner's actions.

**Tests required:** the E2E journey, three runs in a row with no retries.

**Acceptance criteria:** AC-24, AC-25, AC-27, AC-28.

**Portfolio rules:** verified features and measured numbers only. No invented clients, results or testimonials.
