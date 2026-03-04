# demo-agentforge

Standalone demo project for AgentForge. It runs as an independent compose project and does not require the main AgentForge stack on the same host.

## Stack

The runtime topology is fixed:

- `web`: `nginx`, listens on `8081`, binds `8081` on the host, serves static files, proxies `/api/`, and protects public access with HTTP basic auth
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

## AgentForge Protocol v1 Bridge

Task Tracker exposes AgentForge protocol `v1` routes under `/api/agentforge`:

- `GET /api/agentforge/config`
- `GET /api/agentforge/ready-candidates`
- `POST /api/agentforge/ready-candidates/{external_id}/planned`
- `POST /api/agentforge/ready-candidates/{external_id}/done`

All `/api/agentforge/*` endpoints require HTTP Basic auth.

### Как подключить AgentForge через `/api/agentforge/config`

1. Выполните `GET /api/agentforge/config` через demo ingress с Basic auth:
   `curl -sS -u admin:robot https://<demo-host>/dev/tasks/api/agentforge/config`
2. Возьмите из ответа `base_url`, `project_id`, `connector_id`, `paths`, `agentforge_variables`.
3. Настройте AgentForge connector на `protocol_version=v1`, `auth_type=basic`,
   и используйте относительные пути из `paths`.

## Fixed Compose Contract

The compose file is intentionally frozen. Future demo work should change application code, not infrastructure shape.

The contract is:

- there is exactly one compose file: `docker-compose.yml`
- service names stay `web`, `api`, `db`, `redis`, `beads-dolt`, `beads-ui`, `task-tracker-db`, and `task-tracker`
- `web` is the only public ingress-facing service and binds `8081:8081` on the host
- `api`, `beads-ui`, `db`, `redis`, `task-tracker-db`, and `task-tracker` stay internal-only behind `web`
- `beads-dolt` binds loopback-only on the host for agent access (`127.0.0.1:3307`)
- `task-tracker-db` binds loopback-only on the host for local SQL access (`127.0.0.1:55432`)
- `task-tracker` binds loopback-only on the host for local health/API access (`127.0.0.1:9102`)
- `web` keeps HTTP basic auth enabled in `nginx/default.conf` with credentials from `nginx/demo-auth.htpasswd`
- `beads-ui` bind-mounts the project checkout so it shares the repository fingerprint with host-side agent checkouts
- `beads-ui` is built from `beads-ui/Dockerfile` and installs `beads-ui` via `npm`
- internal ports stay offset from defaults: `8081`, `9001`, `3306`, `8080`, `5433`, `6380`, `5432`, `9102`

This keeps the demo runtime self-sufficient and predictable across hosts.

## Frontend Files

The frontend layout is fixed:

- `site/index.html` is the HTML entrypoint
- `site/version.json` is the version beacon used by already-open tabs
- `site/assets/` contains JS, CSS, images, fonts, and future build output

New frontend assets should be added under `site/assets/` so the `web` config does not need structural changes.

## Standalone Host Deployment

The demo now runs as one independent compose project on its host:

- no shared Docker network is required,
- no upstream AgentForge ingress is required,
- `web` is directly published on host port `8081`,
- all public routes remain served by the local `web` container.

Inside the demo stack, `web` routes:

- `/dev/tasks` -> `task-tracker:9102`
- `/dev/beads` -> `beads-ui:8080`
- `/dev/beads/ws` -> `beads-ui:8080/ws` for Beads UI websocket traffic

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
- `make lint-contract`: enforces the fixed runtime contract (service names, standalone ingress/auth, internal ports, and synchronized version beacons),
- `make test-unit`: runs focused stdlib unit tests for `api/server.py` helpers.

A failing applicable check blocks merge. Review output does not replace green verification.

## Demo Change Control

The sections above are the authoritative architecture contract for the embedded demo while it still lives inside the main AgentForge repository.

- Any change to the fixed compose contract, standalone ingress/auth contract, or task-tracking workflow contract must update this `README.md`, `AGENTS.md`, and the relevant `task-tracker` docs in the same change set.
- Changes that revise a long-lived boundary or invariant should also update the parent repository architecture records (`docs/ARCHITECTURE.md`, `docs/adr/`, or `docs/agent_decisions.md`) before merge.
- Deferred follow-up work is not an acceptable substitute for a failed blocking verification step.

## Deploy

Deploy the demo independently:

```bash
cd demo-agentforge
docker compose up --build -d
docker compose run --rm task-tracker python /app/migrate.py
docker compose up -d --no-deps --force-recreate task-tracker web
```

The first start builds local `beads-ui` and `task-tracker` images, creates `./.beads-host/dolt` for the shared Beads backend, and initializes task-tracker schema via `python /app/migrate.py` in the `task-tracker` container.
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

The deployment pipeline is self-contained and may safely run:

```bash
docker compose up --build -d
docker compose run --rm task-tracker python /app/migrate.py
docker compose up -d --no-deps --force-recreate task-tracker web
```

The target host only needs Docker/Compose and network access to pull images/build.
If public internet access is required, expose host port `8081` (or put any external reverse proxy/LB in front of `:8081`).

## Version Updates

- The running page polls `/version.json` every 30 seconds.
- `version.json` is served with a short HTTP cache TTL.
- If the version changes, already-open tabs show a refresh banner.

To publish a new frontend revision:

1. Update `data-app-version` in `site/index.html`.
2. Update `version` in `site/version.json`.
3. Redeploy the demo stack.

Because the `web` container serves the checked-out `site/` directory, frontend asset changes do not require changing the compose file.
