# Task Tracker MVP: Implementation Plan

Date: 2026-03-03
Owner: orchestrator thread
Execution model: one task per agent, strictly sequential

## Scope

Build a reusable sidecar task tracker service with:
- project-bound versioned workflow definitions from files,
- task lifecycle `backlog -> ready -> in_progress -> done`,
- gate approval on transition attempts (`approve` or `reject with comment`),
- overlays `blocked` and `awaiting_input`,
- long polling UI for operational control only (no workflow editing).

## Task Breakdown

| ID | Task | Deliverable | Dependencies | Done Criteria | Readiness |
|---|---|---|---|---|---|
| T01 | Write MVP spec | `docs/task-tracker-spec.md` | — | Domain rules and API contracts fixed; no open ambiguities | ✅ Verified |
| T02 | Scaffold sidecar service | `task-tracker/` skeleton + Dockerfile + health endpoint | T01 | Service starts in container and responds on `/healthz` | ✅ Verified |
| T03 | Add PostgreSQL schema + migrations | SQL migration files and migration runner | T01, T02 | All core tables/constraints/indexes created successfully | ✅ Verified |
| T04 | Implement config import from TOML | parser + validation + DB import for project/workflow/types | T03 | Import works idempotently; pinned workflow version available | ✅ Verified |
| T05 | Implement task runtime API | endpoints for task CRUD, child attach, claim, start_work, results | T03, T04 | Endpoints pass unit/integration tests | ✅ Verified |
| T06 | Implement transition & gate engine | transition attempts + auto/manual approve/reject | T03, T04, T05 | Transition rules enforced with DB transaction safety | ✅ Verified |
| T07 | Implement pauses | blocked + awaiting_input + question/answer flow | T05 | One open pause per task enforced; resume behavior correct | ✅ Verified |
| T08 | Implement queue projection | attention buckets + priority score + closability checks | T05, T06, T07 | UI/API can fetch grouped work queues | ✅ Verified |
| T09 | Implement long polling API | `/ui/snapshot` and `/ui/updates?cursor=&timeout=` | T08 | Delta updates from event cursor work reliably | ✅ Verified |
| T10 | Build operational UI | board + details panel + actions for human operations | T09 | Human can operate approvals/questions/blocked flow end-to-end | — |
| T11 | Harden concurrency and tests | lock strategy, race tests, contract tests | T05, T06, T07, T08, T09 | Concurrent operations deterministic and tested | ✅ Verified |
| T12 | Package and document sidecar usage | compose snippet + runbook + quickstart | T10, T11 | Service can be launched near any project with minimal setup | ✅ Verified |

## Sequential Orchestration Contract

1. Only one implementation task is active at a time.
2. Each task is executed by a fresh agent via `codex exec`.
3. The orchestrator verifies task outputs before starting the next task.
4. If task verification fails, the same task is retried or fixed before continuing.
5. No task may change scope outside its own ID.

## Required Technical Rules per Task

- Use TDD: tests first for behavior changes.
- Use DB transactions for all state-changing operations.
- Use row locking (`SELECT ... FOR UPDATE`) where required.
- Keep event log append-only and emit domain events for every meaningful change.
- Do not implement workflow editing UI.
- Keep code modular so the service can run as a standalone sidecar.

## Acceptance Gate per Task

Each task is accepted only when all checks pass:
- unit tests for changed domain,
- integration tests for changed API paths,
- concurrency test coverage for critical transitions,
- lint/static checks,
- short handoff note in commit message or task note.

## Final MVP Acceptance

The MVP is done when:
1. A human can manage queues in UI and resolve pending approvals/questions.
2. Agents can claim and explicitly start work (`ready` does not auto-become `in_progress`).
3. Transition gates support approve and reject-with-comment.
4. Awaiting human input flow resumes same work after answers.
5. Sidecar deployment runs independently with Postgres and file-based workflow definitions.
