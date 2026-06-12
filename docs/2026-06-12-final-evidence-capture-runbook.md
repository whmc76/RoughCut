# Final Evidence Capture Runbook (2026-06-12)

## Purpose

This runbook defines the shortest operational path for the last real-sample evidence gaps under the current "strategy contraction / slimming" direction.

It exists to prevent more framework edits when the remaining closure work is only:

1. one real `manual_editor no_material_change / metadata_refresh_render` sample;
2. one or two real `ffmpeg/provider` render-failure samples;
3. one final scorecard / required-check trimming pass only if a fresh sample proves it is needed.

If a future agent is about to add new helpers, new report fields, or new registry structure for these gaps, stop and run this document first.

## Current Facts

- Current workspace closure state is summarized in `docs/2026-06-12-final-closure-audit.md`.
- Current task state is summarized in `docs/agent-current-state.md`.
- Existing SQL and workspace scans already confirmed there are no reusable real samples in the current workspace for:
  - `manual_editor_no_material_change / metadata_refresh_render`
  - `ffmpeg_* / render_ffprobe_failed`
  - `avatar_full_track_provider_response_error / avatar_full_track_busy_exhausted / avatar_full_track_slot_timeout`
- Existing real verification already covers:
  - narrowed `manual_editor_apply_semantics` anchors via `scripts/verify_manual_editor_apply_semantics.py`
  - timeout-mainline render diagnostics via `scripts/run_auto_edit_recovery_golden_set.py`

## Do Not Expand

- Do not add new batch report fields just to describe a missing sample.
- Do not add new golden manifest schema unless a real replay cannot be represented.
- Do not add new render-diagnostics helpers unless a fresh real failure cannot be normalized by the current shared helper.
- Do not try to "simulate closure" with test-only synthetic fixtures when the gap is explicitly real-sample evidence.

## Gap A: Real `manual_editor no_material_change` Sample

### Goal

Capture one real job where manual-editor save resolves to:

- `change_scope = no_material_change`
- `render_strategy = metadata_refresh_render`
- rerun shrunk to `platform_package`

### Why This Gap Still Exists

Current contract code and verifier already support this path, but current workspace scans found no existing real anchor carrying this shape.

### Preferred Capture Path

Use an already healthy manual-editor anchor and perform a true "open and save without effective edits" operation in the product flow.

Preferred existing anchors from `docs/golden-jobs/auto-edit-recovery-golden-slice.v1.json`:

- `noc_mt34_manual_editor_anchor`
- `edc17_manual_editor_anchor`
- `noc_mt34_short_done`
- `noc_mt34_long_done`

You can also locate current real-job candidates directly from the database without touching the manifest:

```powershell
python scripts/list_final_evidence_candidates.py --mode manual_editor --limit 20 --json
```

### Shortest Operational Steps

1. Choose one of the anchors above whose manual editor can already open cleanly.
2. In the real product/manual flow, open manual editor.
3. Do not change keep segments.
4. Do not change effective subtitle content.
5. Trigger a normal save/submit path anyway.
6. Record the resulting `job_id`.
7. Verify that the saved result resolved to the shared no-change contract instead of a fake render rerun.

### Verification Commands

Baseline contract verifier:

```powershell
python scripts/verify_manual_editor_apply_semantics.py --json
```

If the newly created real sample is not yet in the golden manifest, inspect it directly by `job_id` or `source_name` through the existing shared inspector path in `scripts/run_auto_edit_recovery_golden_set.py::inspect_manual_editor_apply_semantics(...)`.

Direct CLI examples:

```powershell
python scripts/verify_manual_editor_apply_semantics.py --job-id <job_id> --json
python scripts/verify_manual_editor_apply_semantics.py --source-name "<source_name>" --json
```

Minimum DB / artifact facts to confirm on the captured job:

- `change_scope = no_material_change`
- `render_strategy = metadata_refresh_render`
- rerun issue code resolves to `manual_editor_no_material_change`
- rerun start step is `platform_package`
- no new timeline mutation is introduced just by the save

### Exit Evidence

This gap is closed only when one real saved job can be cited with:

- `job_id`
- source name
- save operation context
- contract payload showing `no_material_change / metadata_refresh_render`

Current captured sample:

- `job_id = abbb6269-5f76-4435-a200-17a751d7632b`
- capture command:

