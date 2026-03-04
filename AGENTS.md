# Demo AgentForge Guidelines

## Delivery Discipline

- Use TDD for demo changes: add or update the narrowest automated check before changing behavior.
- Prefer `tests/test_api_server.py` for Python helper logic and extend `scripts/verify.sh` when the change is a static/runtime contract.
- Use task-tracker as the source of truth for delivery work.
- Follow `task-tracker/README.md` for quickstart and runbook commands.
- Run `make verify-fast` from the `demo-agentforge/` checkout after each small implementation slice.
- Run `make verify` before handoff, review, or merge approval.
- Treat a failing applicable verify target as a blocker; review comments are additive, not a substitute for passing checks.
- Keep changes single-purpose. Split mixed product and infrastructure work unless the fixed contract change requires both in one change set.

## Architecture and Change Control

- `README.md` is the authoritative runtime contract for the demo stack. Keep compose, ingress, and task-tracking sections synchronized with real behavior.
- The fixed compose contract is a blocking architecture boundary: service names, internal ports, loopback-only tracker/beads ports, and the `demo-agentforge-web` alias do not change casually.
- Keep `beads-ui` and `beads-dolt` runtime access available, but track active delivery through task-tracker.
- Keep ingress mapping stable: `/dev/tasks` is task-tracker and `/dev/beads` is beads-ui.
- Treat changes to workflow order, approval semantics, ingress shape, or long-lived runtime boundaries as architectural changes, not incidental edits.
- When a demo change affects a long-lived invariant shared with the parent AgentForge repo, sync the rationale back into the parent architecture docs (`docs/ARCHITECTURE.md`, `docs/adr/`, or `docs/agent_decisions.md`) in the same change set.
- Run `make verify-fast` after each small implementation slice. Run `make verify` before handoff or review, then record the result in the active task-tracker task.
- If the next step requires a human, add the blocking question to the active task-tracker item instead of opening a side channel.

## Landing the Plane (Session Completion)

When ending a work session, finish the repo-specific closeout before handing off.

- File or update task-tracker tasks for any remaining follow-up work instead of leaving loose notes.
- Run the applicable quality gate: `make verify-fast` for an incremental slice, `make verify` before handoff or review.
- Hand off with concrete verification status, blockers, and task-tracker references.

## Task Tracking

Use `task-tracker` for all delivery tracking in this repository.

- Keep active work, blockers, approvals, and handoff notes in Task Tracker.
- Use `/dev/tasks` through demo ingress or `http://127.0.0.1:9102/ui?project_key=demo` locally.
- Keep `beads-ui` available under `/dev/beads` for compatibility access only.

Useful local commands:

```bash
make task-tracker-migrate
make task-tracker-health
make task-tracker-snapshot
```
