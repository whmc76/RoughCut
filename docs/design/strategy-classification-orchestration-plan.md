# Strategy Classification Orchestration Plan

**文档同步版本：** RoughCut v0.1.5 后续重构计划

## Purpose

RoughCut 的剪辑能力不能以一套通用 video-cut 流程默认套到所有任务上。正确方向是先识别视频类型、生产意图和素材状态，再选择策略、能力矩阵和生产线。

本计划定义从视频分类到剪辑策略编排的可落地契约：

```text
evidence -> classification_tags -> strategy_profile
         -> capability_orchestration -> pipeline_plan -> review_gates
```

其中：

- `classification_tags` 是事实层，描述视频和素材是什么。
- `strategy_profile` 是决策层，决定使用哪类剪辑策略。
- `capability_orchestration` 是能力层，决定哪些剪辑能力启用、建议、人工确认或禁用。
- `pipeline_plan` 是生产线层，决定需要哪些后续 review gate 和执行能力。

## Current Baseline

当前代码已具备基础策略编排层：

- `roughcut.edit.strategy_profile`：集中推断 `strategy_type`。
- `roughcut.edit.capability_policy`：根据策略和内容画像解析默认能力状态。
- `roughcut.edit.capability_orchestrator`：输出 `capability_orchestration` payload。
- `roughcut.edit.product_controls`：承接创建任务、watch root、用户选择和运行时默认值。

本轮新增的低风险基础是：

- `strategy_classification.v1`：归一化分类标签。
- `strategy_pipeline_plan.v1`：把策略解析成生产线特征和 review gates。
- `strategy_policy.v1`：为每个 strategy 固化 cut、review、render validation 和 capability default policy。
- `strategy_review_gates.v1`：把 `pipeline_plan.review_gates` 解析成 required/recommended/optional gate 状态和 blocking summary。
- `strategy_review_gates` artifact：当 content profile carrying `capability_orchestration` is persisted, gate status can be stored as durable artifact evidence.
- `strategy_review_gate_confirmations.v1`：把 operator confirmation 绑定到当前 `pipeline_plan` + classification evidence fingerprint，rerun 后证据变化会让旧确认失效。
- `strategy_storyboard_review` artifact：为 `storyboard_review_required` 生成绑定策略证据 fingerprint 的结构化分镜草案。
- `strategy_timeline_preview` artifact：为 `timeline_preview_required` 生成绑定策略证据 fingerprint 的结构化时间线预览草案。
- `capability_orchestration.classification`：保留分类事实快照。
- `capability_orchestration.pipeline_plan`：保留下游可消费的生产线计划。

## Classification Contract

分类结果必须是多标签结构，不能退回单一 `content_kind`。

```json
{
  "schema": "strategy_classification.v1",
  "primary_type": "talking_head",
  "production_mode": "source_cut",
  "content_tags": ["commentary", "product_demo"],
  "media_tags": ["single_speaker", "speech_dominant"],
  "editing_signals": ["retake_likely", "silence_trim_useful", "subtitle_important"],
  "asset_tags": ["visual_inserts_available"],
  "confidence": 0.86
}
```

Source priority:

1. User-selected product controls and explicit `strategy_profile`.
2. Explicit `strategy_classification` from `source_context` or content profile.
3. Watch root and creator-card defaults.
4. Automatic content/video understanding.
5. Workflow template and legacy `content_kind`.
6. Project default.

Weak automatic labels may guide fallback behavior, but must not override stronger explicit inputs or hard evidence such as multi-material inventory.

## Strategy Mapping

The initial mapping is intentionally conservative:

| Strategy | Typical Tags | Default Use |
| --- | --- | --- |
| `information_density` | `talking_head`, `commentary`, `speech_dominant`, `retake_likely` | 口播、观点、产品讲解的密度压缩和低风险清理 |
| `step_demonstration` | `tutorial`, `screen_recording`, `step_by_step`, `workflow_breakdown` | 教程、录屏、操作演示 |
| `experience_and_mood` | `vlog`, `food`, `travel`, `experience` | 体验、探店、氛围类内容 |
| `event_highlight` | `gameplay`, `highlight`, `event_highlight`, or `high_energy` with event context such as `sports` / `match` / `action_peak` | 游戏、活动、高光提炼 |
| `narrative_assembly` | `remix`, `script_driven`, `digital_human`, `material_insert_required`, `storyboard_required` | 影视二创、数字人解说、多素材混剪 |

External video-use / videocut ideas are only absorbed through these strategy contracts. A口播清理 rule, storyboard preview, or avatar production gate must be enabled by matching tags and strategy, not as a global default.