```powershell
python scripts/capture_manual_editor_no_material_change.py --job-id abbb6269-5f76-4435-a200-17a751d7632b --apply --json
```

- confirmed real outputs:
  - `change_scope = no_material_change`
  - `render_strategy = metadata_refresh_render`
  - `rerun_steps = [platform_package]`

## Gap B: Real `ffmpeg/provider` Render-Failure Samples

### Goal

Capture one or two fresh real failures proving the current shared diagnostics chain already normalizes non-timeout render failures without new helper drift.

Priority classes:

1. `ffmpeg_*`
2. `render_ffprobe_failed`
3. `avatar_full_track_provider_response_error`
4. `avatar_full_track_busy_exhausted`
5. `avatar_full_track_slot_timeout`

### Why This Gap Still Exists

The code path is already shared and tested, but current workspace evidence is concentrated on `avatar_full_track_call_timeout`. The missing part is fresh replay evidence for the other classes.

### Preferred Capture Path

Do not force artificial code changes to manufacture a failure class. Wait for the next naturally occurring replay failure, then preserve it through the existing batch/golden reporting chain.

Preferred capture entrypoint:

```powershell
python scripts/run_auto_edit_recovery_golden_set.py --manifest docs/golden-jobs/auto-edit-recovery-golden-slice.v1.json --case-id <case_id> --report-dir output/test/auto-edit-recovery-golden/final-evidence
```

To check whether the latest workspace already contains reusable failure candidates before replaying again:

```powershell
python scripts/list_final_evidence_candidates.py --mode render_failure --limit 80 --json
```

Use `--stop-after render` only when the failure class requires render execution. Use lighter stages when the target class is already known earlier.

### Shortest Operational Steps

1. Pick a real anchor most likely to exercise render again.
2. Run a fresh replay through `scripts/run_auto_edit_recovery_golden_set.py`.
3. If the replay fails with one of the target classes, preserve the report directory immediately.
4. Verify that the same root cause is visible across all shared consumers instead of only one layer.

### Required Evidence Surface

For the captured replay, confirm the same class is reflected consistently in:

- `batch_report.json`
- `golden_set_summary.md`
- `detailed_output_scorecard.json` or markdown
- audit snapshot / audit markdown when generated
- `live_readiness` summary

Fast verification entrypoint:

```powershell
python scripts/verify_render_failure_signal_consistency.py --report-dir <report_dir> --json
```

This verifier is intentionally narrow. It checks whether the current report directory keeps the same failed render jobs aligned across:

- job-level `render_diagnostics`
- `render_diagnostics_summary.failed_render_job_ids`
- `live_readiness.checks.render_end_state_stability.failed_render_job_ids`
- scorecard render-stage failure rows
- audit snapshot coverage for failed jobs

### Expected Normalized Outcomes

The captured result should already map through the current shared helpers to one of these reason families:

- `ffmpeg_render_failed`
- `ffmpeg_packaging_failed`
- `render_ffprobe_failed`
- `provider_error`
- `busy_exhausted`
- `slot_timeout`

If a fresh real failure cannot be expressed by those families, that is the moment to consider a code change. Not before.

### Exit Evidence

This gap is closed only when at least one fresh replay directory can be cited with:

- replay command
- report directory
- target failure class
- proof that batch, scorecard, audit, and live-readiness all surface the same normalized reason

## Gap C: Final Scorecard / Required-Check Trimming

### Trigger Condition

Do not do this by default.

Only trim again if a fresh real sample shows that scorecard or required-check output still carries non-delivery-critical fields that obscure the operator decision.

### Acceptance Rule

Keep only fields directly needed to answer:

- did the run complete
- if not, why not
- how many high-risk / manual-confirm items remain
- whether manual-editor contract passed
- whether render end state is stable

## Minimal Closure Sequence

Run closure in this order:

1. Capture one real `manual_editor no_material_change` sample.
2. Capture one fresh `ffmpeg/provider` failure replay if and when it naturally reappears.
3. Trim scorecard / required-checks only if that fresh replay proves there is still report noise.

If step 1 or step 2 cannot be completed because the real sample does not exist yet, do not reopen the main framework. Leave the code as-is and keep the gap labeled as evidence-only.

## Completion Rule

The refactor is not "more complete" because more abstractions were added.

It is more complete only when the remaining evidence-only gaps above are filled, or explicitly proven absent in the current workspace with no additional framework drift introduced.
