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

## Auto Edit Recovery

- `docs/design/2026-06-08-auto-edit-quality-recovery-architecture.md`
  Current source-of-truth architecture for restoring predictable subtitle, projection, and automatic editing behavior.
- `docs/2026-06-08-auto-edit-quality-recovery-task-list.md`
  Dependency-ordered execution plan for the current recovery and quality-uplift work.
- `docs/2026-06-11-auto-edit-refactor-closure-checklist.md`
  Consolidated closure checklist for finishing the refactor, optimization, and hardening pass through production-grade acceptance.
- `docs/2026-06-12-final-closure-audit.md`
  Current judgment on what is structurally closed versus what is only missing real-sample evidence.
- `docs/2026-06-12-final-completion-audit-matrix.md`
  Requirement-by-requirement completion matrix for deciding what is actually closed, what is optional breadth, and what is still only missing real samples.
- `docs/2026-06-12-final-evidence-capture-runbook.md`
  Shortest operational path for the remaining real-sample gaps; use this before any further framework edits.
- `docs/golden-jobs/auto-edit-recovery-golden-slice.v1.json`
  First committed real-job golden slice for recovery replay and regression evidence.

## Read Discipline

- Prefer the current state doc and the narrowest relevant task doc over broad historical reading.
- If a current-state doc conflicts with an incident doc, trust the current-state doc unless fresh runtime evidence proves it stale.
- If no current-state doc exists for a task family, create one instead of overloading `AGENTS.md`.