Classification tags are typed signals, not equal-weight votes. A broad pacing signal such as `high_energy` may increase confidence for an event strategy when paired with event context, but it must not by itself reclassify a product unboxing, talking-head, or vlog into `event_highlight`.

## Pipeline Plan Contract

`pipeline_plan` is the bridge from strategy decision to production flow.

```json
{
  "schema": "strategy_pipeline_plan.v1",
  "strategy_type": "narrative_assembly",
  "production_mode": "remix",
  "primary_type": "avatar_commentary_remix",
  "enabled_features": [
    "avatar_render",
    "material_insert_plan",
    "storyboard_review",
    "timeline_preview",
    "tts_generation"
  ],
  "review_gates": [
    "strategy_confirmation_required",
    "storyboard_review_required",
    "timeline_preview_required"
  ],
  "strategy_policy": {
    "schema": "strategy_policy.v1",
    "strategy_type": "narrative_assembly",
    "cut_policy": {"basis": "script_segment"},
    "review_policy": {"storyboard_review": "required"},
    "render_validation_policy": {"check_storyboard_alignment": true},
    "capability_defaults": {"multi_material_assembly": "manual_required"}
  },
  "reason_codes": ["assembly_or_remix_tags", "avatar_commentary_tags"],
  "classification_confidence": 0.78,
  "requires_operator_confirmation": false
}
```

Downstream steps must treat this as a plan, not as a substitute for step-local validation. Render, subtitle projection, avatar generation, and publication still validate their own inputs.

## Phased Closure Targets

### Phase 0: Contract Foundation

Goal: make strategy classification visible and testable without changing durable pipeline shape.

Done when:

- `capability_orchestration` includes `classification` and `pipeline_plan`.
- Explicit strategy/product controls still win over auto classification.
- Multi-material inventory can still select `narrative_assembly`.
- Targeted tests cover talking-head, tutorial, avatar/remix, override priority, and content-profile attachment.

Recommended verification:

```bash
uv run pytest tests/test_capability_orchestrator.py tests/test_product_controls.py tests/test_video_understanding_downstream.py tests/test_content_profile_api_payloads.py -q
```

### Phase 1: Classifier Input Expansion

Goal: feed better classification evidence into `strategy_classification.v1`.

Implementation targets:

- Extend content-profile/video-understanding prompts to emit explicit `primary_type`, `production_mode`, and tags.
- Normalize watch root and creator-card defaults into `source_context.strategy_classification`.
- Add confidence and conflict reasons when classification disagrees with user-selected controls.

Done when:

- New jobs created from upload, watch root, and remix production all carry a classification payload.
- Low-confidence classification requires strategy confirmation instead of silently choosing a production line.
- Tests prove explicit user selections are not overwritten by automatic labels.

### Phase 2: Strategy Registry Hardening

Goal: move from scattered strategy heuristics to a durable strategy registry.

Implementation targets:

- Keep `strategy_type` as the stable top-level enum.
- Add strategy profile metadata for cut policy, review policy, render validation policy, and capability defaults.
- Keep policy data in code first; only move to external config after the contract stabilizes.

Done when:

- Each strategy has a documented cut basis, enabled capability defaults, and review-gate policy.
- `resolve_editing_skill(...)` remains backward compatible.
- Existing edit-plan and local insert/audio/focus consumers use shared strategy/product-control inputs instead of re-guessing mode.

Initial code-level registry support is in place once `pipeline_plan.strategy_policy` carries each strategy's cut, review, render validation, and capability defaults. Full Phase 2 remains open until downstream edit-plan and packaging consumers stop duplicating strategy inference.

### Phase 3: Review Gate Integration

Goal: turn `pipeline_plan.review_gates` into real operator checkpoints.

Implementation targets:

- `strategy_confirmation_required`: show the chosen strategy, evidence, and candidate alternatives before edit-plan execution.
- `storyboard_review_required`: generate a storyboard artifact for script-driven or material-insert workflows.
- `timeline_preview_required`: generate a preview artifact before render for remix/avatar/multi-material workflows.

Done when:

- Gates are durable job steps or durable artifacts, not API-owned background-only state.
- Reruns preserve confirmed gate decisions until upstream evidence changes.
- Manual editor and job detail views show gate status and blocking reasons.

Initial gate-state normalization is in place once `capability_orchestration.review_gate_status` exposes required/recommended/optional gate rows and blocking gate IDs. A first artifact path is in place once `strategy_review_gates` is emitted from persisted content-profile artifact payloads. A durable confirmation path is in place once `strategy_review_gate_confirmations` can be written through `POST /jobs/{job_id}/strategy-review-gates/confirm`, merged into future gate artifacts, and ignored when the strategy evidence fingerprint changes. Operator visibility is in place once `ContentProfileReviewOut.strategy_review_gates` and the job detail / summary-review content profile section expose strategy, production mode, gate status, and a confirmation action. Initial storyboard/timeline artifacts are in place once `strategy_storyboard_review` and `strategy_timeline_preview` are persisted for required gates. Full Phase 3 remains open until those draft artifacts are backed by real media/storyboard previews and the manual-editor surface can consume the same gate contract.

