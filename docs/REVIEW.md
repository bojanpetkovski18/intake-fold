# Full-codebase review

M16, 2026-11-03, on branch `#0016-full-codebase-review`, from `dev` at `5d75e10` (M14 merged). The brief is `prompts/16-full-codebase-review.md`, the owner's prompt word for word.

## Method

1. **Baseline** before any change: `bash scripts/check.sh` exited 0 with 663 backend tests, 127 front-end tests, the e2e journey three times in a row and no leaks.
2. **Read every tracked source file**, by layer, from the data model up: models and migrations, identity, the API, uploads and storage, review, validation, extraction, the queue and worker, delivery, audit and metrics, demo, evaluation, the sink, then the front end and the infrastructure. Then the tests beside each part.
3. **A finding is confirmed** only by a failing test, or for infrastructure a failing check, shown failing for the right reason before the fix.
4. **Each fix** is its own commit with its regression test. After all fixes, each was undone once by hand to check that its test fails again (13 of 13 did).
5. **A second pass** searched the whole codebase for what the project rules forbid: wall-clock time outside the clock, floats, SQL built from strings, type escapes without a reason, stray output.
6. **Self-review** of the diff found one more problem, in a fix of this review (finding 7).

## Coverage

| Area | Files | Depth |
|---|---|---|
| Data model, migrations, engine, clock, logging | `db/`, `migrations/`, `clock.py`, `logging.py` | Read in full |
| Identity and access | `identity/`, `api/access.py`, `api/auth.py`, `api/rate_limit.py` | Read in full |
| API core | `api/app.py`, `api/middleware.py`, `api/problems.py`, `api/health.py` | Read in full |
| Uploads and storage | `api/documents.py`, `documents/checks.py`, `intake.py`, `storage.py`, `rendering.py`, `queries.py` | Read in full |
| Review | `api/review.py`, `documents/review.py`, front-end `review/` | Read in full |
| Validation | `validation/` | Read in full |
| Extraction | `extraction/` | Read in full |
| Queue and worker | `jobs/`, `worker/`, `api/jobs.py` | Read in full |
| Delivery and export | `delivery/`, `api/delivery.py`, `intakefold_sink/` | Read in full |
| Audit and metrics | `audit/`, `api/insight.py` | Read in full |
| Demo | `demo.py`, `api/demo.py`, `db/seed.py` | Read in full |
| Evaluation | `eval/` | Read in full |
| Generator | `generator/` | Read at the level of its entry point, plan and labels; it is offline tooling that writes the committed labeled set, and AC-20's tests cover it. Not read line by line |
| Front end | `src/api/`, `src/screens/`, `src/components/`, `AppLayout`, routes | Read in full |
| End to end | `frontend/e2e/`, `scripts/e2e.sh` | Read in full (written in M14) |
| Infrastructure | Dockerfiles, `compose.yaml`, `nginx.conf`, `.devcontainer/`, CI workflow, `scripts/` | Read in full |
| Tests | every test file beside the part above | Read for what each part's tests cover; not every assertion re-derived |
| Not reviewed | `data/labeled/` documents and labels, images, `uv.lock`, `package-lock.json` | Generated data and lock files. Dependencies are covered by `pip-audit` and `npm audit` in CI |

## Findings fixed

