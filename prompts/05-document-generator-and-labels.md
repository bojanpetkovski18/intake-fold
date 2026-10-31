# M5: Fictional document generator and labeled set

**Branch:** `#0005-document-generator-and-labeled-set`
**Goal:** a reproducible, realistic, fictional evaluation set with ground truth.
**Estimate:** 7 h

**Context:** SPEC section 13. Data rules in `CLAUDE.md`.
**Re-check:** reportlab, Pillow.

**Scope**
- Seeded generator: at least 5 layouts and 8 invented vendors, invoices and receipts, PDF and image.
- Variation: rotation, noise, blur, low contrast, missing fields, deliberately wrong totals, duplicates, unknown vendors, implausible dates.
- Ground-truth JSON per document, including expected routing and reasons.
- Set of 60 documents: 20 development and 40 held out, with the split fixed by the seed. 8 injection pairs.
- Emails on the `example` domain. Obviously fake phone numbers and tax IDs.
- CLI entry point.

**Out of scope:** scoring (M12).

**Tests required:** same seed gives identical labels; labels agree with what was rendered, including the wrong-total cases; a denylist check on vendor names; each generated file passes the M4 upload checks.

**Acceptance criteria:** AC-20. Search each invented vendor name before committing, and record that the check was done.

**Python notes to flag:** seeded `random.Random` instances, not the global generator.