### Phase 4: Production Line Execution

Goal: make strategy-selected features drive actual pipeline behavior.

Implementation targets:

- `information_density`: word-boundary smart cuts, silence/retake review, subtitle projection validation.
- `step_demonstration`: screen focus, chapter cards, operation hotspot packaging.
- `event_highlight`: highlight windows, high-energy keep preservation.
- `narrative_assembly`: script segmentation, material insert plan, storyboard, timeline preview, avatar/TTS when selected.

Done when:

- Each strategy has at least one real end-to-end sample or fixture proving the intended production line.
- Feature activation is traceable from classification tags to strategy to capability to artifact.
- No unsupported feature silently auto-applies outside its strategy.

Initial downstream consumption is in place once `downstream_context.resolved_profile.strategy_review_context` carries the latest `strategy_review_gates`, `strategy_storyboard_review`, and `strategy_timeline_preview` payloads. The pipeline/API profile selectors must merge later strategy-gate artifacts back into the resolved profile so confirmations made after content-profile generation still reach edit-plan, manual-editor, and render callers through the shared downstream profile contract. The first production consumers are in place once edit decisions persist the same context in `analysis.strategy_review_context` and render plans expose it through top-level `strategy_review_context`, `manual_editor.strategy_review_context`, and `packaging_timeline.strategy_review_context`. The first behavior-level consumer is in place once `narrative_assembly`/`material_insert_plan` timeline-preview segments are normalized as strategy insert windows and can steer local insert-slot planning without becoming a global default. Manual-editor visibility is in place once the session API exposes `strategy_review_context` and the unified timeline renders strategy-preview markers from `strategy_timeline_preview.segments`. The executable strategy fixture contract is in place once golden jobs can declare `strategy:<type>` tags and require `strategy_pipeline_coverage`, which verifies that the evaluation job emitted matching strategy evidence through content profile, strategy review gates, or render diagnostics. Completion is audited with `python scripts/verify_strategy_fixture_coverage.py <report-dir-or-batch_report.json>`, which requires all five strategy types by default and can derive coverage from `golden_case_rows.required_check_statuses` when the aggregate summary is absent. Candidate reference jobs can be proposed from existing DB content-profile artifacts with `python scripts/export_strategy_fixture_candidates.py --limit 800 --per-strategy 2`; this re-runs the current classification/orchestration policy over old profiles and emits manifest-ready `strategy:<type>` entries, but the exported rows are candidates only until the reference job is validated by a fresh golden run. The exporter also reports `real_render_ready_strategy_types` and can be run with `--require-real-render-ready` to make true render-backed candidates a machine gate, separate from replay safety. It can also write a runner-ready manifest with `--manifest-output output/test/strategy-fixture-candidates.manifest.v1.json`, so fixture agents can run selected cases without hand-copying `golden_manifest_jobs`. Candidate manifests explicitly write `enhancement_modes: []` so replay runs do not inherit stale avatar/AI/multi-platform enhancement modes from reference jobs. The candidate manifest can be expanded into a per-strategy execution plan with `uv run python scripts/build_strategy_fixture_execution_plan.py --manifest output/test/strategy-fixture-candidates.manifest.v1.json --output output/test/strategy-fixture-execution-plan.v1.json --markdown-output output/test/strategy-fixture-execution-plan.v1.md`; this emits one smoke/render command per strategy plus the ASR runtime preflight, real-render, and integration-closure verifier commands. Execution-plan rows marked `runtime_preflight_required=true` must first pass `uv run python scripts/check_strategy_fixture_runtime_preflight.py --output output/test/strategy-fixture-runtime-preflight.json`, which performs both health and `/transcribe` smoke checks because health-only probes do not prove render subtitle-alignment readiness. Execution-plan rows marked `promotion_required_for_real_closure=true` must be promoted with a `real_world_fixture` tag after validation before `scripts/verify_strategy_real_render_fixtures.py` will count them as final real-world evidence. Manifest-ready candidates must be replay-safe: the strategy-driving evidence has to live in reference-job context that the golden runner preserves, such as source path, workflow template, source-context classification, product controls, enhancement modes, packaging snapshot, or merged-source inventory. Evidence that exists only in an old `content_profile_final` artifact is reported as a candidate but is not manifest-ready. For new replay-safe fixtures, the golden manifest can use `source_paths` to create a merged multi-material job and can declare `strategy_classification`, `product_controls`, `source_context`, and `transcript_segments`; the runner writes these into content-profile source context and seeds deterministic subtitles before the pipeline rerun. The deterministic generated fixture path is `uv run python scripts/build_strategy_replay_fixture_manifest.py --output-dir output/test/strategy-replay-fixtures --force`, which creates ignored MP4 sources plus a manifest covering all five initial strategies. A verified generated replay slice is established when that manifest is run with `scripts/run_auto_edit_recovery_golden_set.py --stop-after content_profile` and the resulting report passes `scripts/verify_strategy_fixture_coverage.py`; this proves the classification-to-strategy-to-pipeline evidence chain for all five strategies without making any video-use/videocut behavior global. The generated suite now also requires `strategy_review_preview_evidence` and `strategy_review_preview_media_evidence` for `narrative_assembly`, proving that its storyboard/timeline review artifacts contain usable panels, time-anchored preview segments, readable source media, and preview ranges that fall within media duration; run `output/test/strategy-replay-golden/20260624-124208` passed 7/7 required checks with `storyboard_panels=3`, `timeline_segments=2`, `timeline_time_anchors=2`, `source_media=3`, `readable_media=3`, and `media_backed_segments=2`. Generated closure evidence is audited with `scripts/verify_strategy_integration_closure.py`, which combines the five-strategy content-profile report and the event-highlight render report, returning `generated_closure_ok=true` only when both narrative preview checks pass while withholding `completion_ready=true` unless real-world render fixtures and real-world media-backed preview validation also exist. Real-world render fixture coverage is audited separately with `scripts/verify_strategy_real_render_fixtures.py`; a case only counts when it is not tagged `generated_fixture`, is not an unpromoted `strategy_candidate`, has a render output path and positive duration, passes its required checks, and passes `strategy_pipeline_coverage`. The same real-world verifier now reports `media_backed_preview_validation`, which requires a non-generated `narrative_assembly` render fixture to pass `strategy_review_preview_media_evidence` with readable source media and media-backed preview segments. Passing generated reports to that verifier currently returns all five strategies missing, which is the intended guard against counting synthetic media as real-world closure evidence. New batch reports that include or can derive `strategy_pipeline_coverage` will fail live readiness until all five strategies are covered; `completion_ready` becomes true only when generated closure, real render coverage, and real narrative media-backed preview validation all pass. Current real-fixture closure uses `output/test/strategy-fixture-candidates.expanded.manifest.v1.json`, `output/test/strategy-fixture-candidates.promoted.manifest.v1.json`, `output/test/strategy-real-render-reference-report/batch_report.json`, and `output/test/strategy-real-narrative-render-golden/20260624-170043/batch_report.json`. The expanded execution plan at `output/test/strategy-fixture-execution-plan.expanded.v1.json` now reports `completion_ready=true`, all five `effective_real_render_ready_strategy_types`, and no `replacement_fixture_needed_strategy_types`. The initial Phase 4 real end-to-end fixture requirement is closed for the five starting strategies; remaining Phase 4 product work is about broadening manual-editor actions over storyboard/timeline structures rather than proving the strategy-selection pipeline.

