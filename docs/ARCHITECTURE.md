# Intakefold architecture

**Outline only.** Written before any code exists. It is rewritten from the code as milestones land, and claims here are intent until then.

## Containers

```
browser
   |
  web (nginx: static React build, proxies /api)
   |
  api (FastAPI) ----------- postgres (data and job queue)
                               |
  worker (same image) ---------+
     |        |
     |        +--> sink (demo webhook receiver)
     +--> Claude API (only when EXTRACTOR=claude)

  api and worker share a file volume for documents and rendered pages.
```

## Processes

- **api:** thin routes that authenticate, validate, and call handlers. It never calls the model.
- **worker:** claims one job at a time with `FOR UPDATE SKIP LOCKED`, commits, then does the work outside a transaction, with a background thread renewing the lease. On a stop signal it finishes the current job and exits. Run more workers for concurrency.
- **sink:** a separate small app with no access to the database.
- **web:** `frontend/nginx.conf` serves the build with a strict CSP and proxies `/api` (D-078). M14 puts it in an image.

## Boundaries

- `Extractor` is the seam between the pipeline and the model. Tests and the default demo use the mock.
- Tokens are reserved per batch before a model call, in one SQL statement, then settled to actual use.
- Model output is proposed data. It crosses into the domain only after Pydantic validation.
- Rules and routing are pure functions over domain objects, so they are tested without a database or a model. `validation/apply.py` is the only part that touches the database.
- Every external call happens outside a database transaction.
- Uploads are read after the access checks, one file at a time. pypdf and Pillow decode them in the API; PDFium runs only in the worker.
- `enforce_access` runs on every route. Authentication is on unless a route is listed in `PUBLIC_ROUTES`.

## Reliability

- At-least-once jobs with idempotent handlers, leases, backoff and a dead state.
- Delivery jobs are written in the approval transaction, and sent with no database connection held.
- Run steps are written as work happens, so a crash leaves a trace. Metrics are read from them and from document status, in SQL.
- In demo mode the seed uploads the demo set as an ordinary batch, so the worker processes it like any upload. The admin reset truncates the document tables under a table lock, deletes their files after the commit, and uploads the set again (D-076).

## To be written from the code

Request flow, concurrency, external integrations, data model diagram, delivery.
