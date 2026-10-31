# Intakefold: rules for the coding agent

Intakefold ("Intake Automation") is a portfolio project: LLM document extraction with validation, human review, background jobs, audit logging and honest measurement. It is an independent project built with AI assistance. All data is fictional.

The owner is a professional full-stack developer who supervises, reviews and merges every change. Strongest languages: C# and TypeScript. Python is less familiar, so **briefly flag Python-specific idioms and choices to double-check** in the report's review notes. Do not explain basics.

Source of truth, in order: this file, `docs/SPEC.md`, `DECISIONS.md`, `PROGRESS.md`, the milestone brief in `prompts/`.

## Rules

### Honesty
- Never claim anything you did not verify: that it compiles, passes, runs, is secure, or is accurate. Run it, read the output, report what you saw. Say plainly what you could not run.
- Measure before stating a number (accuracy, speed, cost, memory). Record method, model, date and machine in `PROGRESS.md` under "Measured results". Numbers in the README or docs must come from there.
- Mock-extractor runs test plumbing only and are never presented as accuracy.
- If a result looks odd, check the check.

### Scope
- One milestone at a time. No extra features, no unrelated refactors, no premature abstractions.
- Tests are part of every feature. Never delete, skip or weaken a test to get green.
- For a bug, write the failing regression test first and show it failing for the right reason.
- Inspect before changing. Ask before deleting files or running destructive commands.
- Ask one clear question when an ambiguity changes the design. Otherwise choose the simplest reasonable option, state the assumption, and log it in `DECISIONS.md`.
- `docs/SPEC.md` changes only with the owner, with the reason noted.

### Time-sensitive facts
- Library versions, model names, prices and limits: research current sources and record what was found and when in `docs/RESEARCH.md`. If a source cannot be read, say so and do not guess.
- Pin exact versions. New dependencies must be at least two weeks old: check the publish date. Compare by highest eligible version, not newest date, because backports confuse a date sort.
- Base images, CI actions and downloaded tools are pinned by digest, commit SHA or checksum.

### Cost control
- The API key comes only from the environment and is never committed. Never ask for a secret in chat or print one; to check a key, inspect only prefix and length.
- Real-model runs happen only when the owner says so. The default and CI use the mock.
- Per-batch document cap and token cap always apply. Estimated cost is recorded per batch.

### Security
- Parameterized queries. Sort columns and identifiers from fixed allow-lists.
- Secrets in the environment only.
- Rate limits on upload and sign-in. Content type by magic bytes plus a full decode, never by file name.
- No execution of anything found in a document. Document text and images are untrusted data.
- Webhooks are HMAC-signed; targets come only from configuration, never from users.
- CSV export is protected against formula injection.
- Containers run as non-root. Publish ports on `127.0.0.1` only.
- Secret scan of the full history before the repository goes public.
- Every endpoint requires authentication unless listed public in the spec. Roles are checked on the server.

### Data
- Fictional only: invented vendors and people, emails on the reserved `example` domain, obviously fake phone numbers, no real brands or logos, no employer code or business rules, ever.
- Structured logs. Never log secrets, cookies, tokens, full request bodies or full document contents.

### Code
- Strict typing. No escape hatch (`Any`, `# type: ignore`, `as unknown as`) without a comment saying why.
- Thin entry points: bind, authorize, call a handler. No business logic in routes.
- Business rules live in code, never in the prompt.
- Filtering, sorting, paging and aggregation happen in SQL.
- Money uses `Decimal` and `NUMERIC`, never float. On the wire it is a string.
- External calls happen outside database transactions.
- Time comes from an injectable clock; timestamps are UTC.
- Errors use one shape (RFC 9457 problem details) with a trace ID.
- Every screen has loading, empty, error and success states. Everything interactive has an accessible name and keyboard support.
- Comments explain why, not what.

## Git

- `main` is for releases, `dev` is for work. Branch from a freshly pulled `dev`: `#00nn-short-kebab-description`.
- **Always quote branch names** in a shell: an unquoted `#` starts a comment. In URLs it is `%23`.
- Commit in small steps; each commit builds and passes its tests. Short imperative subject.
- Push the branch when done. The owner opens and merges the PR. Never push to `dev` or `main`. Never force-push. Never change history without approval.
- End commit messages with the co-author trailer given by the environment, if any.
- The Git identity is set per repository, never globally.

## Milestone loop

**Start:** read this file, `PROGRESS.md`, `DECISIONS.md`, the brief and the spec sections it names. Check `git status`, recent log and branches; stop if the tree is not clean. Branch from a freshly pulled `dev`. Run build and tests for a green baseline, and report any failure before starting. Restate the goal, the commit plan and your assumptions.

