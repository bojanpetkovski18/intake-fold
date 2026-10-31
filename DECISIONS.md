# Decisions

Numbered and never renumbered. A reversal is a new entry. The owner approved Phase 0 on 2026-10-31.

## D-001 Project name: Intakefold
- **Date:** 2026-10-31. **Status:** decided by the owner.
- **Decision:** rename the project from Filefold to Intakefold, Python package `intakefold`.
- **Why:** filefold.com is a live product in the same space, a client document portal with AI retrieval. Intakefold is free on PyPI and npm, has no GitHub repositories, and no product was found.
- **Alternatives:** Slipfold, Foliowise, keeping Filefold.
- **Trade-offs:** the GitHub repository is still called `file-fold`, and renaming it is the owner's action. No trademark search was done.

## D-002 Minimal sign-in with two roles
- **Date:** 2026-10-31. **Status:** decided by the owner.
- **Decision:** seeded accounts, reviewer and admin roles, HttpOnly session cookie, database-backed sessions, CSRF token plus Origin check, rate-limited sign-in, argon2 hashes.
- **Why:** the audit trail needs a "who" that the client cannot control, and the playbook requires authentication by default.
- **Alternatives:** a client-side "reviewing as" picker, which saves about 5 hours but makes the audit trail a demo.
- **Trade-offs:** about 5 hours, plus CSRF handling in every unsafe call. No registration or password change in the MVP.

## D-003 Python 3.15
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** target Python 3.15. Fall back to 3.14 in M1 if any dependency fails to install or pass tests.
- **Why:** the brief asks for the latest stable version, and all native dependencies have 3.15 wheels.
- **Alternatives:** 3.14, which is more settled.
- **Trade-offs:** 3.15.0 is 22 days old. Patch releases 3.15.1 and 3.15.2 are under two weeks old today; 3.15.1 clears the floor on 2026-11-04. M1 pins the newest eligible patch.

## D-004 uv for Python environments and locking
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** use `uv` with a committed `uv.lock`. uv also supplies the Python interpreter.
- **Why:** the host has no Python, and uv gives the exact-version, hash-locked workflow of `npm ci`.
- **Alternatives:** pip with pip-tools, Poetry, Docker-only development.
- **Trade-offs:** one more tool to install on the host.

## D-005 pyright in strict mode, not mypy
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** pyright strict, plus ruff.
- **Why:** it is the engine behind VS Code's Pylance, so the editor and CI agree. It reports like `tsc`, is familiar to a TypeScript developer, and understands SQLAlchemy 2 `Mapped[]` and Pydantic through `dataclass_transform` without plugins.
- **Alternatives:** mypy strict, which is the community default but needs a Pydantic plugin for best results.
- **Trade-offs:** the PyPI wrapper needs Node at run time, which the project already has. Third-party stubs may need targeted ignores, each with a comment.

## D-006 Synchronous SQLAlchemy with psycopg 3
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** sync sessions and plain `def` routes in the API, and the same in the worker.
- **Why:** there is one code path to reason about. FastAPI runs `def` routes in a threadpool, and the worker does one blocking job at a time, scaled by process count.
- **Alternatives:** async SQLAlchemy with asyncpg, which handles more concurrent connections but adds async sessions and more ways to fail, for no benefit at this scale.
- **Trade-offs:** lower peak API concurrency. Python note: a blocking call inside `async def` would stall the event loop, so routes stay `def`.

## D-007 TypeScript 6.0, not 7
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** pin TypeScript 6.0.3.
- **Why:** typescript-eslint's peer range is `<6.1.0`, on its latest release too.
- **Alternatives:** TS 7 without type-aware linting.
- **Trade-offs:** misses the faster TS 7 compiler. Revisit when typescript-eslint supports it.

## D-008 Anthropic SDK follows the two-week floor
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** choose the SDK version at the start of M6. It should be 2.x if eligible by then: 2.0.0 clears the floor on 2026-11-04.
- **Why:** 1.15.0 is the only eligible release today, and 2.x defaults to API version `2026-10-21`. Starting on 2.x avoids a migration soon after.
- **Trade-offs:** none now, since no SDK code exists before M6.

