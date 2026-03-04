# demo-agentforge

Standalone demo project for AgentForge. It is intended to run only in the target environment as its own compose project, next to the main AgentForge stack.

## Stack

The runtime topology is fixed:

- `web`: `nginx`, listens on `8081`, serves static files and proxies `/api/`
- `api`: tiny Python API, listens on `9001`
- `beads-dolt`: shared Beads Dolt backend kept for compatibility access, listens on `3306` internally and binds `127.0.0.1:3307` on the host
- `beads-ui`: Beads UI kept for compatibility access, installed from `npm` in a local image, listens on `8080` internally and is proxied via `web`
- `db`: Postgres, listens on `5433`
- `redis`: auxiliary Redis instance, listens on `6380`
- `task-tracker-db`: Postgres for task-tracker, listens on `5432` internally and binds `127.0.0.1:55432` on the host
- `task-tracker`: Task Tracker sidecar API/UI, listens on `9102` internally and binds `127.0.0.1:9102` on the host

The API uses Postgres as the source of truth and Redis as a cache/auxiliary runtime service.

The current API exposes:

- `GET /healthz`
- `GET /api/state`
- `POST /api/state`

The frontend uses that API to keep a shared "Server Best" score.

## Task Tracking Workflow

Delivery tracking for this project uses `task-tracker` from `task-tracker/`.

