# Task Tracker MVP Specification

Date: 2026-03-03
Status: Accepted for implementation
Owner: orchestrator thread

## Purpose

Define the fixed domain rules and HTTP API contract for the Task Tracker MVP sidecar.
This specification is normative for tasks `T02` through `T12` in
`docs/task-tracker-implementation-plan.md`.

## Non-Goals

- No workflow editing in UI.
- No external identity provider integration.
- No cross-project task moves.
- No soft-delete or archival model in MVP.

## Terminology

- `project`: a scoped namespace for tasks and workflow configuration.
- `workflow_version`: immutable imported workflow definition pinned to a project.
- `task`: a unit of work tracked by lifecycle status plus overlays.
- `transition_attempt`: a request to move a task from one lifecycle status to another.
- `gate`: policy for transition approval (`auto` or `manual`).
- `pause`: operational overlay state with reason (`blocked` or `awaiting_input`).
- `event`: append-only domain event record used for projections and UI updates.

## Workflow Versioning Rules

1. Each project has exactly one active `workflow_version` at a time.
2. Importing workflow TOML creates a new immutable version row.
3. Existing tasks keep the workflow version they were created with.
4. New tasks use the project active workflow version at create time.
5. Runtime behavior reads only persisted workflow data, never TOML files directly.

## Status Model

Primary lifecycle is fixed and ordered:

`backlog -> ready -> in_progress -> done`

Rules:

1. `ready` does not auto-switch to `in_progress`; only explicit `start_work` performs this change.
2. Lifecycle status and overlay pause states are independent dimensions.
3. Overlay states are `blocked` and `awaiting_input`; they do not replace lifecycle status.
4. At most one open pause exists per task at any time.
5. A task in `done` cannot open a new pause.
6. A task in `done` cannot transition to another lifecycle status.

Allowed lifecycle transitions:

- `backlog -> ready`
- `ready -> in_progress`
- `in_progress -> done`
- `in_progress -> ready`
- `ready -> backlog`

Transitions not listed above return `409 Conflict`.

## Task Invariants

1. `id` is UUIDv7 (string form).
2. `project_key` is immutable after task creation.
3. `workflow_version_id` is immutable after task creation.
4. `parent_task_id` is optional and immutable; parent and child must share `project_key`.
5. `title` is required, 1..200 UTF-8 characters.
6. `description` is optional, up to 10_000 UTF-8 characters.
7. `priority` is integer `0..100` (higher means more urgent).
8. `assignee` is optional string `1..120` characters.
9. `updated_at` must change on every state mutation.

## Gate Approval Semantics

1. Every lifecycle transition request creates a `transition_attempt` record.
2. `gate_type=auto` immediately resolves the attempt as `approved` and applies transition in one transaction.
3. `gate_type=manual` sets attempt to `pending` until a human action.
4. Approval endpoint applies transition only when attempt is still `pending`.
5. Reject endpoint requires non-empty comment (`reject-with-comment` policy).
6. Rejected attempts do not change task lifecycle status.
7. An attempt can be resolved exactly once.
8. Attempt resolution emits a domain event.
9. At most one `pending` transition attempt may exist per task at a time.
10. Approve/reject must fail if task lifecycle no longer matches attempt `from_status`.

## Pause Semantics

`blocked` pause:

- requires `reason` (1..500 chars).
- may include optional `details` (up to 5_000 chars).

`awaiting_input` pause:

- requires `question` (1..1_000 chars).
- optional `requested_from` (1..120 chars).
- optional `due_at` (RFC3339 timestamp).

Resume rules:

1. Resume closes the active pause and returns task to prior operational state.
2. `awaiting_input` can be resumed only after at least one answer exists.
3. Answer append does not auto-resume.
4. Closing a task to `done` auto-closes any open pause in the same transaction.

## Event Log Contract

1. Events are append-only.
2. Global cursor is strictly increasing 64-bit integer.
3. Each state-changing operation emits at least one event.
4. Event payload is JSON object with stable keys:
   - `cursor` (int)
   - `event_type` (string)
   - `project_key` (string)
   - `task_id` (string or null)
   - `occurred_at` (RFC3339)
   - `payload` (object)

