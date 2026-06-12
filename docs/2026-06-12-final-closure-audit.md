# Auto-Edit Refactor Final Closure Audit (2026-06-12)

## Scope

This audit evaluates the current closure state of the roughcut auto-edit refactor under the "strategy contraction / slimming" direction. The question is no longer "what large framework is still missing", but:

1. whether the main shared contracts have already been pulled back to single sources of truth;
2. whether the main runtime/report/gate consumers now reuse those contracts instead of re-guessing locally;
3. whether the remaining gaps are code structure gaps or only missing real-sample evidence.

## Executive Conclusion

Within the current workspace, `C1-C5` are effectively in the "main framework closed, only optional evidence breadth remains" state.

- `C1` is no longer blocked by major surface-contract drift and is now closed for the current narrowed scope; remaining work is optional real-sample breadth only.
- `C2` is no longer blocked by apply/render contract divergence, and one real `no_material_change / metadata_refresh_render` anchor has now been captured.
- `C3` is no longer blocked by duplicated auto-apply / multimodal / candidate metadata logic and is now closed for the current narrowed scope; remaining work is optional future tuning only when a real false-delete sample appears again.
- `C4` is no longer blocked by report-chain vocabulary drift; `render_ffprobe_failed` replay evidence is now captured on the real chain, and only natural provider-class sample breadth remains optional.
- `C5` is no longer blocked by golden/scorecard/live-gate contract fragmentation; the scorecard markdown surface has now been trimmed against a real failure sample, and only future sample-driven tweaks remain optional.
- `C6` remains intentionally deferred. It is not a refactor-closure blocker and should not be expanded before new real false-delete/miss-delete evidence appears.

## Package Audit

### C1 Text Surface Mainline

Current evidence:

- shared surface helpers exist and have already been pushed through manual-editor, projection validation, quality/review, content understanding, translation, and display consumers;
- canonical/projection refresh paths no longer backfill `text_final` into raw/canonical fact layers;
- display-suppressed rows are no longer supposed to re-enter fact-layer reads through the previously identified major paths.

Current status:

- `closed for current scope`

What is still missing:

- no further shared-helper refactor is justified on current workspace evidence;
- only optional real-sample breadth remains, in case a future anchor exposes a still-hidden long-tail consumer.

Why this is not a framework blocker anymore:

- the first bad layers that used to mutate or re-interpret fact surfaces have already been moved onto shared helpers and explicit layer ownership;
- focused helper regressions, manual-editor session regressions, and manual-editor golden semantics coverage now all pass without exposing a new shared surface-contract leak.

### C2 Manual Editor Invariants

Current evidence:

- `manual_editor_change_contract`, rerun shrinking, subtitle-only render reuse, and frontend-managed auto-cut re-application are shared contracts now;
- golden/manual-editor verification now uses the shared contract instead of hardcoding `subtitle_only` as the only valid passing state;
- `verify_manual_editor_apply_semantics.py --json` now defaults to the 4 cases that explicitly require the `manual_editor_apply_semantics` contract, and all 4 pass;
- one of those passing anchors (`edc17_manual_editor_anchor`) has `managed_auto_cut_count=0`, proving zero-managed-cut subtitle-only cases are part of the real verification surface.
- one real no-op save sample has now been captured on job `abbb6269-5f76-4435-a200-17a751d7632b` via `scripts/capture_manual_editor_no_material_change.py --apply`, and the real apply response plus latest editorial/render-plan metadata all resolve to:
  - `change_scope = no_material_change`
  - `render_strategy = metadata_refresh_render`
  - `rerun_steps = [platform_package]`

Current status:

- `closed for current scope`

What is still missing:

- optional broader evidence for `base_keep_segments` in more real editorial/render-plan shapes.

Why this is not a framework blocker anymore:

- the previous sample gap is now filled by a real saved job, so the remainder is only optional breadth rather than a missing mainline proof point.

### C3 Rule Registry and Risk Gates

Current evidence:

- rule metadata is centralized in `RuleDefinition`;
- frontend-managed reason sets and timeline-contract reason sets are derived from registry metadata instead of parallel handwritten sets;
- multimodal-review default gating is registry-driven;
- resolved candidate reads and auto-apply fallback logic are shared;
- auto-apply eligibility is no longer implicit `risk_level == low` alone and is now anchored in rule-registry contract.

Current status:

- `closed for current scope`

What is still missing:

- no forced code expansion should be done now;
- only optional future tuning should react to real false-delete / mis-bucket evidence, not to a desire for taxonomy completeness.

Why this is not a framework blocker anymore:

