# M4: Upload and documents API

**Branch:** `#0004-upload-and-documents-api`
**Goal:** accept untrusted files safely and queue them.
**Estimate:** 7 h

**Context:** SPEC sections 4, 5 and 11. D-015, D-016, D-017, D-018.
**Re-check:** python-multipart (0.0.33 was published 2026-10-31, too new for the floor until 2026-11-14), Pillow, pypdf, pypdfium2.

**Scope**
- `Storage` module on a volume with generated keys.
- Content checks: magic bytes, full decode, size, pages, dimensions, pixel cap, encrypted PDF refusal. Image re-encoding and metadata stripping.
- `POST /documents` creating a batch and enqueuing `process_document`, with SHA-256 idempotency and a rate limit.
- `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/pages/{n}`.
- Worker handler that renders pages and stops at a placeholder extraction step, writing `run_steps`.

**Out of scope:** extraction, rules, UI.

**Tests required:** each refusal; wrong extension both ways; polyglot file; pixel bomb; malformed PDF; path traversal in the file name; deduplication; batch cap; pagination; sort allow-list; EXIF removed; extend the route-table test.

**Acceptance criteria:** AC-01, AC-02, AC-03, and the upload half of AC-26.

**Python notes to flag:** upload streaming with `UploadFile`, Pillow decompression-bomb settings, PDFium parsing untrusted input.