## API Contract

Base path: `/api/v1`

Transport:

- JSON request/response (`application/json`).
- Timestamps use RFC3339 UTC (`Z`) format.
- Unknown JSON fields are ignored.
- All mutating endpoints are transactionally atomic.

Error model for non-2xx responses:

```json
{
  "error": {
    "code": "string",
    "message": "human-readable",
    "details": {}
  }
}
```

### Health

- `GET /healthz`
  - `200 OK`: `{"status":"ok"}` when API and DB dependencies are reachable.
  - `503 Service Unavailable`: unhealthy.

### Workflow Import and Read

- `POST /api/v1/projects/{project_key}/workflow/import`
  - Body: `{ "toml": "<string>", "version_label": "optional-string" }`
  - `201 Created`: `{ "workflow_version_id": "uuid", "project_key": "...", "version": 3 }`
  - `400 Bad Request`: parse/validation failure.

- `GET /api/v1/projects/{project_key}/workflow`
  - `200 OK`: active workflow metadata and normalized state machine definition.

### Task CRUD and Work Actions

- `POST /api/v1/tasks`
  - Body: `{ "project_key": "...", "title": "...", "description": "...", "priority": 50, "parent_task_id": "uuid|null" }`
  - `201 Created`: full task object.

- `GET /api/v1/tasks/{task_id}`
  - `200 OK`: full task object with lifecycle status, pause state, and latest transition attempt summary.
  - `404 Not Found`: unknown task.

- `PATCH /api/v1/tasks/{task_id}`
  - Body: subset of `{ "title", "description", "priority", "assignee" }`.
  - `200 OK`: updated task.

- `POST /api/v1/tasks/{task_id}/children`
  - Body: same shape as `POST /api/v1/tasks` excluding `project_key` and `parent_task_id`.
  - `201 Created`: created child task.

- `POST /api/v1/tasks/{task_id}/actions/claim`
  - Body: `{ "assignee": "agent-or-user-id" }`
  - `200 OK`: updated task with assignee.

- `POST /api/v1/tasks/{task_id}/actions/start_work`
  - Effect: transition attempt for `ready -> in_progress`.
  - `200 OK`: transition approved and applied.
  - `202 Accepted`: transition pending manual approval.
  - `409 Conflict`: task not currently `ready`.

- `POST /api/v1/tasks/{task_id}/actions/report_result`
  - Body: `{ "summary": "...", "artifacts": [{"name":"...","url":"..."}] }`
  - `200 OK`: result attached to task.

### Transition Engine

- `POST /api/v1/tasks/{task_id}/transitions`
  - Body: `{ "target_status": "backlog|ready|in_progress|done", "reason": "optional-string" }`
  - `200 OK`: attempt auto-approved and transition applied.
  - `202 Accepted`: attempt pending manual gate.
  - `409 Conflict`: invalid transition from current status or existing pending attempt.

- `GET /api/v1/transitions/{attempt_id}`
  - `200 OK`: transition attempt object with `status` in `pending|approved|rejected`.

- `POST /api/v1/transitions/{attempt_id}/approve`
  - Body: `{ "actor": "user-id", "comment": "optional" }`
  - `200 OK`: approved attempt and task status updated.
  - `409 Conflict`: attempt already resolved or stale attempt source status.

- `POST /api/v1/transitions/{attempt_id}/reject`
  - Body: `{ "actor": "user-id", "comment": "required" }`
  - `200 OK`: rejected attempt.
  - `400 Bad Request`: empty comment.
  - `409 Conflict`: attempt already resolved or stale attempt source status.

### Pause and Input Flow

- `POST /api/v1/tasks/{task_id}/pauses/blocked`
  - Body: `{ "reason": "...", "details": "optional" }`
  - `201 Created`: pause object.
  - `409 Conflict`: another pause already open.

- `POST /api/v1/tasks/{task_id}/pauses/awaiting_input`
  - Body: `{ "question": "...", "requested_from": "optional", "due_at": "optional-rfc3339" }`
  - `201 Created`: pause object.
  - `409 Conflict`: another pause already open.

