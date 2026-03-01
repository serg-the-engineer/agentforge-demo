# Demo AgentForge Guidelines

## Delivery Discipline

- Use TDD for demo changes: add or update the narrowest automated check before changing behavior.
- Prefer `tests/test_api_server.py` for Python helper logic and extend `scripts/verify.sh` when the change is a static/runtime contract.
- Run `make verify-fast` from the `demo-agentforge/` checkout after each small implementation slice.
- Run `make verify` before handoff, review, or merge approval.
- Treat a failing applicable verify target as a blocker; review comments are additive, not a substitute for passing checks.
- Keep changes single-purpose. Split mixed product and infrastructure work unless the fixed contract change requires both in one change set.

## Primary Human Workflow

- Use Beads as the default human-facing task tracker for all demo changes.
- Open the task board in the deployed demo at `/dev/tasks` on the demo domain.
- Start new work from the `mol-change-request` formula instead of creating ad-hoc tasks.
- Keep approvals, questions, review findings, CI status, and acceptance notes inside the same Change Request thread.

## Change Request Flow

- The demo workspace ships the `mol-change-request` formula versioned in `beads/formulas/`.
- Create a new Change Request with `bd mol pour mol-change-request`.
- Follow the canonical path: `plan -> plan_approval -> implement -> review -> ci -> merge_approval -> merge -> deploy -> acceptance`.
- Do not bypass `plan_approval`, `merge_approval`, or `acceptance`.
- If the sequence or gate semantics change, update this file, `README.md`, and the seeded formula in the same change set.

## Architecture and Change Control

- `README.md` is the authoritative runtime contract for the demo stack. Keep compose, ingress, and workflow sections synchronized with real behavior.
- The fixed compose contract is a blocking architecture boundary: service names, internal ports, the loopback-only Beads backend port, and the `demo-agentforge-web` alias do not change casually.
- Treat changes to workflow order, approval semantics, ingress shape, or long-lived runtime boundaries as architectural changes, not incidental edits.
- When a demo change affects a long-lived invariant shared with the parent AgentForge repo, sync the rationale back into the parent architecture docs (`docs/ARCHITECTURE.md`, `docs/adr/`, or `docs/agent_decisions.md`) in the same change set.

## Agent Expectations

- Start each session by making sure `make beads-init` has already been run for this checkout, then run `bd prime`. After that, use `bd mol current` or `bd ready` to confirm the active unblocked step before you claim work.
- If you are not on the demo host, open an SSH tunnel to the host-local Beads backend first: `ssh -N -L 3307:127.0.0.1:3307 <demo-host>`, then run `make beads-init`.
- Agents should publish handoff summaries, verification results, questions, and links back into the active Change Request.
- Run `make verify-fast` after each small implementation slice. Run `make verify` before handoff, review, or merge approval, then post the result in the active Change Request with `bd comments add <id> ...`.
- If the next step requires a human, record the blocking questions in the current gate instead of opening a side channel.
- When new follow-up work is discovered, create a separate Beads task with `bd create` and connect blockers with `bd dep add`.
- Review findings should become separate Beads tasks only when the review step explicitly identifies actionable defects.
- Status mutations are live in the shared Beads backend, so `bd update`, `bd comments add`, and `bd close` show up in Beads UI without a separate `bd sync`.

## Landing the Plane (Session Completion)

When ending a work session, finish the repo-specific closeout before handing off.

- File or update Beads tasks for any remaining follow-up work instead of leaving loose notes.
- Run the applicable quality gate: `make verify-fast` for an incremental slice, `make verify` before handoff, review, or merge approval.
- Update the current bead status, add the handoff note with `bd comments add <id> ...`, and close finished work with `bd close <id>` when appropriate.
- Do not push, merge, or mark work complete ahead of `plan_approval`, `merge_approval`, or `acceptance`.
- Hand off with concrete verification status, blockers, and links inside the active Change Request.


<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do not use markdown TODOs, ad-hoc task lists, or side-channel trackers.

### Quick Start

```bash
make beads-init
bd prime
bd ready
bd mol pour mol-change-request
```

### Repo Workflow

- Run `make beads-init` once per checkout. It attaches the checkout to the shared Dolt backend, copies `beads/PRIME.md`, and seeds the `mol-change-request` formula for local CLI use.
- If you are off-host, open `ssh -N -L 3307:127.0.0.1:3307 <demo-host>` first, then run `make beads-init` with the same `BEADS_DOLT_PASSWORD` that the host stack uses.
- Run `bd prime` at session start and after context compaction. This repo overrides the default Beads primer with `.beads/PRIME.md`.
- Use `bd ready` for ad-hoc work, or `bd mol current` when you are already inside an active Change Request.
- Use `bd update <id> --status in_progress` when you claim a bead, `bd comments add <id> "..."` for progress notes and verification results, `bd create` plus `bd dep add` when new work is discovered, and `bd close <id>` only after the applicable verification target passes.
- The shared Dolt backend is the live source of truth for Beads UI. `bd sync` is optional for snapshots; it is not required for live status updates.

### Verification Rules

- Run `make verify-fast` after each small implementation slice.
- Run `make verify` before handoff, review, or merge approval.
- Do not bypass `plan_approval`, `merge_approval`, or `acceptance`.

<!-- END BEADS INTEGRATION -->
