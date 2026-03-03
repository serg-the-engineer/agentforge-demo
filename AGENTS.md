# Demo AgentForge Guidelines

## Delivery Discipline

- Use TDD for demo changes: add or update the narrowest automated check before changing behavior.
- Prefer `tests/test_api_server.py` for Python helper logic and extend `scripts/verify.sh` when the change is a static/runtime contract.
- Run `make verify-fast` from the `demo-agentforge/` checkout after each small implementation slice.
- Run `make verify` before handoff, review, or merge approval.
- Treat a failing applicable verify target as a blocker; review comments are additive, not a substitute for passing checks.
- Keep changes single-purpose. Split mixed product and infrastructure work unless the fixed contract change requires both in one change set.

## Architecture and Change Control

- `README.md` is the authoritative runtime contract for the demo stack. Keep compose, ingress, and workflow sections synchronized with real behavior.
- The fixed compose contract is a blocking architecture boundary: service names, internal ports, the loopback-only Beads backend port, and the `demo-agentforge-web` alias do not change casually.
- Treat changes to workflow order, approval semantics, ingress shape, or long-lived runtime boundaries as architectural changes, not incidental edits.
- When a demo change affects a long-lived invariant shared with the parent AgentForge repo, sync the rationale back into the parent architecture docs (`docs/ARCHITECTURE.md`, `docs/adr/`, or `docs/agent_decisions.md`) in the same change set.
- Run `make verify-fast` after each small implementation slice. Run `make verify` before handoff, review, or `review_approval`, then post the result in the active Change Request with `bd comments add <id> ...`.
- If the next step requires a human, record the blocking questions in the current gate instead of opening a side channel.

## Landing the Plane (Session Completion)

When ending a work session, finish the repo-specific closeout before handing off.

- File or update Beads tasks for any remaining follow-up work instead of leaving loose notes.
- Run the applicable quality gate: `make verify-fast` for an incremental slice, `make verify` before handoff, review, or `review_approval`.
- Hand off with concrete verification status, blockers, and links inside the active Change Request.