# Task Tracker Sidecar (T02 Scaffold)

This directory contains the Task Tracker MVP sidecar implementation slices.

Current delivered slices include:

- a container image definition (`Dockerfile`),
- a service entrypoint (`server.py`),
- schema migrations (`migrations/`),
- workflow import support (`workflow_import.py`),
- task runtime endpoints (`/api/v1/tasks`),
- transition and gate engine endpoints (T06),
- pause flow endpoints for `blocked` and `awaiting_input` (T07),
- queue projection endpoint for operational attention buckets (T08),
- long polling UI API with snapshot + cursor updates (T09),
- operational UI page with board/details/actions for human control flows (T10).
- concurrency hardening for transition and approval flows (T11).

Run locally:

```bash
python3 task-tracker/server.py
```

Health check:

- `GET /healthz`

```bash
curl -sS http://127.0.0.1:9102/healthz
```

Expected response:

```json
{"status":"ok"}
```

## T06: Transition & Gate Engine

Lifecycle transitions are routed through transition attempts and gate policy:

- `POST /api/v1/tasks/{task_id}/transitions`
- `GET /api/v1/transitions/{attempt_id}`
- `POST /api/v1/transitions/{attempt_id}/approve`
- `POST /api/v1/transitions/{attempt_id}/reject`

`POST /api/v1/tasks/{task_id}/actions/start_work` now uses the same transition
engine (`ready -> in_progress`) and can return:

- `200 OK` for auto-approved gates,
- `202 Accepted` for manual pending gates,
- `409 Conflict` for invalid status transitions.

## T07: Pauses (`blocked` and `awaiting_input`)

Pause endpoints:

- `POST /api/v1/tasks/{task_id}/pauses/blocked`
- `POST /api/v1/tasks/{task_id}/pauses/awaiting_input`
- `POST /api/v1/pauses/{pause_id}/answers`
- `POST /api/v1/pauses/{pause_id}/resume`

Delivered pause behavior:

- at most one open pause per task,
- no new pause can be opened when task status is `done`,
- `awaiting_input` pauses require at least one answer before resume,
- appending answers does not auto-resume,
- completing a task to `done` auto-closes any open pause in the same operation.

## T08: Queue projection (`/api/v1/queues/attention`)

Queue endpoint:

- `GET /api/v1/queues/attention?project_key=<key>`

Delivered queue behavior:

- fixed buckets: `pending_approval`, `awaiting_input`, `blocked`, `ready_unclaimed`, `in_progress`, `done_recent`,
- each bucket returns task summaries with `priority_score` and `closable`,
- task summaries include `task_id`, `title`, `status`, `pause_type`, and `updated_at`.

## T09: Long polling UI API

UI endpoints:

- `GET /api/v1/ui/snapshot?project_key=<key>`
- `GET /api/v1/ui/updates?cursor=<cursor>&timeout=<seconds>`

Delivered behavior:

- snapshot returns `cursor`, queue projection, project tasks, pending transitions, and open pauses,
- updates returns append-only events after the provided cursor,
- `timeout` defaults to `20` seconds and is validated in range `1..30`,
- if no new events appear before timeout, updates returns empty `events` with unchanged cursor.

## T10: Operational UI

Operational page endpoint:

- `GET /ui?project_key=<key>`

Delivered behavior:

- renders queue board buckets from snapshot projection,
- renders task details panel with live context for selected task,
- allows manual task creation from a dedicated form (title required, description/priority optional),
- allows human approve/reject for pending transition attempts,
- allows open/answer/resume for `blocked` and `awaiting_input` pause flows,
- subscribes to event deltas via long polling updates endpoint and refreshes snapshot on change.

## T11: Concurrency Hardening and Contracts

Delivered behavior:

- transition requests reject with `409 pending_transition_exists` when the task already has a pending manual gate attempt,
- approve/reject now reject with `409 stale_transition` when task lifecycle no longer matches attempt `from_status`,
- schema enforces one pending transition attempt per task via a partial unique index,
- runtime and HTTP contract tests cover duplicate-request conflict and stale approval handling.

## T12: Sidecar Packaging and Usage

The sidecar can run next to any project as a dedicated `task-tracker` + Postgres pair.
Keep these services in your local compose override and point your project tooling to
`http://127.0.0.1:9102`.

### Compose snippet

```yaml
services:
  task-tracker-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: task_tracker
      POSTGRES_USER: task_tracker
      POSTGRES_PASSWORD: task_tracker
    ports:
      - "127.0.0.1:55432:5432"
    volumes:
      - task-tracker-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U task_tracker -d task_tracker"]
      interval: 5s
      timeout: 3s
      retries: 20

  task-tracker:
    build:
      context: ./task-tracker
    depends_on:
      task-tracker-db:
        condition: service_healthy
    environment:
      TASK_TRACKER_HOST: 0.0.0.0
      TASK_TRACKER_PORT: "9102"
      TASK_TRACKER_DATABASE_URL: postgresql://task_tracker:task_tracker@task-tracker-db:5432/task_tracker
      TASK_TRACKER_DB_DSN: host=task-tracker-db port=5432 dbname=task_tracker user=task_tracker password=task_tracker
    ports:
      - "127.0.0.1:9102:9102"
    restart: unless-stopped

volumes:
  task-tracker-db-data:
```

For host-local CLI tools, use:
`TASK_TRACKER_DATABASE_URL=postgresql://task_tracker:task_tracker@127.0.0.1:55432/task_tracker`

### Quickstart

1. Start only the sidecar database:

   ```bash
   docker compose up -d task-tracker-db
   ```

2. Apply schema migrations:

   ```bash
   docker compose run --rm task-tracker python /app/migrate.py
   ```

3. Start API sidecar:

   ```bash
   docker compose up -d task-tracker
   ```

4. Verify health:

   ```bash
   curl -sS http://127.0.0.1:9102/healthz
   ```

5. Open operational UI:

   - [http://127.0.0.1:9102/ui](http://127.0.0.1:9102/ui)

### Runbook

- Check service health:

  ```bash
  curl -sS http://127.0.0.1:9102/healthz
  ```

- Check project snapshot (queues + pending transitions + open pauses):

  ```bash
  curl -sS "http://127.0.0.1:9102/api/v1/ui/snapshot?project_key=demo"
  ```

- Inspect DB state directly:

  ```bash
  psql "postgresql://task_tracker:task_tracker@127.0.0.1:55432/task_tracker"
  ```

- Re-run migrations after updating SQL files:

  ```bash
  docker compose run --rm task-tracker python /app/migrate.py
  ```

- Restart sidecar after deploy:

  ```bash
  docker compose up -d --no-deps --force-recreate task-tracker
  ```

## T03: PostgreSQL migrations

The schema baseline for the Task Tracker sidecar is now versioned in
`task-tracker/migrations/`.

Run migrations against PostgreSQL:

```bash
python3 task-tracker/migrate.py --dsn "host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres"
```

Or set environment variables:

```bash
export TASK_TRACKER_DB_DSN="host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres"
python3 task-tracker/migrate.py
```
