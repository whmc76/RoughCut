# Agent Current State

This file is the source of truth for the current active task state across long Codex sessions. Update it when the active objective, blockers, or "do not reopen" decisions change.

## Current Objective

Stabilize RoughCut's subtitle and auto-edit pipeline into a stage-disciplined architecture that can support high-throughput batch automatic editing with acceptable quality. The immediate target is to recover a usable end-to-end chain and reach a practical `~90` point operating level before pursuing slower long-tail polish.

## Current Workstream

- Write the authoritative auto-edit recovery architecture and bind it to existing canonical transcript, subtitle projection, and source timeline contracts.
- Split the recovery work into executable milestones with explicit deliverables, acceptance criteria, and dependency order.
- Prioritize high-return fixes: restore manual editor availability, stop cross-stage mutation, restore predictable rule behavior, then improve automatic cut quality.
- Treat publication work as parked context in `docs/publication-agent-ledger.md`; it is not the active objective for this thread.

## Open Work

- Restore real-job manual editor usability and remove hidden fallback behavior that rewrites projection or edit inputs across stages.
- Remove `manual-editor/apply` side mutation: keep subtitle timing/text in the edit contract output, and do not rebind editable subtitles through projection validation repair when no explicit fallback contract allows it.
- Rebuild the rule system so filler words, catchphrases, pause trimming, repeated speech, and smart-delete candidates are generated in one place and audited consistently.
- Add a real-job evaluation harness and golden job set so quality claims are based on repeatable runs rather than screenshots or ad hoc inspection.
- Add a regression test for `_validated_subtitle_projection_for_timeline` contract: default path is non-mutating, repair path is explicit.

## Resolved Decisions

- The recovery direction is "one stage, one responsibility"; no stage may silently re-correct, re-split, or re-delete outputs owned by an earlier stage.
- `ASR evidence`, `canonical transcript`, `subtitle projection`, `edit candidates`, and `final keep/remove decisions` are separate artifacts and must stay separate.
- Subtitle segmentation is a single shared automatic stage. Manual editing may inspect and override the result, but does not become the primary segmentation engine.
- Automatic editing and manual adjustment are two execution modes over the same contracts. Manual mode is a review/refine phase, not a parallel hidden pipeline.
- Current system scoring should be judged on production usefulness, not isolated model quality. The latest real-task evaluation baseline is roughly `62/100` overall and `~72/100` if manual-editor production usability is excluded.
- `manual-editor/apply` now avoids silent subtitle re-write during validation (only diagnostics remain), reducing untraceable timing/text edits introduced at submit time.
- `_validated_subtitle_projection_for_timeline` now has an explicit `apply_repair` switch; `tests/test_pipeline_projection_validation_contracts.py` guards contract: no repair means no content mutation.

## Do Not Reopen

- Do not move active task state back into `AGENTS.md`.
- Do not let display subtitle text become the fact layer for timing or edit decisions again.
- Do not allow subtitle cleanup, filler matching, segmentation, and edit removal to run in overlapping hidden stages.
- Do not treat auto-cut compression ratio alone as success; false deletion rate and sentence naturalness are co-equal quality gates.
- Do not claim the chain is recovered until real jobs can complete manual-editor load, automatic edit generation, and render review without hidden fallback corruption.

## Next Concrete Action

1. Start `T0.1` and reproduce the `/manual-editor` / `/manual-editor/readiness` failure on real jobs with traceback evidence.
2. Start `T0.3` and add high-signal rule/candidate provenance surface for brown/gray/green highlights.
3. Keep `T0.2` contract assertions active and extend to any newly discovered repair path if real-job traces still show hidden edits.

## Verification

- The new design doc must name each pipeline stage, its inputs, outputs, and forbidden side effects.
- The task list must be dependency-ordered and executable without replaying prior chat history.
- The current-state file must point future agents to the active recovery docs instead of stale publication-only state.