- source of truth for active work is Task Tracker (`/ui` and `/api/v1/*`),
- default local UI: [http://127.0.0.1:9102/ui?project_key=demo](http://127.0.0.1:9102/ui?project_key=demo),
- quickstart and runbook live in `task-tracker/README.md`,
- external demo route `/dev/tasks` points to Task Tracker UI/API through `web`,
- `beads-ui` and `beads-dolt` remain available for compatibility access only and are exposed via `/dev/beads`.

## Fixed Compose Contract

The compose file is intentionally frozen. Future demo work should change application code, not infrastructure shape.

The contract is:

- there is exactly one compose file: `docker-compose.yml`
- service names stay `web`, `api`, `db`, `redis`, `beads-dolt`, `beads-ui`, `task-tracker-db`, and `task-tracker`
- `web` is the only public ingress-facing service
- `api`, `beads-ui`, `db`, `redis`, `task-tracker-db`, and `task-tracker` stay internal-only from ingress
- `beads-dolt` binds loopback-only on the host for agent access (`127.0.0.1:3307`)
- `task-tracker-db` binds loopback-only on the host for local SQL access (`127.0.0.1:55432`)
- `task-tracker` binds loopback-only on the host for local health/API access (`127.0.0.1:9102`)
- `web` keeps the external network alias `demo-agentforge-web`
- `beads-ui` bind-mounts the project checkout so it shares the repository fingerprint with host-side agent checkouts
- `beads-ui` is built from `beads-ui/Dockerfile` and installs `beads-ui` via `npm`
- internal ports stay offset from defaults: `8081`, `9001`, `3306`, `8080`, `5433`, `6380`, `5432`, `9102`

This is what keeps the main AgentForge compose unchanged while the demo evolves.

## Frontend Files

The frontend layout is fixed:

- `site/index.html` is the HTML entrypoint
- `site/version.json` is the version beacon used by already-open tabs
- `site/assets/` contains JS, CSS, images, fonts, and future build output

New frontend assets should be added under `site/assets/` so the `web` config does not need structural changes.

## Shared Host Deployment

AgentForge and the demo run as two separate compose projects:

- AgentForge owns the public ingress and the `agentforge.redmadrobot.com` domain
- the demo owns its own runtime
- both projects join the shared external Docker network `agentforge-edge`

The main AgentForge ingress routes:

- `agentforge.redmadrobot.com` -> AgentForge API
- `demo.agentforge.redmadrobot.com` -> `demo-agentforge-web:8081`

Inside the demo stack, `web` additionally routes:

- `/dev/tasks` -> `task-tracker:9102`
- `/dev/beads` -> `beads-ui:8080`
- `/dev/beads/ws` -> `beads-ui:8080/ws` for Beads UI websocket traffic

The main AgentForge stack only needs that one stable upstream.

As long as the demo keeps the alias `demo-agentforge-web` and keeps `web` on `8081`, the AgentForge compose and ingress config do not need to change.

The public demo domain is protected with HTTP basic auth:

- username: `admin`
- password: `robot`

That applies to the game UI, Task Tracker UI mounted at `/dev/tasks`, and Beads UI mounted at `/dev/beads`.

## Local Delivery Workflow

This demo follows the same delivery discipline as the main repository, adapted to a smaller runtime:

- use TDD for behavior changes by adding or updating the narrowest automated check before implementation,
- run `make verify-fast` after each small implementation slice,
- run `make verify` before handoff or review,
- use `make verify-ci` as the CI-grade alias; it currently mirrors `make verify` until the demo moves into its own repository,
- keep task lifecycle, approvals, and blockers in Task Tracker (`task-tracker/README.md`),
- keep changes small and single-purpose so they can be reviewed in one pass.

## Local Verification Contract

The demo now exposes stable verification entrypoints in its local `Makefile`:

- `make task-tracker-migrate`: apply task-tracker migrations through the main `task-tracker` container,
- `make task-tracker-health`: check local task-tracker health endpoint,
- `make task-tracker-snapshot`: inspect current Task Tracker queues for `TASK_TRACKER_PROJECT_KEY` (defaults to `demo`),
- `make verify-fast`: quick local contour for small iterations,
- `make verify`: full local contour before review or handoff,
- `make verify-ci`: CI-grade alias with the same blocking semantics,
- `make lint-static`: syntax and required-file checks for the Python API and static assets,
- `make lint-hygiene`: blocks placeholder markers and unfinished notes,
- `make lint-contract`: enforces the fixed runtime contract (service names, stable alias, internal ports, and synchronized version beacons),
- `make test-unit`: runs focused stdlib unit tests for `api/server.py` helpers.

A failing applicable check blocks merge. Review output does not replace green verification.

## Demo Change Control

The sections above are the authoritative architecture contract for the embedded demo while it still lives inside the main AgentForge repository.

- Any change to the fixed compose contract, shared ingress alias, or task-tracking workflow contract must update this `README.md`, `AGENTS.md`, and the relevant `task-tracker` docs in the same change set.
- Changes that revise a long-lived boundary or invariant should also update the parent repository architecture records (`docs/ARCHITECTURE.md`, `docs/adr/`, or `docs/agent_decisions.md`) before merge.
- Deferred follow-up work is not an acceptable substitute for a failed blocking verification step.

## Deploy

Create the shared network once:

```bash
docker network create agentforge-edge
```

Then deploy the demo independently:

```bash
cd demo-agentforge
docker compose up --build -d
docker compose run --rm task-tracker python /app/migrate.py
docker compose up -d --no-deps --force-recreate task-tracker web
```

The first start now also builds the local `beads-ui` and `task-tracker` images, creates `./.beads-host/dolt` for the shared Beads backend, and initializes task-tracker schema via `python /app/migrate.py` in the `task-tracker` container.
Task Tracker setup and operations are documented in `task-tracker/README.md`.
Remote access to the Beads backend still uses an SSH tunnel to `127.0.0.1:3307`.

## CI/CD Contract

The repository now ships with GitHub Actions workflow `.github/workflows/cicd.yml`:

- `validate` runs on `pull_request`, `push` to `main`, and `workflow_dispatch`, and executes `make verify-ci`
- `deploy` runs only after successful `validate` and only for non-PR events, then deploys on the demo host
- deployment flow:
  1. `cd /srv/agentforge-demo`
  2. upload current workflow checkout to host via SSH (`tar` stream, excludes `.git`, `.github`, `.beads`, `.beads-host`)
  3. `docker compose up --build -d`
  4. `docker compose run --rm task-tracker python /app/migrate.py`
  5. `docker compose up -d --no-deps --force-recreate task-tracker web`

Required repository secrets for deployment:

- `DEMO_DEPLOY_HOST`
- `DEMO_DEPLOY_USER`
- `DEMO_DEPLOY_SSH_KEY` (private key for host access)
- `DEMO_DEPLOY_KNOWN_HOSTS` (output of `ssh-keyscan -H <host>`)

Optional:

- `DEMO_DEPLOY_PORT` (defaults to `22`)

When this demo is moved into its own public repository, its CI/CD can deploy it without knowing internal AgentForge details.

The only shared infrastructure contract is:

- the host already has a Docker network named `agentforge-edge`
- the main ingress already proxies the demo domain to `demo-agentforge-web:8081`

That means demo CI/CD may safely run:

```bash
docker compose up --build -d
docker compose run --rm task-tracker python /app/migrate.py
docker compose up -d --no-deps --force-recreate task-tracker web
```

The demo pipeline does not need to know:

- how AgentForge is built
- which services AgentForge runs
- what database AgentForge uses
- which internal ports AgentForge uses

It only needs to preserve the fixed compose contract above.

## Version Updates

- The running page polls `/version.json` every 30 seconds.
- `version.json` is served with a short HTTP cache TTL.
- If the version changes, already-open tabs show a refresh banner.

To publish a new frontend revision:

1. Update `data-app-version` in `site/index.html`.
2. Update `version` in `site/version.json`.
3. Redeploy the demo stack.

Because the `web` container serves the checked-out `site/` directory, frontend asset changes do not require changing the compose file.
