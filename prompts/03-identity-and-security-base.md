# M3: Identity and security base

**Branch:** `#0003-identity-and-security-base`
**Goal:** sign-in, roles and the protections everything else relies on.
**Estimate:** 5 h

**Context:** SPEC sections 2 and 11. D-002, D-019.
**Re-check:** argon2-cffi, slowapi.

**Scope**
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- Argon2 hashing, and replace `UNUSABLE_PASSWORD` in `db/seed.py` with real demo credentials from configuration. Opaque session tokens stored hashed. HttpOnly, SameSite cookie. A local plain-http switch that is explicit and off by default.
- `require_user` and `require_role` dependencies. Authentication on by default, with public routes listed explicitly.
- CSRF: `X-CSRF-Token` plus an `Origin` allow-list on unsafe methods.
- Rate limit on sign-in. Client IP trusted from the proxy only.
- A route-table test that future milestones extend.

**Out of scope:** registration, password change, the front-end sign-in screen (M8).

**Tests required:** correct and wrong password; expired session; logout ends the session; missing CSRF; bad Origin; rate limit; anonymous and wrong-role calls across the route table; passwords and tokens never appear in logs.

**Acceptance criteria:** AC-23 for all routes existing so far.

**Python notes to flag:** FastAPI `Depends` compared with ASP.NET filters and middleware.