### Phase 5: Render and Quality Gates

Goal: absorb video-use/videocut production correctness rules as validation policies, not global剪辑 presets.

Implementation targets:

- Common render checks: audio present, ffprobe duration/resolution, subtitle timing on output timeline.
- Strategy-gated checks: cut-boundary frame/waveform samples, storyboard/timeline preview checks, overlay/subtitle occlusion checks.
- Render debug evidence stored under existing render diagnostics paths.

Done when:

- Failed render/review gates explain which strategy rule failed.
- Narrow tests cover subtitle remap, cut-boundary policies, and strategy-gated validation.
- Batch/live readiness summaries include strategy and pipeline-plan evidence.

Initial strategy-gated render validation is in place once `production_readiness.render_output_blocking_reasons()` consumes `strategy_review_context` and blocks a `timeline_preview_required` / `check_timeline_preview_alignment` plan when `strategy_timeline_preview.segments` are missing, or a `storyboard_review_required` / `check_storyboard_alignment` plan when `strategy_storyboard_review.panels` are missing. The first render-plan overlay/subtitle occlusion preflight is in place once `check_overlay_subtitle_occlusion` requires emphasis overlays to carry a known subtitle-safe treatment, placement, or safe-zone contract before render output is accepted. The first cut-boundary readiness path is in place once `check_cut_boundaries` / `check_highlight_boundary_frames` consumes variant timeline diagnostics, accepted-cut counts, high-risk cut rows, and `boundary_keep_energy` evidence, then blocks unresolved high-risk cuts through `strategy_cut_boundary_high_risk_unresolved`. The first cut-boundary sample path is in place once render emits `strategy_cut_boundary_samples` artifact data from the packaged output video for strategies that require `check_highlight_boundary_frames`, including before/after frame grabs and a short waveform peaks JSON per sampled boundary, and readiness blocks highlight boundary cuts when no frame sample manifest is present. The first durable diagnostics path is in place once render runtime diagnostics record aggregate `strategy_render_validation` checks for render plans that carry strategy review context. Batch/live readiness visibility is in place once job audit summaries, fullchain batch diagnostics, golden-set diagnostics, live readiness checks, and detailed scorecards preserve strategy validation reason, strategy type, review-gate counts, cut-boundary evidence counts, and boundary sample counts. This gives Phase 5 a policy-driven render-readiness path without making storyboard/timeline/overlay/cut-boundary checks global. Render fixture required checks are now configured by strategy through `scripts/build_strategy_replay_fixture_manifest.py::STRATEGY_RENDER_REQUIRED_CHECKS`, so adding a future `step_demonstration` or `narrative_assembly` render gate means extending the strategy check map and its verifier instead of hard-coding case-specific behavior. A generated event-highlight render fixture is in place when `scripts/build_strategy_replay_fixture_manifest.py --include-render-required-checks` emits `strategy_boundary_samples` for the event case and `scripts/run_auto_edit_recovery_golden_set.py --case-id strategy_event_highlight_generated_gameplay --stop-after render` passes both `strategy_pipeline_coverage` and `strategy_boundary_samples`; the verified run at `output/test/strategy-replay-render-golden/20260624-130307` produced a 2.936s packaged output, `strategy_cut_boundary_samples` artifact, one waveform sample, and one frame sample from the packaged output without the previous Windows asyncpg / SQLAlchemy process-exit cleanup warning. Full Phase 5 remains open until real-world event-highlight footage proves the same sample manifest path and, where needed, pixel-level overlay/subtitle occlusion samples.

