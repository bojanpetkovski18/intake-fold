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
- **worker:** claims one job at a time with `FOR UPDATE SKIP LOCKED`, commits, then does the work outside a transaction. Run more workers for concurrency.
- **sink:** a separate small app with no access to the database.

## Boundaries

- `Extractor` is the seam between the pipeline and the model. Tests and the default demo use the mock.
- Model output is proposed data. It crosses into the domain only after Pydantic validation.
- Rules and routing are pure functions over domain objects, so they are tested without a database or a model.
- Every external call happens outside a database transaction.

## Reliability

- At-least-once jobs with idempotent handlers, leases, backoff and a dead state.
- Delivery jobs are written in the approval transaction.
- Run steps are written as work happens, so a crash leaves a trace.

## To be written from the code

Request flow, auth, concurrency, external integrations, data model diagram, delivery.