## D-009 Default model claude-opus-5-5, configurable
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** `CLAUDE_MODEL` defaults to `claude-opus-5-5`, Anthropic's current recommended default. The evaluation can compare Sonnet 5.5 and Haiku 5.5 with authorized runs.
- **Why:** moving to a cheaper model should rest on measured accuracy, and that choice is the owner's. Haiku is roughly 40 times cheaper per token, so it is worth measuring.
- **Trade-offs:** highest per-document cost of the three until measured.

## D-010 Structured outputs with parse, not tool use
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** use `client.messages.parse()` with a Pydantic model, or `output_config.format` directly if the schema needs it.
- **Why:** forced `tool_choice` returns a 400 on Opus 5.5 and Sonnet 5.5, and the model should have no tools at all (see D-013).
- **Alternatives:** strict tool use, plain JSON mode with prompting.
- **Trade-offs:** citations are incompatible, so the review screen cannot highlight source locations from the API. That is acceptable for the MVP.

## D-011 Money as strings in the model schema
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** the model-facing schema uses decimal strings with a simple pattern, and converts to `Decimal` afterwards. The API also carries money as strings.
- **Why:** floats corrupt money, and the API rejects lookahead patterns and numeric constraints. Pydantic's own `Decimal` schema is expected to include a lookahead; this is to be confirmed in M6.
- **Trade-offs:** an extra conversion step, which doubles as a validation point.

## D-012 Confidence is a signal that can only lower trust
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** the model reports `overall_confidence` and `uncertain_fields`. Anything short of `high` with no uncertain fields goes to review. A high score never overrides a failed rule.
- **Why:** model self-confidence is not calibrated, and an injected document could try to raise it. The harness measures whether the signal is useful.
- **Alternatives:** per-field numeric scores, which look precise without being so, and use up schema limits.
- **Trade-offs:** coarse. Real runs may show too many or too few documents going to review.

## D-013 Layered injection defense with honest test scope
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** as SPEC section 6: untrusted-content prompt, document blocks only, no tools, schema-only output, a `contains_embedded_instructions` flag, and code-side rules. CI tests use a compromised-model double; resistance of the real model is measured only in an authorized run.
- **Why:** the brief asks for a test proving an injected document does not change the result. A mock cannot prove that about a model, so the CI test proves the system holds even if the model is fooled, and the real comparison is reported separately.
- **Trade-offs:** an injection that changes values consistently, so that all rules pass, is only caught by the flag or by the model ignoring it. This remaining risk is stated in the README.

## D-014 Queue with leases and at-least-once delivery
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** claim in a short transaction, commit, work outside it, and heartbeat a lease. Handlers are idempotent.
- **Why:** holding a row lock during a model call would pin a connection for its duration and lose work on crash.
- **Alternatives:** session-level advisory locks, a lock held for the whole job, Procrastinate or another queue library.
- **Trade-offs:** a job can run twice after a lease expires, which idempotent handlers must absorb. A library would save code, but the queue is one of the skills on show.

## D-015 A batch is the unit for caps and cost
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** "run" in the cost rule means a batch, one upload request or one evaluation run. The document cap is enforced at upload; the token cap is reserved atomically before each model call.
- **Why:** the brief needs a per-run cap, and a document's own processing is a different kind of run.
- **Trade-offs:** several small uploads bypass the batch cap. The owner-only real-model switch and the Anthropic spend limit cover that.

## D-016 Files on a volume
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** a shared Docker volume, generated storage keys, behind a small `Storage` module.
- **Why:** simplest thing that works for a local demo.
- **Alternatives:** S3-compatible storage, database blobs.
- **Trade-offs:** does not scale past one host; acceptable as there is no hosting.

## D-017 Server-rendered previews
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** render PDF pages to PNG with pypdfium2 in the worker, and show images in the UI.
- **Why:** the browser never parses an untrusted PDF, the CSP stays strict, and there is one preview path for PDFs and images.
- **Alternatives:** pdf.js (a large dependency, and it needs CSP allowances), PyMuPDF (AGPL).
- **Trade-offs:** no text selection in the preview, and rendering costs worker time.

## D-018 Content checks in house
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** a small magic-byte check, then a full decode with Pillow or pypdf.
- **Why:** three formats need only a few lines, and the decode is the real proof. The alternatives are stale or need a system library.
- **Trade-offs:** a little code to own and test.