## Multi-Agent Rollout

Use sub-agents only when work can be split by ownership boundary. Do not give multiple agents overlapping edits to the same core file in the same phase.

| Agent Lane | Scope | Primary Files | Output | Verification |
| --- | --- | --- | --- | --- |
| Classifier Agent | Classification schema, prompt fields, source-context propagation | `review/content_profile*`, `review/video_understanding.py`, job creation paths | `strategy_classification.v1` appears on new jobs | content-profile and source-context regression tests |
| Strategy Agent | Strategy registry, precedence rules, product-control compatibility | `edit/strategy_profile.py`, `edit/product_controls.py`, `edit/capability_policy.py` | stable strategy selection and pipeline plan | capability/product-control tests |
| Review-Gate Agent | durable strategy/storyboard/timeline confirmation gates | `pipeline/orchestrator.py`, `pipeline/steps.py`, API schemas/routes | review gates block/unblock downstream work | step-state and API regression tests |
| Frontend Agent | operator visibility and confirmation UX | `frontend/src/features/jobs`, manual editor/job detail views | strategy evidence, classification tags, gate actions | frontend typecheck and browser smoke |
| Render-QA Agent | strategy-gated render validation and diagnostics | `media/render*`, `pipeline/quality.py`, render diagnostics scripts | reproducible QA evidence | targeted render/diagnostic tests |

Coordination rules:

- Strategy Agent owns precedence semantics. Other agents consume the shared contract.
- Classifier Agent may add new tags, but cannot change strategy priority without Strategy Agent review.
- Review-Gate and Frontend agents must agree on API shape before either side lands UI-only or backend-only behavior.
- Render-QA Agent may add validation gates, but must keep them policy-driven by `pipeline_plan`.

Current real-fixture landing plan:

