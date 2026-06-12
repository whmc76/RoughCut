# Final Completion Audit Matrix (2026-06-12)

## Purpose

This matrix is the final completion-oriented audit view for the current "strategy contraction / slimming" closure target.

It does not replace:

- `docs/2026-06-11-auto-edit-refactor-closure-checklist.md`
- `docs/2026-06-12-final-closure-audit.md`
- `docs/2026-06-12-final-evidence-capture-runbook.md`

It compresses them into a stricter question:

For each remaining closure requirement, what is the current authoritative evidence, and is the item actually closed, still incomplete, or only waiting on real-sample appearance?

## Audit Scope

This audit uses the narrowed Stage B closure target:

1. `manual-editor / auto-edit / render` mainline no longer drifts across hidden contracts.
2. `raw / canonical / display` surface ownership is structurally recovered.
3. rule generation / auto-apply / manual gating share the same registry contracts.
4. render blocking / failure / audit vocabulary is shared across runtime, report, gate, and audit consumers.
5. golden / scorecard / live gate can support release judgment without parallel local reinterpretation.

`C6` remains intentionally out of closure scope.

## Matrix

| Area | Requirement | Current evidence | Status | Remaining gap type |
|---|---|---|---|---|
| `C1` | text surface ownership is structurally unified | shared surface helpers are already pushed through manual-editor, projection validation, content understanding, translation, and display consumers; major fact/display backfill paths already removed; current closure audit marks the first bad layers as fixed; focused helper/session/golden verification now passes across manual-editor and canonical replay chains | `closed for current scope` | optional real-sample breadth only |
| `C1` | display layer no longer silently revives fact-layer rows | current closure audit and current-state evidence both record that display-suppressed rows no longer re-enter major fact-layer reads; recent manual-editor source-row/session regressions and focused replay checks did not reveal a remaining shared revival path | `closed for current scope` | optional real-sample breadth only |
| `C2` | subtitle-only apply path stays on one shared contract | `verify_manual_editor_apply_semantics.py --json` passes the 4 explicit contract-bearing anchors; shared `manual_editor_change_contract` is the authority | `closed for current scope` | no mainline blocker |
| `C2` | no-material-change save is real, not test-only | real job `abbb6269-5f76-4435-a200-17a751d7632b` captured via `scripts/capture_manual_editor_no_material_change.py --apply`; real apply response and latest editorial/render-plan metadata all resolve to `no_material_change / metadata_refresh_render / platform_package` | `closed for current scope` | no mainline blocker |
| `C2` | manual editor save does not drop frontend-managed auto cuts | shared apply helpers and narrowed manual-editor regressions are already in current-state evidence; golden/manual verifier proves roundtrip consistency on real anchors | `closed for current scope` | optional broader coverage only |
| `C3` | rule registry is the single source of truth for auto-apply eligibility | `RuleDefinition.auto_apply_in_auto_mode`, registry-driven multimodal review, resolved candidate reads, and focused `rule_registry/source_timeline_contract/manual_editor_helpers` verification now all align on one contract | `closed for current scope` | optional future tuning only if new false-delete evidence appears |
| `C3` | downstream consumers no longer locally guess applied cuts / review gates | current-state evidence plus focused `resolved-candidate / auto-refine / multimodal gate / frontend-managed auto-cut` regressions now show no active structural contradiction across main consumers | `closed for current scope` | optional evidence breadth only |
| `C4` | render failure classification is shared across report consumers | `roughcut.pipeline.render_diagnostics` is already the shared helper used by batch, readiness, scorecard, and audit snapshot paths | `closed for current scope` | no structural blocker |
| `C4` | timeout and `render_ffprobe_failed` mainlines have real end-to-end evidence | real timeout sample `output/test/auto-edit-recovery-golden/c5-high-risk-render-anchor-long/20260611-094926` and controlled real-chain `render_ffprobe_failed` sample `output/test/auto-edit-recovery-golden/controlled-render-failure/20260612-060442` both pass `scripts/verify_render_failure_signal_consistency.py` | `closed for current scope` | natural provider-class breadth only |
| `C4` | avatar provider/busy/slot-timeout classes have natural replay evidence | widened SQL scan over the most relevant artifact types still returns `0`; wider offline audit-snapshot review still shows mainly timeout / partial-stop outcomes | `optional breadth only` | wait for future real sample appearance |
| `C5` | golden / scorecard / live gate share the same mainline contracts | current-state evidence records shared required-check, manual-editor semantics, risk-gate, and render-diagnostics consumption | `closed for current scope` | no structural blocker |
| `C5` | scorecard / live gate can already express current real failures | current timeout sample passes the new offline consistency verifier; live gate and scorecard render-stage failure already align on that real sample | `closed for current known failure mainline` | only future sample classes need replay evidence |
| `C5` | report surface is slim enough for delivery decisions | current-state now records a real-sample-driven markdown contraction on `output/test/auto-edit-recovery-golden/controlled-render-failure/20260612-060442`, with JSON evidence preserved and markdown focused on blockers | `closed for current scope` | only future sample-driven tweaks if noise reappears |
| `C6` | smart delete quality enhancement | explicitly deferred by closure docs | `deferred` | out of current scope |

## Current Closure Judgment

### Structurally closed or effectively closed

- `C2` mainline closure
- `C3` mainline registry/risk unification
- `C4` timeout-mainline report/gate/audit alignment
- `C5` mainline gate/report contract alignment
- `C5` current markdown/report contraction

### Near closure but still with optional breadth work

- optional future `C5` display tuning only if newer real samples demand it

### Not structurally open, but still sample-incomplete

- `C4` natural provider-class render failure classes:
  - `avatar_full_track_provider_response_error`
  - `avatar_full_track_busy_exhausted`
  - `avatar_full_track_slot_timeout`

## Decision Rule

The current goal should not be treated as "needs more framework refactor".

The current goal should be treated as:

1. structurally closed enough for Stage B mainline;
2. remaining only at optional breadth where natural provider-class replay evidence does not yet exist in the current workspace;
3. only optionally tweak the report surface again if a newer real sample proves the current contraction is still noisier than needed.

## Practical Conclusion

If no new provider-class real failure sample exists, the correct action is not more code churn.

The correct action is to preserve the current narrowed closure state and wait for the next real target-class sample, then run:

1. `docs/2026-06-12-final-evidence-capture-runbook.md`
2. `scripts/verify_render_failure_signal_consistency.py`

until the optional breadth gap is closed.
