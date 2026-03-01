# Demo AgentForge Beads Workflow

## Session Start

- Run `make beads-init` once per checkout to attach it to the shared Beads backend, seed this file, and install the `mol-change-request` formula locally.
- If you are off-host, open `ssh -N -L 3307:127.0.0.1:3307 <demo-host>` before `make beads-init`.
- Run `bd prime` at the start of every agent session and after any context compaction or handoff.
- Use `bd ready` for ad-hoc work, or `bd mol current` when you are already inside an active Change Request.

## Change Request Flow

- Start new work with `bd mol pour mol-change-request`.
- Respect the fixed flow: `plan -> plan_approval -> implement -> review -> review_approval -> ci -> merge -> deploy -> acceptance`.
- Do not bypass `plan_approval`, `review_approval`, or `acceptance`.
- `review_approval` is a human Beads gate: code-review approval is captured by Beads status, not GitHub PR review approval.

## Step Rules

- When an agent starts a bead, run `bd update <id> --status in_progress` and post the current plan or status in the Change Request.
- Use `bd comments add <id> "..."` for verification output, blockers, and handoff notes.
- Run `make verify-fast` after each small implementation slice.
- Run `make verify` before closing `implement`, before handoff to review, and before asking for `review_approval`.
- If you discover new work, create a separate issue with `bd create "..." --type task --priority 2` and connect blockers with `bd dep add <blocked-id> <blocking-id>`.
- In `review`, create separate Beads tasks only for actionable defects.
- The shared backend is live, so UI updates happen as soon as `bd update`, `bd comments add`, or `bd close` succeeds.

## Session End

- Close finished steps with `bd close <id>` only after the applicable verification target passes.
- `bd sync` is optional for snapshots; it is not required for live UI visibility.
- If a human is needed, leave the blocking question in the current gate instead of opening a side channel.