| Agent Lane | Immediate Target | Closure Command |
| --- | --- | --- |
| Fixture Candidate Agent | Keep all five strategy candidates replay-safe and export a runner-ready manifest | `uv run python scripts/export_strategy_fixture_candidates.py --manifest-output output/test/strategy-fixture-candidates.manifest.v1.json` reports no `manifest_missing_strategy_types` |
| Execution Plan Agent | Convert the candidate manifest, candidate summary, failed render reports, and accepted real render reports into one command per strategy, replacement-fixture flags, reference-only evidence flags, and final verifier commands | `uv run python scripts/build_strategy_fixture_execution_plan.py --manifest output/test/strategy-fixture-candidates.manifest.v1.json --candidate-summary output/test/strategy-fixture-candidates.deep-scan.json --real-render-report <accepted-real-report> --rejection-report <failed-render-report> --output output/test/strategy-fixture-execution-plan.v1.json --markdown-output output/test/strategy-fixture-execution-plan.v1.md` |
| Runtime Preflight Agent | Prove local ASR is ready for render subtitle alignment before long real-render fixture reruns | `uv run python scripts/check_strategy_fixture_runtime_preflight.py --output output/test/strategy-fixture-runtime-preflight.json` returns `ok=true` |
| Promotion Agent | Promote only validated render-ready candidates into a manifest whose reports can count as real-world fixtures | `uv run python scripts/promote_strategy_fixture_manifest.py --manifest output/test/strategy-fixture-candidates.expanded.manifest.v1.json --strategy information_density --strategy step_demonstration --strategy event_highlight --output output/test/strategy-fixture-candidates.promoted.manifest.v1.json` adds `real_world_fixture` without skipped rows |
| Reference Evidence Agent | Convert promoted reference jobs and candidate-summary rows that already have completed render outputs into verifier-readable real fixture evidence, avoiding repeated long-source rerenders while marking non-replay-safe rows as `reference_evidence_only` | `uv run python scripts/build_strategy_real_render_reference_report.py --manifest output/test/strategy-fixture-candidates.promoted.manifest.v1.json --candidate-summary output/test/strategy-fixture-candidates.deep-scan.json --required-strategy experience_and_mood --output output/test/strategy-real-render-reference-report/batch_report.json` |
| Fixture Candidate Agent | Replace current render-unsuitable `narrative_assembly` candidate with a real fixture source that can pass render, ASR alignment, strategy evidence, and narrative media-backed preview checks | `output/test/strategy-real-narrative-render-golden/20260624-170043/batch_report.json` provides the accepted real fixture row |
| Render Fixture Agent | Rerun only non-rejected or replacement candidates through render so they produce non-generated batch rows with `strategy_pipeline_coverage` | `uv run python scripts/verify_strategy_real_render_fixtures.py --report <real-batch-report>` covers those strategies |
| Narrative Preview Agent | Ensure the replacement real `narrative_assembly` render keeps the `narrative_assembly` strategy and includes readable source media plus timeline preview segments backed by those media ranges | `media_backed_preview_validation.ok=true` in `scripts/verify_strategy_real_render_fixtures.py` |
| Closure Agent | Combine generated closure, real render coverage, and narrative media-backed preview validation into a single pass/fail status | `uv run python scripts/verify_strategy_integration_closure.py --content-profile-report output/test/strategy-replay-golden/20260624-124208/batch_report.json --event-render-report output/test/strategy-replay-render-golden/20260624-130307/batch_report.json --real-render-report output/test/strategy-real-render-reference-report/batch_report.json --real-render-report output/test/strategy-real-narrative-render-golden/20260624-170043/batch_report.json` returns `completion_ready=true` |

## Verification Matrix