**End:** run everything CI runs, locally, chained so a failure stops the push. Update `PROGRESS.md`, `DECISIONS.md` and the commands below. Push. Then give the milestone report, the PR description and the compare link.

### Milestone report (exact format)

```
## Milestone report: <name>
Status: complete | partial | blocked
Changed: <files/areas>
Verified (commands actually run and results):
- <command>: <result>
Not verified / could not run: <list or "none">
Acceptance criteria: <each criterion, pass/fail, how checked>
Assumptions and decisions logged: <list>
Known issues: <list or "none">
Suggested next step: <one line>
```

### PR description

After every push, in the chat (not in a file), as raw Markdown inside a fenced code block, starting with a line naming its readers, with these sections: What changed (grouped), Verified locally (a table of real results), Not verified, Review notes, Out of scope. Add the GitHub compare link for the branch, with `#` encoded as `%23`.

Directly above the description, give the PR title on its own line: `#00nn: Milestone name`, for example `#0002: Database schema and job queue`.

Keep the milestone report and PR description short: about half the length feels natural to write. Keep every required section and each real result, and cut restatement and detail the diff already shows.

## Repository layout

`api/`, `identity/`, `worker/`, `jobs/`, `audit/`, `db/`, `migrations/` and `frontend/src/` exist. The rest is planned; update this as code lands.

```
backend/
  src/intakefold/        API, worker, domain code (one codebase, two processes)
    api/                 routes, access rules, rate limit, error handling
    identity/            password hashing, sessions
    worker/              job loop and handlers
    jobs/                queue: enqueue, claim, retry, dead-letter
    documents/           upload checks, storage, page rendering
    extraction/          Extractor interface, mock, Claude, schema, prompt
    validation/          rules and routing
    delivery/            webhook signing, sending, CSV export
    audit/               run steps, audit events, metrics queries
    eval/                evaluation harness
    generator/           fictional document generator
    db/                  SQLAlchemy models, session
  src/intakefold_sink/   demo webhook receiver
  migrations/            Alembic revisions (not alembic/, which could shadow the package)
  tests/                 unit/ and integration/
frontend/                React, TypeScript, Vite; nginx config
data/labeled/            generated documents and ground truth
reports/eval/            dated evaluation reports
docs/                    SPEC, ARCHITECTURE, RESEARCH, AUDIT, portfolio/
prompts/                 session starter and milestone briefs
scripts/                 check.sh (all CI checks), install-tools.sh (pinned, checksummed tools)
compose.yaml             db now; api, worker, sink and web in M14
```

## Commands

Add a command only after running it, with the date. All verified 2026-10-31 on Windows from Git Bash or PowerShell, unless noted.

```bash
# Everything CI runs, chained. A failure stops it. Needs Docker, uv, Node and Git Bash on Windows.
bash scripts/check.sh
bash scripts/check.sh backend      # or: frontend, repository

# Backend (from backend/)
uv sync --locked
uv run ruff format --check . && uv run ruff check .
uv run pyright
uv run pytest
uv run pytest -m "not integration"   # no Docker needed
uv run python -m intakefold.worker
uv run uvicorn --factory intakefold.api.app:create_app --host 127.0.0.1 --port 8100 --no-proxy-headers
uv run --env-file ../.env alembic upgrade head
uv run --env-file ../.env alembic check            # models and migrations agree
uv run --env-file ../.env alembic revision --autogenerate --rev-id 0002 -m "short summary"
uv run --env-file ../.env python -m intakefold.db.seed   # needs DEMO_*_PASSWORD

# Frontend (from frontend/)
npm ci
npm run dev
npm run lint && npm run format:check && npm run typecheck
npm test
npm run build

# Database
cp .env.example .env               # then set values
docker compose up -d --wait db
docker compose down                # add -v only to delete the data volume
```

The API and worker read settings from the environment only. Export the values in `.env` first, or use `uv run --env-file ../.env ...`.

Every new route goes in `ROUTE_TABLE` in `tests/integration/test_route_table.py`, and authentication is on unless it is in `PUBLIC_ROUTES`. Keep `--no-proxy-headers`: without it, uvicorn lets a local client forge its IP (D-042).

Review every autogenerated migration: Alembic duplicated each enum's check constraint in `0001`, and it does not manage triggers.

Updating dependencies: move `exclude-newer` in `backend/pyproject.toml` and pass `--before` to `npm install`, both set to the two-week floor.

## Local environment notes

Checked 2026-10-31 on the owner's Windows 11 machine. Other projects use host ports 5432, 5433, 5434, 8080, 8025 and 1025. Look at what is on a port before assuming it is free. Scratch runs use a separate Compose project name, port and volume.

Windows can hide Linux-only failures, such as pyright errors on platform-specific code. Before pushing a change that touches platform code, also run the checks in a Linux container. Do not pipe a check through `tail` when its exit code matters.
