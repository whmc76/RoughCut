# Agent Current State Template

Use this template when a task family needs its own durable state file. Keep the file factual, current, and small enough that a fresh agent can recover the task without replaying old chat history.

## Current Objective

State the concrete active objective in one or two sentences.

## Current Workstream

- List the active implementation track.
- List the current decision track.
- List the current verification track.

## Open Work

- Record only current unfinished work.
- Keep each item concrete enough to become the next action.

## Resolved Decisions

- Record decisions that must survive long context.
- Prefer "what is settled" and "why" over long history.

## Do Not Reopen

- Record issues that are closed unless fresh live evidence invalidates them.
- Record dead-end paths that should not be retried from stale context.

## Next Concrete Action

- Name the next action the next agent should take first.

## Verification

- Record the smallest checks that prove the current objective is still on track.
- Note any missing verification that must happen before claiming completion.

## Optional Task-Specific Sections

- Add narrow sections only when they help the current task family.
- Put platform-specific current facts here or in that task family's dedicated ledger, not in `AGENTS.md`.
