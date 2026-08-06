# ADR-014: Job idempotency, retry, and attempt history

**Status:** Accepted
**Date:** 2026-08-07

## Context

The PostgreSQL queue must survive worker crashes, reject duplicate submissions, bound retries, and
retain evidence from failed or stale attempts. Replacing a failed job row would break resource
references, while overwriting its error fields would remove useful diagnostic history.

## Decision

- Enqueue accepts an optional, globally unique idempotency key of at most 200 characters.
- Reusing a key with the same job type, payload, priority, and retry limit returns the original job
  in its current state. It never creates or requeues work, including when the original succeeded.
- Reusing a key with different request content returns `409 idempotency_conflict`.
- A claim increments `jobs.attempt` and creates one immutable-identity `app.job_attempts` row.
  Attempt outcome, timestamps, worker ID, and error evidence are finalized on that row.
- Explicit retry requeues the same job only from `failed` or `stale`, and only while
  `attempt < max_attempts`. API-created jobs allow one to five attempts.
- Stale recovery requeues the same job when budget remains, otherwise moves it to `failed`.
  Successful and cancelled jobs are never requeued.

## Consequences

Resource tables can keep a stable foreign key to one job while polling exposes every prior attempt.
The queue gains one partial unique index and one small relational history table. Clients must use a
new idempotency key when they intentionally want a distinct job.