## D-019 slowapi with in-memory limits
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** slowapi, one API process, keyed by user, or by client IP on sign-in.
- **Why:** no Redis, and one process is all the demo runs.
- **Trade-offs:** limits reset on restart and would not span instances. Behind nginx, the client IP must be read only from the trusted proxy.

## D-020 One backend image, one web image
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** the five Compose services use two images: backend (API, worker, sink, by command) and web (unprivileged nginx). Postgres is the third, stock.
- **Why:** the brief requires five services and the playbook prefers one image. This is the closest fit.
- **Trade-offs:** the sink image carries code it does not use.

## D-021 Host ports
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** Compose project `intakefold`, ports on `127.0.0.1`: web 8180, API 8100, sink 8190, database 5441.
- **Why:** 5432 to 5434 and 8080 are in use by the owner's other projects. All are overridable from `.env`.

## D-022 No hosting; Docker demo
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** one-command Docker run, per the brief's V2 list. A pinned Codespaces dev container is decided at M14.
- **Why:** a hosted demo is out of the MVP.

## D-023 No Batch API, Files API or prompt caching in the MVP
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** one synchronous `messages` call per document, with files inlined as base64.
- **Why:** this is the simplest path, and the cheaper options are not needed at this volume. The Batch API is half price and would suit the evaluation, but would need a second code path.
- **Trade-offs:** evaluation runs cost more than they could.

## D-024 Refusal fallback decided in M6
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** the default plan is to enable server-side `fallbacks` on Opus 5.5, as Anthropic recommends, with the serving model logged in `run_steps`. A refusal that survives goes to review. M6 confirms this works with structured outputs before relying on it.
- **Why:** a fallback runs a different model, so the audit log must show which one, and the price table must follow.
- **Trade-offs:** a beta parameter on a code path that should rarely fire.

## D-025 Playbook kept out of the repository
- **Date:** 2026-10-31. **Status:** approved with Phase 0.
- **Decision:** leave `PROJECT-PLAYBOOK.md` untracked. `CLAUDE.md` carries its rules.
- **Why:** it is the owner's general working method, not part of this product, and the repository is public.
- **Trade-offs:** it must be ignored explicitly in M1, or the owner may prefer to commit it.

## D-026 Repository bootstrap and commit identity
- **Date:** 2026-10-31. **Status:** bootstrap instructed by the owner; identity chosen by the agent.
- **Decision:** the agent made one first commit on `main` and created `dev` from it, as a one-time exception to the rule against pushing to those branches. Commits use the owner's GitHub noreply address, set for this repository only.
- **Why:** the remote was empty and milestones branch from `dev`. The noreply address was recommended in Phase 0 and keeps a personal email out of a public history. The owner did not state a preference.
- **Alternatives:** the owner's personal email, or the owner creating the branches.
- **Trade-offs:** the exception does not extend to any later push. A different address would apply only to new commits, because history is not rewritten without approval.

## D-027 The two-week floor is enforced by tooling
- **Date:** 2026-10-31. **Status:** decided in M1.
- **Decision:** `exclude-newer` in `backend/pyproject.toml` and `--before` on `npm install` set the floor when dependencies change.
- **Why:** this covers transitive packages, which a check of direct pins misses.
- **Trade-offs:** the floor date must be moved by hand when updating.

## D-028 Audit thresholds differ for runtime and dev tooling
- **Date:** 2026-10-31. **Status:** decided in M1, for owner review.
- **Decision:** CI fails on moderate or worse in runtime npm packages and on high or worse in everything. Python packages are audited with no threshold.
- **Why:** an advisory on `minimatch` below 11.0.1, published 2026-10-30, reaches only ESLint tooling. The fix is newer than the floor and outside the `^10.2` range ESLint declares, and `npm audit fix --force` would downgrade ESLint to 4.
- **Alternatives:** an `overrides` entry forcing minimatch 11, which needs the owner's approval as a security exception and may break ESLint.
- **Trade-offs:** moderate dev-tool advisories do not fail CI, so they must be tracked in `PROGRESS.md`.

## D-029 Testing and accessibility libraries follow what is compatible
- **Date:** 2026-10-31. **Status:** decided in M1.
- **Decision:** `httpx2` for FastAPI's test client, because Starlette 1.8 deprecates `httpx`. `eslint-plugin-jsx-a11y` is left out, because it does not support ESLint 10. Accessibility is covered by Testing Library role queries now, and axe in M13 and M14.
- **Trade-offs:** no static accessibility lint until the plugin catches up.