| # | Severity | Where | Root cause | Fix | Regression test |
|---|---|---|---|---|---|
| 1 | High | `documents/review.py` | When extraction fails there is no invoice. A save that created the invoice but changed no field returned before the rules ran, so approval found no failed rule and approved an empty invoice without a reason, and delivered it. Reachable from the UI by changing only the document type. | A created invoice counts as a change, so the rules run and the version moves on | `test_an_empty_save_on_a_failed_extraction_still_runs_the_rules` |
| 2 | Medium | `extraction/schema.py` | The extraction schema had no length limit on vendor name and invoice number, but the columns are 200 and 100 characters. A longer model answer validated, then failed the insert after the call was paid for, and every job retry paid again. | Length limits checked on the response, so the model gets a repair request. `transform_schema` keeps them out of the API schema. `SCHEMA_VERSION` is now `2026-11-03.1` | `test_text_longer_than_its_column_is_repaired_not_stored` |
| 3 | Medium | `validation/normalize.py`, both callers | A vendor or invoice number made only of punctuation normalized to an empty string, and every such invoice from a vendor matched as a duplicate. | One helper, `invoice_keys`, returns no key for an empty result, so such an invoice is compared by date and total | `test_numbers_with_no_letters_or_digits_do_not_all_match`, `test_a_value_that_normalizes_to_nothing_has_no_duplicate_key` |
| 4 | Low | `delivery/signing.py` | `hmac.compare_digest` raises on non-ASCII text, so a signature header with such a character made the sink answer 500 instead of refusing it. | Compare bytes | a case in `test_malformed_headers_fail` |
| 5 | Low | `documents/intake.py` | Checked files are written before the batch transaction, so a failed commit left them on disk with no row. | Delete the batch's files when the transaction fails | `test_a_batch_that_fails_to_save_leaves_no_files_behind` |
| 6 | Low | `documents/intake.py` | Display names kept bidirectional overrides, so `invoice<U+202E>fdp.exe` showed as `invoiceexe.pdf`. `display_filename` had no tests. | Strip bidirectional marks, overrides and isolates | `test_display_filename_keeps_only_what_is_safe_to_show` (10 cases) |
| 7 | Low | `documents/intake.py` (from fix 6) | The editor tool stored the escapes of fix 6 as the invisible characters themselves, the very thing the pattern removes. Found in self-review. | ASCII escapes only, and a repository check that fails on bidirectional controls in any tracked text file | The check in `scripts/check.sh repository`, shown failing on a planted file |
| 8 | Low | `frontend/src/api/client.ts` | A 2xx upload answer that was not JSON threw inside the XHR handler, so the promise never settled and the upload stayed busy. | Reject with an error the page shows | "shows an error, not a stuck upload, when a success answer is not JSON" |
| 9 | Low | `audit/records.py` | A permanent failure was logged under its type, `PermanentJobError`, so the document log never said what went wrong. | Record the error's code, which is safe to store by contract | `test_a_permanent_failure_records_its_code_not_its_type` |
| 10 | Low | `jobs/dead_letters.py` | A delivery job names its delivery, not its document, so the dead-letter list showed only `deliver_webhook`. | Join through the delivery | `test_dead_delivery_is_listed_with_its_document` |

Found and fixed in M14 by the e2e journey, listed for completeness: a requeued dead delivery was never sent again, and nginx kept proxying to a replaced API container's old address.

## Reviewed and left as they are

- **Duplicates re-checked during review compare against later documents too.** When a reviewer corrects the first of two copies, the rules run again and flag it against the second. SPEC section 7 says "no other non-rejected document", so this matches the spec; D-057 describes only first routing. The owner decides whether the first copy should stay unflagged (D-087).
- **A session that expires mid-review** shows "Sign in to continue." on the next action, without sending the reviewer to the sign-in page. Queries do redirect. The message is accurate, and nothing is lost.
- **The rate limiter is per process and in memory** (as documented). One API process runs.
- **`install-tools.sh` does not re-check a tool already in `.tools/`.** A version bump needs that folder deleted. CI starts with none.
- **Foreign keys without an index** (`run_steps.job_id`, `audit_events.actor_user_id`, `sessions.user_id`): not used for lookups at this scale.
- **Pattern search hits:** `time.time()` in the rate limiter and the sink (wall-clock seconds for their own libraries), the `TRUNCATE` built from model table names, seven commented type escapes around `pypdfium2` and `pydantic-settings`, and `print` in three command-line tools. Each is deliberate.

## Validation

| Check | Result |
|---|---|
| Mutation check: each fix undone by hand | 13 of 13 caught by their tests |
| Full gate and Linux container | see `PROGRESS.md`, "Measured results", and the PR |

## Remaining issues

None found that can be fixed without the owner. D-087 is the one open question. The known issues in `PROGRESS.md` stand; this review added none.

## Assessment

The codebase was in good shape before the review: strict types, thin routes, rules in code, and a test at every layer. The review found one real correctness bug (finding 1), which let an empty invoice be approved without a reason. It also found one cost bug on the real-model path that no mock run could show (finding 2). Everything else was edge cases at trust boundaries: hostile header bytes, file names, odd invoice numbers. The weakest area was input that is valid to the schema but not to the database. The tests were strongest where the spec was explicit, and missing where a helper had no acceptance criterion of its own (`display_filename`).
