# Research notes

Time-sensitive facts with sources. All entries checked **2026-10-31** unless dated otherwise. The two-week floor on that date is **2026-10-17**. Re-check at the start of the milestone that uses each one.

## M2 re-check (2026-10-31)

SQLAlchemy 2.1.5 and Alembic 1.20.0 remain the newest releases past the floor (2.1.6 and 1.20.1 are from 2026-10-21 and 2026-10-22). Web searches for the four seeded vendor names found no business using them: Quillbrook Office Supply, Tarnwell Freight, Morrowfen Catering, Ostrel Print Works. A search is not proof a name is unused. [Quill](https://en.wikipedia.org/wiki/Quill_Corporation) is a real office supply brand with a similar-looking name; "Quillbrook" is a different word, but M5 should reconsider it.

## Local tools

Checked with the commands listed. Windows 11 Pro 10.0.26200.

| Tool | Result |
|---|---|
| Python | **Not installed.** `python` is only the Microsoft Store alias; there is no `py` launcher |
| uv | Not installed at first; 0.13.1 installed with winget on 2026-10-31, the highest release past the two-week floor |
| Node / npm | 24.20.0 / 11.19.0 |
| pnpm | Not installed; not needed |
| Docker / Compose | 29.8.2 / v5.5.1; daemon running; 16 CPUs and 6.7 GiB visible to Docker |
| Git | 2.56.0.windows.2; `core.autocrlf=true`; no `user.name` or `user.email` configured |
| GitHub CLI | Not installed; not needed, since the owner opens PRs |

Host ports already listening: 5432, 5433, 5434, 8080. Containers also publish 1025 and 8025.

## Repository

`bojanpetkovski18/intake-fold` on GitHub (renamed from `file-fold` on 2026-10-31) is **public** by the owner's choice, with default branch `main`.

## M1 re-check (2026-10-31)

All pins above and below were confirmed by resolving with the floor in place. Changes and additions:

| Item | Result | Note |
|---|---|---|
| Python | 3.15.0 | Patches 3.15.1 and 3.15.2 clear the floor on 2026-11-04 and 2026-11-08 |
| `python:3.15.0-slim` | `sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58` | For M14 |
| `postgres:18.6-alpine` | `sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5` | Same digest as `18-alpine` |
| Node | 24.22.1 (2026-10-20) | Security release, taken below the floor with owner approval (D-033) |
| certifi | 2026.10.18 | Fixes PYSEC-2026-4320. Below the floor with owner approval (D-033) |
| filelock | 4.2.1 | Fixes 17 advisories. Below the floor with owner approval (D-033) |
| `httpx2` | 2.13.1 (2026-09-23) | Replaces `httpx`, which Starlette 1.8 deprecates for its test client |
| actions/checkout | v7.0.1, `3d3c42e5aac5ba805825da76410c181273ba90b1` | |
| actions/setup-node | v7.1.0, `949feb2413d6458794dcd2491c4babbbce0c15c1` | |
| astral-sh/setup-uv | v10.3.0, `1c37ad07a6a961277cf70c0d37d6f313000f5884` | |
| gitleaks | 8.30.1 | Linux and Windows SHA-256 in `scripts/install-tools.sh` |
| actionlint | 1.7.12 | As above |
| editorconfig-checker | 4.0.2 | As above |
| `eslint-plugin-jsx-a11y` | 6.10.2 | Rejected: peer range stops at ESLint 9 |
| minimatch advisory | [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249), published 2026-10-30, fixed in 11.0.1 | Reaches dev tooling only. See D-028 |

## Runtimes

| Runtime | Finding | Source |
|---|---|---|
| Python | 3.15.0 released 2026-10-09; 3.15.2 and 3.14.10 on 2026-10-25. Bugfix support to 2028-10 | [python.org](https://www.python.org/api/v2/downloads/release/), [endoflife.date](https://endoflife.date/python) |
| Node | 24 LTS to 2028-04; 26 became LTS 2026-10-28 | [endoflife.date](https://endoflife.date/nodejs) |
| PostgreSQL | 18.6 (2026-08-11), supported to 2030-11 | [endoflife.date](https://endoflife.date/postgresql) |

Re-checked 2026-10-31 for M3 on the PyPI JSON API: argon2-cffi 25.1.0 and limits 5.8.0 are the highest eligible. slowapi 0.1.10 was dropped: on Python 3.15 its decorator calls `asyncio.iscoroutinefunction`, deprecated with removal in 3.16, and it fails strict pyright (D-038).

Re-checked 2026-10-31 for M4 on the PyPI JSON API: python-multipart 0.0.32 (0.0.33 is under the floor until 2026-11-14), Pillow 13.0.0 and pypdfium2 5.14.0 are the highest eligible. pypdf 6.21.0 is the highest eligible but `pip-audit` lists 11 advisories fixed by 6.21.1 to 6.21.4, so 6.21.4 (2026-10-28) is taken as an approved exception (D-043).

Re-checked 2026-11-01 for M5 on the PyPI JSON API: reportlab 5.0.1 (2026-08-20) is the highest eligible, and 5.1.0 (2026-10-22) is under the floor until 2026-11-05. Pillow stays at 13.0.0. reportlab's output differs between Windows and Linux in compressed streams, so byte reproducibility holds per platform (D-050).

Vendor name check, 2026-11-01: exact-phrase web searches for Brindlecote Stationers, Harrowmere Cleaning, Velloway Electrical, Cindergate Joinery, Pellandine Water, Drovemoor Tools, Lunnick Textiles and Zenthorpe Packaging found no business with that name. This was a web search only, not a trademark or company-registry search. Yarrowgate Couriers also found none, but was dropped as too close to Yellowgates Courier Ltd. Quillbrook was replaced because it resembles the Quill brand. Tarnwell, Morrowfen and Ostrel were searched in Phase 0.

Re-checked 2026-11-01 for M6, with the Claude API skill (2.1.314) and live docs. Prices for Opus 5.5, Sonnet 5.5 and Haiku 5.5 match the table below. Fallback is at `build-with-claude/refusals-and-fallback`; the older URL returns 404. Token counting accepts base64 PDFs and images, and the count is an estimate. The structured outputs page says nothing about fallback, and the fallback page says only that an entry can override `output_config`, so the combination is unconfirmed until a real run. anthropic 1.15.0 (2026-10-15) is the highest eligible; 1.16.0 and 1.17.0 are from 2026-10-20 and 2.0.0 from 2026-10-21. 1.15.0 sends API version `2023-06-01`.

Re-checked 2026-11-01 for M7 on the PyPI JSON API: hypothesis 6.170.1 (2026-10-16, MPL-2.0) is the highest eligible, as a dev dependency only.

Native packages at the versions below have wheels for Python 3.15 on Windows and Linux x86-64 (pydantic-core, SQLAlchemy, psycopg-binary, Pillow directly; argon2-cffi-bindings by abi3; pypdfium2 by py3-none). Source: PyPI JSON API.

Image digests observed, to be re-read and pinned in M1:

| Image | Digest | Updated |
|---|---|---|
| `python:3.15-slim` | `sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913` | 2026-10-28 |
| `python:3.14-slim` | `sha256:cd89c30eda26ee911a4611b18680086e0ea42e6f5f8cbe653d07fa7958c9cec8` | 2026-10-28 |
| `postgres:18-alpine` | `sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5` | 2026-10-26 |

These are the multi-architecture index digests reported by Docker Hub.

## Python packages

Highest stable release published on or before 2026-10-17, from the PyPI JSON API.

| Package | Pin today | Latest | Published | Licence |
|---|---|---|---|---|
| fastapi | 0.143.3 | 0.162.0 | 2026-10-16 | MIT |
| uvicorn | 0.54.0 | 0.54.0 | 2026-09-25 | BSD-3 |
| sqlalchemy | 2.1.5 | 2.1.6 | 2026-10-16 | MIT |
| alembic | 1.20.0 | 1.20.1 | 2026-09-11 | MIT |
| psycopg + psycopg-binary | 3.3.6 | 3.3.6 | 2026-09-18 | LGPL-3 |
| pydantic | 2.14.1 | 2.14.2 | 2026-10-11 | MIT |
| pydantic-settings | 2.16.0 | 2.16.2 | 2026-10-14 | MIT |
| anthropic | 1.15.0 | 2.3.0 | 2026-10-15 | Apache-2.0 |
| python-multipart | 0.0.32 | 0.0.33 | 2026-06-04 | Apache-2.0 |
| structlog | 26.1.0 | 26.1.0 | 2026-06-06 | MIT or Apache-2.0 |
| argon2-cffi | 25.1.0 | 25.1.0 | 2025-06-03 | MIT |
| limits | not pinned here | 5.8.0 | 2026-02-05 | MIT |
| pillow | 13.0.0 | 13.0.0 | 2026-10-16 | MIT-CMU |
| pypdf | 6.21.4 (D-043) | 6.21.4 | 2026-10-28 | BSD-3 |
| pypdfium2 | 5.14.0 | 5.14.0 | 2026-10-04 | BSD-3 or Apache-2.0 |
| reportlab | 5.0.1 | 5.1.0 | 2026-08-20 | BSD |
| pytest | 9.1.1 | 9.2.0 | 2026-06-19 | MIT |
| testcontainers | 4.15.0 | 4.15.0 | 2026-07-24 | Apache-2.0 |
| hypothesis | 6.170.1 | 6.170.14 | 2026-10-16 | MPL-2.0 |
| ruff | 0.17.1 | 0.17.3 | 2026-10-15 | MIT |
| pyright | 1.1.414 | 1.1.414 | 2026-09-10 | MIT |
| pip-audit | 2.10.1 | 2.10.1 | 2026-06-10 | Not stated in PyPI metadata |
| uv | 0.13.1 | 0.13.6 | 2026-10-14 | MIT or Apache-2.0 |

OSV returned no advisories for python-multipart 0.0.32 or fastapi 0.143.3. The other packages were not checked; `pip-audit` covers them in CI from M1.

Rejected: PyMuPDF, because it is AGPL. `python-magic`, because it needs libmagic and was last released in 2022. `filetype`, also last released in 2022.

## Front-end packages

Highest stable release on or before 2026-10-17, from the npm registry.

| Package | Pin today | Latest | Published |
|---|---|---|---|
| react, react-dom | 19.3.1 | 19.3.1 | 2026-10-14 |
| typescript | **6.0.3** | 7.0.2 | 2026-04-16 |
| vite | 8.3.4 | 8.3.5 | 2026-10-08 |
| @vitejs/plugin-react | 6.1.2 | 6.1.2 | 2026-10-05 |
| vitest | 5.0.5 | 5.0.5 | 2026-10-15 |
| @testing-library/react | 16.3.3 | 16.3.3 | 2026-08-27 |
| @playwright/test | 1.64.1 | 1.64.1 | 2026-10-14 |
| @axe-core/playwright | 4.14.0 | 4.14.0 | 2026-10-15 |
| eslint | 10.13.0 | 10.14.0 | 2026-10-16 |
| typescript-eslint | 8.71.2 | 8.72.1 | 2026-10-12 |
| prettier | 3.9.10 | 3.9.10 | 2026-10-10 |
| react-router | 8.4.0 | 8.5.1 | 2026-09-15 |
| @tanstack/react-query | 5.104.3 | 5.105.0 | 2026-10-15 |

TypeScript 7 is blocked: typescript-eslint's peer range is `>=4.8.4 <6.1.0`, on both the pinned and the latest release.

## Anthropic API

Sources: the Claude API skill bundled with Claude Code (cached 2026-10-06) and the live docs fetched today. **Where they differed, the live docs are recorded here:** the bundled guidance gave a 32 MB request limit for PDFs, while the live page says 128 MB.

### Models and pricing

Per million tokens. [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), [models overview](https://platform.claude.com/docs/en/about-claude/models/overview).

| Model | ID | Input | Output | Cache read | 5m cache write | Batch in/out |
|---|---|---|---|---|---|---|
| Claude Opus 5.5 | `claude-opus-5-5` | $4 | $20 | $0.20 | $5 | $2 / $10 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | $2 | $10 | $0.10 | $2.50 | $1 / $5 |
| Claude Haiku 5.5, up to 100K-token prompts | `claude-haiku-5-5` | $0.10 | $0.50 | $0.01 | $0.125 | $0.05 / $0.25 |

All three have a 1M-token context window and 128K max output. Haiku 5.5 costs $0.50 / $2.50 for prompts over 100K tokens, which Intakefold's input limit keeps it below. Anthropic describes Haiku as suited to extraction and Opus as its general default; only measurement can settle it for this workload.

### Document and image input

- **PDF** ([docs](https://platform.claude.com/docs/en/build-with-claude/pdf-support)): `document` block with a base64 source. 128 MB request on the first-party API; 600 pages (100 when the context window is under 1M). No passwords or encryption. Each page is converted to an image and its text extracted. Text costs about 1,500 to 3,000 tokens per page, plus image tokens.
- **Images** ([docs](https://platform.claude.com/docs/en/build-with-claude/vision)): 8000 x 8000 px maximum, 10 MB base64-encoded per image on the Claude API, up to 600 images per request. Costs follow the page's table, for example 1,296 tokens for a 1000 x 1000 image.
- Upright pages are recommended, so rotated test documents are a fair stress test.

### Structured output

[Docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

- `output_config.format` with `type: json_schema`, or `client.messages.parse()` with a Pydantic model. Beta headers are no longer required. Opus 5.5, Sonnet 5.5 and Haiku 5.5 are all supported.
- Not supported: numeric constraints, `minLength`/`maxLength`, lookahead in `pattern`, recursion, array constraints beyond `minItems` 0 or 1. Objects need `additionalProperties: false`.
- Limits across a request: 24 optional parameters and 16 union parameters.
- Output may not match the schema on `stop_reason: refusal` or `max_tokens`. Enum casing may vary, so compare case-insensitively.
- Citations are incompatible with `output_config.format` (returns a 400; from the bundled skill, as the live page's final section was not read).

### Model behaviour relevant to this project

From the bundled skill, re-checked against skill version 2.1.314 on 2026-11-01:

- On Opus 5.5 and Sonnet 5.5, forced `tool_choice` returns a 400, so forced tool use is not an option. Structured outputs are the right route.
- Opus 5.5 thinking cannot be disabled; depth is set with `output_config.effort`, whose default is `medium`.
- `temperature` and other sampling parameters are rejected on current models, so a repeated run is not guaranteed to be identical.
- Refused requests return `stop_reason: refusal`. Server-side `fallbacks` can retry on another model. The model that served a response must be logged.
- Prefill is removed.

### SDK

- `anthropic` 1.0.0 (2026-08-20) moved to `httpx2`.
- `anthropic` 2.0.0 (2026-10-21) is breaking and adds API version `2026-10-21` as its default. It is under two weeks old until 2026-11-04. On that API version, `temperature`, `top_p` and `top_k` return a 400 ([changelog](https://github.com/anthropics/anthropic-sdk-python/blob/main/CHANGELOG.md), [migration guide](https://platform.claude.com/docs/en/api/migration-2026-10-21)).

### Limits

[Rate limits](https://platform.claude.com/docs/en/api/rate-limits): Start tier gives Opus 5.5, Sonnet 5.5 and Haiku 5.5 each 4,000 RPM, 2M input TPM and 400K output TPM, with a $500 monthly spend cap. New organizations may start in a lower Evaluation tier. A spend-cap 429 has no `retry-after` and should not be retried; `error.details.error_code` is `enforced_spend_limit_reached`.

## Name check

| Where | Filefold | Intakefold |
|---|---|---|
| PyPI | Free | Free |
| npm | Free | Free |
| GitHub | No notable project; closest `TerryHank/FilefoldAI`, 2 stars | 0 repositories |
| Web | **filefold.com is a live product**, a client file portal with AI retrieval | No product found; intakefold.com did not respond |

Also near "Filefold": FileFolder (AI file tool), Fold & File (mobile app, Android package `com.filefold`). This is not a trademark search, and an unresponsive domain may still be registered.

Owner chose Intakefold on 2026-10-31.

## Planning estimate of model cost

**An estimate, not a measurement.** Assumes a one-page invoice at 5,000 input and 1,500 output tokens, including thinking, with no retries or caching.

| Model | Per document | 68 documents (60 + 8 injected) |
|---|---|---|
| Opus 5.5 | about $0.05 | about $3.40 |
| Sonnet 5.5 | about $0.025 | about $1.70 |
| Haiku 5.5 | about $0.00125 | about $0.09 |

Paired injection runs and repeats add to this. Real figures go in `PROGRESS.md` after an authorized run.