| Requirement | Evidence |
| --- | --- |
| Classification tags do not override explicit user choices | `tests/test_capability_orchestrator.py`, `tests/test_product_controls.py` |
| Multi-material jobs can select assembly flow | `tests/test_content_profile_api_payloads.py` |
| Tutorial tags select step-demonstration flow | `tests/test_capability_orchestrator.py` |
| Avatar/remix tags select narrative assembly and review gates | `tests/test_capability_orchestrator.py` |
| Strategy registry policies are exposed in pipeline plans | `tests/test_capability_orchestrator.py` |
| Required review gates are normalized as blocking until confirmed | `tests/test_capability_orchestrator.py` |
| Strategy review gate status can be persisted as content-profile artifact evidence | `tests/test_content_profile_artifacts.py` |
| Strategy review gate confirmations are evidence-bound and can unblock persisted gates | `tests/test_capability_orchestrator.py`, `tests/test_content_profile_artifacts.py` |
| Strategy review gates are visible through content-profile API/frontend contract | `tests/test_content_profile_api_payloads.py`, `pnpm --dir frontend run typecheck` |
| Required storyboard/timeline gates produce durable draft artifacts | `tests/test_content_profile_artifacts.py` |
| Strategy review draft artifacts are exposed through downstream resolved profile | `tests/test_content_profile_api_payloads.py`, `tests/test_content_profile_artifacts.py` |
| Edit-plan/render consumers preserve strategy review context for manual editor and packaging | `tests/test_strategy_review_downstream_consumers.py` |
| Narrative assembly timeline previews can steer material insert-slot planning without global application | `tests/test_local_insert_plan.py` |
| Manual editor session and timeline UI expose strategy preview markers | full `tests/test_manual_editor_helpers.py`, `frontend/src/features/jobs/JobManualEditSection.timeline.test.ts`, `pnpm --dir frontend run typecheck` |
| Golden fixtures can require declared strategy production-line evidence | `docs/golden-jobs/auto-edit-recovery-golden-slice.v1.json`, `tests/test_run_auto_edit_recovery_golden_set.py`, `tests/test_verify_strategy_fixture_coverage.py` |
| Generated replay-safe strategy suite declares and verifies all five initial strategies | `scripts/build_strategy_replay_fixture_manifest.py`, `tests/test_build_strategy_replay_fixture_manifest.py`, `scripts/verify_strategy_fixture_coverage.py` |
| Narrative assembly generated fixture proves storyboard/timeline preview evidence with time anchors | `strategy_review_preview_evidence`, `scripts/run_auto_edit_recovery_golden_set.py --stop-after content_profile`, `tests/test_run_auto_edit_recovery_golden_set.py` |
| Narrative assembly generated fixture proves preview segments are backed by readable source media | `strategy_review_preview_media_evidence`, `scripts/run_auto_edit_recovery_golden_set.py --stop-after content_profile`, `tests/test_run_auto_edit_recovery_golden_set.py` |
| Generated strategy integration closure evidence is machine-auditable without claiming full completion | `scripts/verify_strategy_integration_closure.py`, `tests/test_verify_strategy_integration_closure.py` |
| Candidate export distinguishes replay-safe fixtures from true real-render-ready candidates and can write a runner-ready manifest | `scripts/export_strategy_fixture_candidates.py --manifest-output ... --require-real-render-ready`, `tests/test_export_strategy_fixture_candidates.py` |
| Candidate manifest can be split into per-strategy multi-agent execution commands; failed render reports can mark candidates as replacement-required, candidate-summary render evidence can close non-replay-safe gaps as reference-only evidence, and accepted real reports can clear old replacement flags | `scripts/build_strategy_fixture_execution_plan.py --candidate-summary ... --real-render-report ... --rejection-report ...`, `tests/test_build_strategy_fixture_execution_plan.py` |
| Real fixture render reruns have an explicit local ASR `/transcribe` runtime preflight | `scripts/check_strategy_fixture_runtime_preflight.py`, `tests/test_check_strategy_fixture_runtime_preflight.py` |
| Validated render-ready candidates can be promoted without promoting unsuitable candidates | `scripts/promote_strategy_fixture_manifest.py`, `tests/test_promote_strategy_fixture_manifest.py` |
| Real-render readiness follows completed render outputs, not only the aggregate job status | `scripts/export_strategy_fixture_candidates.py`, `tests/test_export_strategy_fixture_candidates.py` |
| Promoted reference jobs and candidate-summary rows with existing completed render outputs can be converted into real fixture batch evidence without rerendering long source media | `scripts/build_strategy_real_render_reference_report.py`, `tests/test_build_strategy_real_render_reference_report.py` |
| Candidate manifests explicitly prevent stale enhancement-mode inheritance from reference jobs | `scripts/run_auto_edit_recovery_golden_set.py`, `tests/test_run_auto_edit_recovery_golden_set.py` |
| Reference-job replay resolves legacy `jobs/...` source paths to current runtime media before preview validation | `scripts/run_auto_edit_recovery_golden_set.py`, `tests/test_run_auto_edit_recovery_golden_set.py` |
| Real-world render fixture coverage excludes generated fixtures, unpromoted strategy candidates, and reports per-strategy gaps | `scripts/verify_strategy_real_render_fixtures.py`, `tests/test_verify_strategy_real_render_fixtures.py` |
| Real-world narrative fixture proves media-backed storyboard/timeline preview validation | `media_backed_preview_validation`, `strategy_review_preview_media_evidence`, `scripts/verify_strategy_real_render_fixtures.py`, `tests/test_verify_strategy_real_render_fixtures.py` |
| Live readiness fails when declared strategy fixture coverage is incomplete | `tests/test_run_fullchain_batch.py` |
| Strategy-gated render validation blocks required timeline-preview/storyboard evidence gaps and records diagnostics | `tests/test_production_readiness.py`, `tests/test_manual_editor_helpers.py` |
| Strategy-gated overlay/subtitle occlusion preflight blocks unsafe overlay contracts | `tests/test_production_readiness.py` |
| Strategy-gated cut-boundary readiness blocks unresolved high-risk cuts and preserves evidence counts | `tests/test_production_readiness.py`, `tests/test_run_fullchain_batch.py`, `tests/test_run_auto_edit_recovery_golden_set.py` |
| Highlight boundary validation requires durable frame sample manifest evidence | `tests/test_production_readiness.py`, `tests/test_manual_editor_helpers.py`, `tests/test_run_auto_edit_recovery_golden_set.py` |
| Generated event-highlight render fixture proves strategy boundary samples on packaged output | `scripts/build_strategy_replay_fixture_manifest.py --include-render-required-checks`, `scripts/run_auto_edit_recovery_golden_set.py --case-id strategy_event_highlight_generated_gameplay --stop-after render`, `tests/test_build_strategy_replay_fixture_manifest.py`, `tests/test_run_auto_edit_recovery_golden_set.py` |
| Batch/live readiness summaries preserve strategy validation evidence | `tests/test_run_fullchain_batch.py`, `tests/test_run_auto_edit_recovery_golden_set.py`, `tests/test_build_batch_output_scorecard.py` |
| Existing content-profile video understanding still affects editing skill | `tests/test_video_understanding_downstream.py` |
| Public doc hygiene remains clean | `uv run python scripts/check_agent_docs.py` |

