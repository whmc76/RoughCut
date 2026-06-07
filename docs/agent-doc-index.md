# Agent Document Index

Use this file to route into the smallest set of source-of-truth documents needed for the current task. Do not read every doc by default.

## Default Read Path

1. `AGENTS.md`
2. `docs/agent-current-state.md`
3. one or more task-specific docs below

## State Templates

- `docs/agent-current-state-template.md`
  Template for new task-family state files when a long-running workflow needs durable task state outside chat history.

## Publication Work

- `docs/publication-agent-ledger.md`
  Current publication-session facts, open blockers, resolved issues, and "do not reopen" decisions.
- `docs/publication-adapter-autopilot-runbook.md`
  Command flow, release gates, adapter behavior, and operating procedure.
- `docs/codex-publication-incident-20260605.md`
  Incident history and root-cause writeup. Read only when debugging process failures or refining operating rules.

## Product / Architecture Context

- `README.md`
  Project overview, environment, commands, and major subsystem structure.
- `docs/design/INDEX.md`
  Design-doc entrypoint for deeper architecture work.

## Read Discipline

- Prefer the current state doc and the narrowest relevant task doc over broad historical reading.
- If a current-state doc conflicts with an incident doc, trust the current-state doc unless fresh runtime evidence proves it stale.
- If no current-state doc exists for a task family, create one instead of overloading `AGENTS.md`.