## D-030 Node 24.22.0 in CI
- **Date:** 2026-10-31. **Status:** decided in M1, for owner review.
- **Decision:** CI pins Node 24.22.0. The host's 24.20.0 is accepted by `engines`.
- **Why:** 24.22.1 (2026-10-20) is a security release but under two weeks old, and taking it early needs the owner's approval. Node only runs build and test tools here; nothing ships on it.
- **Trade-offs:** CI runs a known-unpatched Node until the bump, which the floor allows from 2026-11-03.

## D-031 API documentation endpoints are off
- **Date:** 2026-10-31. **Status:** decided in M1.
- **Decision:** `docs_url`, `redoc_url` and `openapi_url` are disabled. M8 revisits how API types reach the front end.
- **Why:** the routes are public by default, which breaks the authentication rule, and their pages load scripts the CSP blocks.

## D-032 Middleware handles unexpected errors itself
- **Date:** 2026-10-31. **Status:** decided in M1.
- **Decision:** one pure ASGI middleware sets the trace ID and headers, writes the request log, and turns unhandled exceptions into problem responses.
- **Why:** FastAPI's `Exception` handler runs outside user middleware, so a 500 there would have no security headers or trace ID. A test covers this.
- **Trade-offs:** slightly more code than `BaseHTTPMiddleware`.

## D-033 Security patches below the two-week floor
- **Date:** 2026-10-31. **Status:** approved by the owner. Supersedes D-030.
- **Decision:** take certifi 2026.10.18, filelock 4.2.1 and Node 24.22.1 before they clear the floor. The two packages use `exclude-newer-package`, so the floor still holds for everything else.
- **Why:** `pip-audit` stopped the push on PYSEC-2026-4320 (certifi bundled root CAs with compromised keys) and 17 filelock advisories, and Node 24.22.1 is a security release. All three are dev or CI only. Neither package is in the runtime tree.
- **Alternatives:** wait about 24 hours for the packages and 3 days for Node.
- **Trade-offs:** less soak time for these three. The entries in `pyproject.toml` can go once `exclude-newer` passes those dates.

## D-034 TRUNCATE is the one way around the audit trigger
- **Date:** 2026-10-31. **Status:** decided in M2, for owner review.
- **Decision:** the append-only trigger is a row trigger, so `UPDATE` and `DELETE` fail but `TRUNCATE` works. A test records this.
- **Why:** the demo reset (AC-22) must clear the audit trail. AC-18 says rows cannot be updated or deleted through SQL, and this meets it for those statements only.
- **Alternatives:** a statement-level `BEFORE TRUNCATE` trigger with a separate privileged role for the reset, which is stronger but adds a second database role to a local demo.
- **Trade-offs:** anyone with table privileges can still erase the trail. A production system would use a restricted application role.

## D-035 Attempts count at claim, and finishing is fenced
- **Date:** 2026-10-31. **Status:** decided in M2.
- **Decision:** `attempts` increases when a job is claimed. Heartbeat, success and failure apply only if the job is running with the same `locked_by` and `attempts`. Stored errors hold an exception type or a safe code, never its message.
- **Why:** a job that kills its worker still runs out of attempts. A worker that lost its lease cannot overwrite the new owner's result. Both parts of the fence are needed, because `requeue` resets attempts, and a mutation run showed that gap in the tests.
- **Trade-offs:** a stale worker's side effects still happen, so handlers must be idempotent.

## D-036 Enums are checked strings
- **Date:** 2026-10-31. **Status:** decided in M2.
- **Decision:** enum columns are `VARCHAR` with a `CHECK` constraint, not native PostgreSQL enums.
- **Why:** changing a value is then an ordinary migration, and removing one is possible.
- **Trade-offs:** Alembic does not detect changes to `CHECK` constraints, so enum changes need a hand-written migration.

## D-037 Seeded users cannot sign in until M3
- **Date:** 2026-10-31. **Status:** decided in M2.
- **Decision:** the seed stores an unusable `!` as the password hash. Four vendors are seeded now; M5 adds the rest.
- **Why:** hashing arrives with M3, and a plain or weak placeholder should never exist.