Current closure status: contract foundation, strategy registry, durable review-gate payloads, downstream strategy context propagation, policy-driven render readiness checks, generated replay coverage for all five initial strategies, generated narrative storyboard/timeline preview evidence with readable generated media, a generated event-highlight render fixture with packaged-output boundary samples, and a machine-readable generated-closure audit are in place. Candidate export now separates replay-safe candidates from real-render-ready candidates, can exclude failed candidates by rejection report, and writes a runner-ready manifest; the execution plan turns that manifest, candidate-summary evidence, accepted real render reports, and failed render reports into per-strategy commands, replacement-fixture flags, reference-only evidence flags, promotion commands, reference-report commands, and final verifier commands so multi-agent work can avoid rerunning known-bad candidates or long promoted source media while clearing stale replacement flags once a newer report proves closure. Runtime preflight originally exposed an ASR service blocker: compose mounted stale `C:/sample-workspace/RoughCut` model-cache paths and pointed Qwen3 ASR at dot-version ModelScope directories that are not valid inside Docker. `docker-compose.asr-matrix.yml` now uses workspace-relative cache mounts and the ModelScope `Qwen3-ASR-1___7B` / `Qwen3-ForcedAligner-0___6B` directories, `deploy/qwen3-asr/server.py` normalizes English language aliases, and the latest `output/test/strategy-fixture-runtime-preflight.json` has `ok=true`, `health.ok=true`, and `transcribe.status_code=200`. A separate replay root cause was fixed in `scripts/run_auto_edit_recovery_golden_set.py`: cloned reference jobs that stored legacy `jobs/...` source paths now resolve to `data/runtime/jobs/...`, so media-backed preview validation sees the same real source file as render. Real-render readiness now follows completed `RenderOutput` evidence rather than the aggregate job status, because cancelled reference jobs can still contain completed render outputs from earlier runs. `output/test/strategy-fixture-candidates.expanded.manifest.v1.json` is the current expanded manifest; `output/test/strategy-fixture-candidates.promoted.manifest.v1.json` promotes `information_density`, `step_demonstration`, and `event_highlight` with `real_world_fixture`. `scripts/build_strategy_real_render_reference_report.py` converts those promoted reference jobs plus the `experience_and_mood` candidate-summary render-ready row into `output/test/strategy-real-render-reference-report/batch_report.json`, marking the latter `reference_evidence_only` because it is not replay-safe manifest input. `output/test/strategy-real-narrative-fixture.manifest.v1.json` defines the real local multi-material `narrative_assembly` fixture from short Bluey remix source clips, and `output/test/strategy-real-narrative-render-golden/20260624-170043/batch_report.json` renders it with `strategy_pipeline_coverage`, `strategy_review_preview_evidence`, and `strategy_review_preview_media_evidence` all passing. Two render-tail root causes surfaced and were fixed: short-sample render ASR alignment now allows a single isolated bad event when drift and local-cluster gates pass, and final variant SRT sidecars are bounded to the probed rendered duration before sync checks. `scripts/verify_strategy_real_render_fixtures.py --report output/test/strategy-real-render-reference-report/batch_report.json --report output/test/strategy-real-narrative-render-golden/20260624-170043/batch_report.json` now covers all five strategies and reports `media_backed_preview_validation.ok=true`. `scripts/verify_strategy_integration_closure.py --content-profile-report output/test/strategy-replay-golden/20260624-124208/batch_report.json --event-render-report output/test/strategy-replay-render-golden/20260624-130307/batch_report.json --real-render-report output/test/strategy-real-render-reference-report/batch_report.json --real-render-report output/test/strategy-real-narrative-render-golden/20260624-170043/batch_report.json` returns `completion_ready=true` with no remaining open items. Candidate manifests explicitly freeze enhancement modes to avoid stale reference-job avatar/AI side effects, and real-world verification rejects unpromoted `strategy_candidate` rows.

## Guardrails

- Do not make videocut口播 assumptions global defaults.
- Do not add UI-only confirmation state; confirmed decisions must be durable.
- Do not let low-confidence classification silently trigger a heavy production line.
- Do not duplicate strategy inference in downstream consumers.
- Do not replace render validation with broad smoke tests; each gate needs evidence tied to the policy it enforces.