- `POST /api/v1/pauses/{pause_id}/answers`
  - Body: `{ "actor": "user-id", "answer": "..." }`
  - `201 Created`: answer record.

- `POST /api/v1/pauses/{pause_id}/resume`
  - Body: `{ "actor": "user-id", "comment": "optional" }`
  - `200 OK`: pause closed.
  - `409 Conflict`: awaiting input has no answers yet.

### Queue Projection

- `GET /api/v1/queues/attention?project_key=<key>`
  - `200 OK`: grouped buckets and counts.
  - Buckets are fixed:
    - `pending_approval`
    - `awaiting_input`
    - `blocked`
    - `ready_unclaimed`
    - `in_progress`
    - `done_recent`

Task summary payload for queues contains:

- `task_id`
- `title`
- `status`
- `pause_type` (`null|blocked|awaiting_input`)
- `priority_score` (numeric projection value)
- `updated_at`
- `closable` (boolean)

### Long Polling UI

- `GET /api/v1/ui/snapshot?project_key=<key>`
  - `200 OK`: `{ "cursor": <int>, "queues": {...}, "tasks": [...], "pending_transitions": [...], "open_pauses": [...] }`

- `GET /api/v1/ui/updates?cursor=<cursor>&timeout=<seconds>`
  - `timeout` range: `1..30`; default `20`.
  - If newer events exist, returns immediately with `200 OK` and `{ "cursor": <int>, "events": [...] }`.
  - If no events before timeout, returns `200 OK` with empty `events` and unchanged cursor.

### AgentForge Bridge (`v1`)

Bridge base path: `/api/agentforge`

Authentication:

- only HTTP Basic auth is allowed,
- every `/api/agentforge/*` request without valid Basic credentials is rejected.

Configuration endpoint:

- `GET /api/agentforge/config`
  - `200 OK`: returns `protocol_version`, `auth_type`, `base_url`,
    `project_id`, `connector_id`, relative `paths`, and
    `agentforge_variables` for quick connector setup.

Ready queue endpoint:

- `GET /api/agentforge/ready-candidates?limit=<n>&project_id=<id>&connector_id=<id>`
  - required query params: `limit`, `project_id`, `connector_id`
  - strict sort: highest project task priority first (`priority DESC`)
  - `200 OK`: `{ "candidates": [...] }`
  - `204 No Content`: no ready candidates

Planned endpoint:

- `POST /api/agentforge/ready-candidates/{external_id}/planned`
  - required header: `Idempotency-Key`
  - idempotent by key (same key + same request => same logical result)
  - successful plan moves candidate out of `ready` (until explicit requeue)
  - success statuses: `200|201|204`; duplicate conflict may be `409`

Done endpoint:

- `POST /api/agentforge/ready-candidates/{external_id}/done`
  - required header: `Idempotency-Key`
  - body `status` must be one of: `completed|failed|cancelled`
  - stores `attempts_used`, `max_attempts`, `summary`, `error_code`, `done_at`
  - idempotent by key with the same rules as `planned`
  - success statuses: `200|201|204`; duplicate conflict may be `409`

## Concurrency and Transaction Rules

1. All mutating endpoints run in a DB transaction.
2. Task lifecycle transitions lock task row (`SELECT ... FOR UPDATE`).
3. Pause open/resume operations lock task row.
4. Transition approve/reject locks transition attempt row.
5. Queue projections are read-only and may use repeatable-read snapshots.

## Required Domain Events

At minimum, these `event_type` values must be emitted:

- `workflow.imported`
- `task.created`
- `task.updated`
- `task.claimed`
- `task.result_reported`
- `transition.requested`
- `transition.approved`
- `transition.rejected`
- `pause.opened`
- `pause.answered`
- `pause.resumed`
- `task.completed`

## Acceptance Criteria for This Spec

1. Domain rules in this file are sufficient to implement tasks `T02`-`T12` without redefining status or API semantics.
2. No unresolved placeholders or open questions remain in this file.
3. Any future contract change requires explicit update to this file in the same change set.