- the repeated local guesses that used to fragment candidate metadata, multimodal gates, and auto-apply semantics are already gone from the main consumers.
- focused 2026-06-12 verification now also passes on the remaining shared C3 contracts:
  - `tests/test_rule_registry.py tests/test_source_timeline_contract.py -q` (`13 passed`)
  - `tests/test_manual_editor_helpers.py -k "cut_analysis_candidate_items_resolved_reuses_shared_auto_apply_contract or cut_analysis_effective_applied_cuts_resolves_legacy_auto_payload_candidates or refine_decision_plan_auto_refine_resolves_legacy_low_risk_rule_candidates or refine_decision_plan_auto_refine_applies_low_risk_rule_candidates or multimodal_trim_review_payload_uses_registry_for_default_semantic_review_rules or cut_analysis_payload_keeps_reviewed_rule_candidate_out_of_rule_auto_apply_bucket or frontend_managed_auto_cuts_keep_low_risk_catchphrase_ranges" -q` (`7 passed`)

### C4 Render Runtime Blocking and Fallback

Current evidence:

- shared render diagnostics helpers now normalize render-step failures and avatar reason categories;
- batch report, live readiness, audit snapshot/pack, and scorecard all consume the same root-cause vocabulary instead of carrying parallel local ladders;
- timeout mainline has real evidence across runtime diagnostics, batch report, audit, live gate, and scorecard;
- weak `missing_avatar_render` fallbacks no longer override stronger failed-render root causes.
- a controlled real-chain replay now also proves `render_ffprobe_failed` flows through the same shared diagnostics path:
  - report dir: `output/test/auto-edit-recovery-golden/controlled-render-failure/20260612-060442`
  - offline verifier: `python scripts/verify_render_failure_signal_consistency.py --report-dir output/test/auto-edit-recovery-golden/controlled-render-failure/20260612-060442`
  - verifier result: `ok=true`

Current status:

- `closed for current scope`

What is still missing:

- optional natural-sample breadth for avatar provider/busy/slot-timeout classes if they reappear in production-like runs.

Why this is not a framework blocker anymore:

- timeout and `render_ffprobe_failed` now both have end-to-end evidence on the existing shared report/gate/audit chain;
- therefore no additional render runtime/report refactor is justified before a genuinely new provider-class failure appears.

### C5 Real Evaluation and Release Gates

Current evidence:

- golden slice, batch report, audit pack, detailed scorecard, and live readiness are all active;
- manual-editor semantics, render diagnostics, required checks, and risk metrics are all consumed by live gating rather than staying as side reports;
- legacy/edit-plan/no-bundle paths now reuse shared fallback contracts instead of hardcoded zeroed or stale issue-code interpretations;
- real anchors already prove the gate/scorecard/report chain is not test-only.
- scorecard markdown has now been contracted on top of the controlled real-chain `render_ffprobe_failed` sample so failed runs emphasize delivery blockers instead of repeating `N/A / skipped / not_generated / pass` detail.

Current status:

- `closed for current scope`

What is still missing:

- do not add new fields unless a new real anchor failure cannot be explained otherwise;
- only revisit markdown/report contraction if a newer real sample still proves operator-facing noise remains.

Why this is not a framework blocker anymore:

- the main problem is no longer report-chain contradiction but final contraction of evidence surfaces and selective fresh replay coverage.

### C6 Smart Delete Quality Enhancement

Current status:

- `intentionally deferred`

Why it is not part of closure:

- the current closure direction explicitly parks systemic quality expansion until new real false-delete/miss-delete evidence appears.

## Evidence Summary

Real verification already available in workspace:

- 4 explicit `manual_editor_apply_semantics` anchors pass under the narrowed verifier.
- Existing real render-failure evidence is concentrated on the `avatar_full_track_call_timeout` mainline and is now normalized consistently across report consumers.
- A controlled real-chain replay now also closes the `render_ffprobe_failed` proof gap at `output/test/auto-edit-recovery-golden/controlled-render-failure/20260612-060442`, with offline consistency verification returning `ok=true`.
- Current DB artifact subset query previously confirmed absence of reusable real samples for:
  - `manual_editor_no_material_change / metadata_refresh_render`
  - `avatar_full_track_provider_response_error / avatar_full_track_busy_exhausted / avatar_full_track_slot_timeout`
- That `manual_editor_no_material_change / metadata_refresh_render` gap is now closed by the captured real sample on job `abbb6269-5f76-4435-a200-17a751d7632b`.
- A wider 2026-06-12 follow-up scan still found no reusable natural provider-class hits in the most relevant artifact types, and offline review of current `output/test/auto-edit-recovery-golden/**/*.snapshot.json` failures still points mainly to timeout / partial-stop outcomes.

## Final Judgment

The remaining work is no longer "continue refactoring the main framework".

The remaining work is:

1. optionally capture natural provider/busy/slot-timeout samples if they appear again;
2. optionally tweak report surface again only if a newer real sample proves the current contraction is still too noisy.

Until those samples exist, further code churn is more likely to create noise than to materially improve closure.
