# demo-agentforge

Standalone demo project for AgentForge. It is intended to run only in the target environment as its own compose project, next to the main AgentForge stack.

## Stack

The runtime topology is fixed:

- `web`: `nginx`, listens on `8081`, serves static files and proxies `/api/`
- `api`: tiny Python API, listens on `9001`
- `beads-dolt`: shared Beads Dolt backend, listens on `3306` internally and binds `127.0.0.1:3307` on the host
- `beads-ui`: Beads task UI, installed from `npm` in a local image, listens on `8080` internally and is proxied via `web`
- `db`: Postgres, listens on `5433`
- `redis`: auxiliary Redis instance, listens on `6380`

The API uses Postgres as the source of truth and Redis as a cache/auxiliary runtime service.

The current API exposes:

- `GET /healthz`
- `GET /api/state`
- `POST /api/state`

The frontend uses that API to keep a shared "Server Best" score.

## Fixed Compose Contract

The compose file is intentionally frozen. Future demo work should change application code, not infrastructure shape.

The contract is:

- there is exactly one compose file: `docker-compose.yml`
- service names stay `web`, `api`, `db`, `redis`, `beads-dolt`, and `beads-ui`
- `web` is the only public ingress-facing service
- `api`, `beads-ui`, `db`, and `redis` stay internal-only
- `beads-dolt` binds loopback-only on the host for agent access (`127.0.0.1:3307`)
- `web` keeps the external network alias `demo-agentforge-web`
- `beads-ui` bind-mounts the project checkout so it shares the repository fingerprint with host-side agent checkouts
- `beads-ui` is built from `beads-ui/Dockerfile` and installs `beads-ui` via `npm`
- internal ports stay offset from defaults: `8081`, `9001`, `3306`, `8080`, `5433`, `6380`

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

- `/dev/tasks` -> `beads-ui:8080`
- `/ws` -> `beads-ui:8080` for Beads UI websocket traffic

The main AgentForge stack only needs that one stable upstream.

As long as the demo keeps the alias `demo-agentforge-web` and keeps `web` on `8081`, the AgentForge compose and ingress config do not need to change.

The public demo domain is protected with HTTP basic auth:

- username: `admin`
- password: `robot`

That applies to both the game UI and the Beads UI mounted at `/dev/tasks`.

## Beads Workflow

The demo now ships with a Beads-first task workspace for human approvals and handoffs.

- `beads-dolt` is now the shared Beads backend. It keeps its state in `./.beads-host/dolt` on the host and binds `127.0.0.1:3307` for host-local clients.
- `beads-ui` now runs against the project checkout itself, is installed through `npm`, and keeps the same repo fingerprint as host-side agent checkouts while using the shared backend.
- Run `make beads-init` once per local checkout to attach that checkout to the shared backend and seed the same `beads/PRIME.md` and `mol-change-request` files for local CLI use.
- If you are on another machine, open `ssh -N -L 3307:127.0.0.1:3307 <demo-host>` first, then run `make beads-init`.
- Run `bd prime` at the start of each agent session; this repo overrides the default Beads primer with `beads/PRIME.md`.
- Open the Beads UI at `https://demo.agentforge.redmadrobot.com/dev/tasks` after deploy.
- Start a new workflow with `bd mol pour mol-change-request`.
- The canonical Change Request path is `plan -> plan_approval -> implement -> review -> review_approval -> ci -> merge -> deploy -> acceptance`.
- For code review, `review_approval` is the human gate in Beads: review approval is recorded by humans in Beads and does not require a GitHub PR review approval.
- For ad-hoc work, run `bd ready` before claiming a task. Inside an active Change Request, run `bd mol current`, then `bd update <id> --status in_progress` when a step starts, `bd comments add <id> "..."` for verification and handoff notes, and `bd close <id>` after green verification.
- Because every client writes directly to the same Dolt backend, status changes appear in Beads UI as soon as the `bd` command succeeds. `bd sync` is not required for live UI updates.

## Local Delivery Workflow

This demo follows the same delivery discipline as the main repository, adapted to a smaller runtime:

- use TDD for behavior changes by adding or updating the narrowest automated check before implementation,
- run `make verify-fast` after each small implementation slice,
- run `make verify` before handoff, review, or `review_approval`,
- use `make verify-ci` as the CI-grade alias; it currently mirrors `make verify` until the demo moves into its own repository,
- keep changes small and single-purpose so they can be reviewed in one pass.

## Local Verification Contract

The demo now exposes stable verification entrypoints in its local `Makefile`:

- `make beads-init`: attach the current checkout to the shared Beads backend and seed the demo workflow files,
- `make verify-fast`: quick local contour for small iterations,
- `make verify`: full local contour before review or `review_approval`,
- `make verify-ci`: CI-grade alias with the same blocking semantics,
- `make lint-static`: syntax and required-file checks for the Python API and static assets,
- `make lint-hygiene`: blocks placeholder markers and unfinished notes,
- `make lint-contract`: enforces the fixed runtime contract (service names, stable alias, internal ports, and synchronized version beacons),
- `make test-unit`: runs focused stdlib unit tests for `api/server.py` helpers.

A failing applicable check blocks merge. Review output does not replace green verification.

## Demo Change Control

The sections above are the authoritative architecture contract for the embedded demo while it still lives inside the main AgentForge repository.

- Any change to the fixed compose contract, shared ingress alias, or Change Request sequence must update this `README.md`, `AGENTS.md`, and the seeded Beads formula in the same change set.
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
export BEADS_DOLT_PASSWORD=demo-agentforge-beads
docker compose up --build -d
```

The first start now also builds the local `beads-ui` image, creates `./.beads-host/dolt` for the shared Beads backend, and attaches `beads-ui` to it through the project checkout.
Host-side agents can connect directly with `make beads-init`. Remote agents should use an SSH tunnel to `127.0.0.1:3307` first.

## CI/CD Contract

The repository now ships with GitHub Actions workflow `.github/workflows/cicd.yml`:

- `validate` runs on `pull_request`, `push` to `main`, and `workflow_dispatch`, and executes `make verify-ci`
- `deploy` runs only after successful `validate` and only for non-PR events, then deploys on the demo host
- deployment flow:
  1. `cd /srv/agentforge-demo`
  2. upload current workflow checkout to host via SSH (`tar` stream, excludes `.git`, `.github`, `.beads`, `.beads-host`)
  3. `docker compose up --build -d`

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
