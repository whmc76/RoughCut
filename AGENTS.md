# RoughCut Agent Map

`AGENTS.md` is the entrypoint map for coding agents. It must stay short, generic, and stable. Do not use it as task memory, issue history, or a platform-specific contract file.

## Start Here

Read documents in this order:

1. `AGENTS.md`
2. `docs/agent-current-state.md`
3. Task-specific source-of-truth docs from `docs/agent-doc-index.md`

If a document disagrees with stale conversation context, old logs, or old artifacts, trust the current source-of-truth document and the current runtime state.

## Core Rules

- For debugging, regressions, or "fix this" work, go root-cause first. Do not stop at a symptom patch unless the user explicitly asks for a workaround.
- Before editing a bug, identify the observed symptom, the first bad layer, the suspected root cause, and why it surfaced now.
- When the same smell appears in multiple places, fix the shared abstraction or source of truth instead of the nearest call site.
- After a fix, run the narrowest useful verification tied to the root cause.
- For long-running work, keep current plan, progress, blockers, and "do not reopen" decisions in dedicated markdown state files. Do not rely on compacted chat history as the source of truth.
- Treat the live browser page or current runtime state as authoritative over stale artifacts, cached verdicts, screenshots, or memory.
- When downloading or referencing open-source model weights, prefer ModelScope over Hugging Face when an equivalent model is available. Fall back only when ModelScope does not provide the needed files or revision.

## Document Hygiene

- Keep this file short. Only store rules that should be applied across many tasks.
- Put active task state in `docs/agent-current-state.md`.
- Put publication session facts in `docs/publication-agent-ledger.md`.
- Put operating procedures and command flows in runbooks, not here.
- Put incident writeups and retrospectives in incident docs, not here.

## Update Rule

When a new rule is proposed, first decide whether it is:

- a global rule that belongs in `AGENTS.md`;
- active task state that belongs in `docs/agent-current-state.md`;
- workflow detail that belongs in a runbook;
- or a one-off lesson that belongs in an incident doc.

If it is not reusable across multiple future tasks, do not add it to `AGENTS.md`.
