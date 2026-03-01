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

- The demo workspace ships the `mol-change-request` formula copied from `examples/`.
- Create a new Change Request with `bd mol pour mol-change-request`.
- Follow the canonical path: `plan -> plan_approval -> implement -> review -> ci -> merge_approval -> merge -> deploy -> acceptance`.
- Do not bypass `plan_approval`, `merge_approval`, or `acceptance`.
- If the sequence or gate semantics change, update this file, `README.md`, and the seeded formula in the same change set.

## Architecture and Change Control

- `README.md` is the authoritative runtime contract for the demo stack. Keep compose, ingress, and workflow sections synchronized with real behavior.
- The fixed compose contract is a blocking architecture boundary: service names, internal ports, and the `demo-agentforge-web` alias do not change casually.
- Treat changes to workflow order, approval semantics, ingress shape, or long-lived runtime boundaries as architectural changes, not incidental edits.
- When a demo change affects a long-lived invariant shared with the parent AgentForge repo, sync the rationale back into the parent architecture docs (`docs/ARCHITECTURE.md`, `docs/adr/`, or `docs/agent_decisions.md`) in the same change set.

## Agent Expectations

- Agents should publish handoff summaries, verification results, questions, and links back into the active Change Request.
- If the next step requires a human, record the blocking questions in the current gate instead of opening a side channel.
- Review findings should become separate Beads tasks only when the review step explicitly identifies actionable defects.
