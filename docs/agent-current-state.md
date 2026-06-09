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
- Tighten smart-cut pause overlap filtering to consume the spoken-ASR surface first (`transcript_text_raw`) so corrected display text can’t hide timing-aware gating.

## Resolved Decisions

- The recovery direction is "one stage, one responsibility"; no stage may silently re-correct, re-split, or re-delete outputs owned by an earlier stage.
- `ASR evidence`, `canonical transcript`, `subtitle projection`, `edit candidates`, and `final keep/remove decisions` are separate artifacts and must stay separate.
- Subtitle segmentation is a single shared automatic stage. Manual editing may inspect and override the result, but does not become the primary segmentation engine.
- Automatic editing and manual adjustment are two execution modes over the same contracts. Manual mode is a review/refine phase, not a parallel hidden pipeline.
- Current system scoring should be judged on production usefulness, not isolated model quality. The latest real-task evaluation baseline is roughly `62/100` overall and `~72/100` if manual-editor production usability is excluded.
- `manual-editor/apply` now avoids silent subtitle re-write during validation (only diagnostics remain), reducing untraceable timing/text edits introduced at submit time.
- `_validated_subtitle_projection_for_timeline` now has an explicit `apply_repair` switch; `tests/test_pipeline_projection_validation_contracts.py` guards contract: no repair means no content mutation.
- `build_cut_analysis_payload` now preserves smart-cut candidate metadata（`rule_id/risk_level/match_surface`）when cached smart candidates are rehydrated, including timing jitter and filler-mode drift, so audit logs can trace deletions across recomputation.
- Projection refresh no longer participates in a second hidden segmentation pass: `canonical_refresh` is now the only automatic projection candidate once canonical segmentation exists, and the legacy local hybrid path has been reduced to a non-authoritative pass-through helper.

## Do Not Reopen

- Do not move active task state back into `AGENTS.md`.
- Do not let display subtitle text become the fact layer for timing or edit decisions again.
- Do not allow subtitle cleanup, filler matching, segmentation, and edit removal to run in overlapping hidden stages.
- Do not treat auto-cut compression ratio alone as success; false deletion rate and sentence naturalness are co-equal quality gates.
- Do not claim the chain is recovered until real jobs can complete manual-editor load, automatic edit generation, and render review without hidden fallback corruption.

## Next Concrete Action

1. Continue `T1.1` migration and replace remaining mixed `text_final/text_norm/text_raw` consumers in auto-edit shared utilities with explicit `raw/canonical/display` surface helpers.
2. Start `T1.2` residual path audit and list every remaining re-segmentation or display-layer rewrite path outside `Subtitle Segmentation`.
3. Extend golden-set replay to include a surface-contract checkpoint so display suppression and rule surfaces can be diffed on fixed real jobs.

## Latest Certification

- 2026-06-09: `T1.2` 主链收口已通过一轮更宽回归复验。manual-editor editing payload 与 display payload 的职责重新分开：`_manual_editor_subtitle_payload(...)` 现使用独立 editable-final helper，保留 standalone filler 等完整编辑文本；而 display-only helper 继续用于 display surface contract，不再互相污染。`_manual_editor_subtitle_items_from_editorial(...)` 也恢复为“缺 raw 不反灌 raw，norm/final 依展示文本规范化”的旧合同，避免 editorial projection item 在 render 前被误写成三层同文案。同时，`tests/test_manual_editor_helpers.py` 中依赖 projection annotation repair 的用例已改为显式声明 `apply_annotation_repair=True`，与新的 validator 合同保持一致。验证：`tests/test_manual_editor_helpers.py`、`tests/test_manual_editor_session_regressions.py`、`tests/test_pipeline_projection_validation_contracts.py`、`tests/test_subtitle_timeline_remap.py`、`tests/test_subtitle_surface_contracts.py` 在 `PYTHONPATH=src` 下全量通过（`287` 项）。
- 2026-06-09: `T1.2` 再次收掉 manual-editor 会话加载里的隐藏投影切换。此前 `_build_manual_editor_session(...)` 即使不直接展示 validator 返回值，仍会把 `validate_projected_subtitles_against_source(...)` 产生的 repair/fallback 中间结果喂给 source fallback 判定，形成“校验顺手改写，改写再参与决策”的暗链。现在会话加载改为：validator 只做 non-mutating diagnostics（`fallback_source_subtitles=None`, `apply_annotation_repair=False`），`source_projection_fallback_applied` 仅基于原始 `projected_subtitles` 走显式 fallback 分支。验证：新增 `tests/test_manual_editor_session_regressions.py::test_manual_editor_session_validation_stays_non_mutating_and_fallback_explicit`，并联同 `tests/test_manual_editor_session_regressions.py`、`tests/test_pipeline_projection_validation_contracts.py`、`tests/test_subtitle_timeline_remap.py`、`tests/test_subtitle_surface_contracts.py` 在 `PYTHONPATH=src` 下通过（`40` 项）。
- 2026-06-09: `T1.2` 继续消除默认副作用链。`validate_projected_subtitles_against_source(...)` 现在新增显式 `apply_annotation_repair` 开关，默认只做 source/projection 校验与诊断，不再默认执行 `_repair_projection_text_drift_from_span_fallback(...)` 去改写字幕；`pipeline/steps.py::_validated_subtitle_projection_for_timeline(...)` 仅在 `apply_repair=True` 时才把 annotation repair 透传给 validator。合同回归 `tests/test_pipeline_projection_validation_contracts.py` 已新增“默认非变异 / 显式才修复” 两条验证，并联同 `tests/test_subtitle_timeline_remap.py`、`tests/test_subtitle_surface_contracts.py` 在 `PYTHONPATH=src` 下通过（`34` 项）。
- 2026-06-09: `T1.1/T1.2` 继续向主链深处收口。`api/jobs.py` 的 `_manual_editor_final_subtitle_text/_manual_editor_display_source_text/_manual_editor_timing_text` 已改为走 `subtitle_display_rule_text(...)`，不再在 manual-editor 公共 helper 内部把 `text_final=""` 的 display-suppressed 行回填成 `text_norm/text_raw`。`pipeline/steps.py` 新增对象型 subtitle surface adapter，`_apply_subtitle_semantic_cleanup`、`_build_projection_entries_from_subtitle_items`、`_projection_item_text`、`_projection_material_text` 不再对 ORM/namespace 条目维护第二套宽松 fallback。`media/subtitle_spans.py`、`media/subtitles.py`、`media/subtitle_fingerprint.py` 与 `review/subtitle_quality.py` 的共享 helper 也已迁到 surface contract，其中 `remap_subtitles_to_timeline(...)` 不再把 fragment 文本统一回写到 `text_raw/text_norm/text_final`，而是分别保留 raw/canonical/display 三层 surface。验证：`tests/test_subtitle_timeline_remap.py` 与 `tests/test_subtitle_surface_contracts.py` 在 `PYTHONPATH=src` 下全量通过（`29` 项）；配套 `tests/test_manual_editor_helpers.py -k "surface or split_long_rows_expose"` 通过（`6` 项）。
- 2026-06-09: `T1.1` 已开始实质落地到共享抽象层。`src/roughcut/edit/subtitle_surfaces.py` 现在对 `raw/canonical/display` 三层 surface 使用独立优先级，不再共享同一条宽松 fallback 链；其中 display 额外尊重显式 `text_final="" + display_suppressed_reason`，避免被 canonical/raw 反向复活。`timeline_contract.py`、`render_plan.py`、`pipeline/steps.py`、`api/jobs.py`、`media/subtitle_projection_validation.py`、`media/output.py`、`media/render.py`、`creative/director.py` 与 `creative/avatar.py` 的高影响公共读取/装配点已迁到 surface helper。新增 `tests/test_subtitle_surface_contracts.py`，并联同 `tests/test_manual_editor_helpers.py -k surface` 在 `PYTHONPATH=src` 下通过（`13` 项），作为主链 surface ownership 的第一批合同回归。
- 2026-06-09: `build_cut_analysis_payload` smart-cut metadata replay regression fixed and certified via `tests/test_manual_editor_helpers.py` (`12` matching tests in cut-analysis path; `244` tests for manual editor helper file full pass). Added `tests/test_manual_editor_session_regressions.py` with three real-job session/load-path cases (`3` passing) and kept it as the first step in live-job-like regression evidence collection. Strengthened `test_manual_editor_session_fallbacks_to_source_when_projection_is_suspicious` to assert fallback is actually applied and fixed `src/roughcut/api/jobs.py` so `source_projection_fallback_applied=True` now rewrites projected subtitles when source fallback rows exist.
- 2026-06-09: `T0.1` 增加了退化回归：`tests/test_manual_editor_session_regressions.py` 新增两个负载场景（缺失 render_plan、异常 cut_analysis artifact），与已有场景共 `5` 个用例在 `PYTHONPATH=src` 下通过。该层面确认 `/manual-editor/readiness` 与 `/manual-editor` 对降级输入不再抛 `500`。
- 2026-06-09: `T0.2` 开始合同化落地：`subtitle_projection_validation` 现在显式返回 `changed/input_count/output_count`；`pipeline/steps.py` 的 projection repair 摘要会写入 `decision.analysis["subtitle_projection_repair"]` 与 `render_plan["subtitle_projection_repair"]`；`manual-editor/apply` 也会把同类诊断写入 editorial analysis，不再只留 debug log。相关合同回归 `tests/test_pipeline_projection_validation_contracts.py`、`tests/test_edit_plan_gate_analysis.py` 通过，联同 manual editor 相关回归共 `265` 项在 `PYTHONPATH=src` 下通过。
- 2026-06-09: `T0.2` 继续收口 `run_render` 与 `run_platform_package`：`run_render` 的 render 输出增加 `quality_checks["subtitle_projection_repair"]`；`run_platform_package` 的步骤 cache 增加 `subtitle_projection_repair`，并把 `_validated_subtitle_projection_for_timeline` 的隐式匹配改为可观测摘要。
- 2026-06-09: `T0.2` 继续收口完成度提升：`platform_packaging_md` 的 markdown payload 也加入 `subtitle_projection_repair` 摘要，追踪链路从自动剪辑、渲染到平台文案都可回放。
- 2026-06-09: `T0.3` 继续收尾来源层可观测性：`ManualEditorRuleSegmentOut` 缺失 `match_surface_layer` 的回退映射已补齐（filler/catchphrase/silence 默认 raw，low_signal_subtail 默认 canonical），并通过 `tests/test_manual_editor_helpers.py::test_manual_editor_rule_segments_expose_provenance_fields` 与全量 `tests/test_manual_editor_helpers.py`、`tests/test_final_subtitle_filler_cleanup.py`、`tests/test_subtitle_*` 回归。前端已补齐类型映射并通过 `pnpm run typecheck` 与 `JobManualEditSection.timeline.test.ts` 全量通过。
- 2026-06-09: `T1.2/T1.3` 开始执行根因收口：`pipeline/steps.py` 已停用 projection 阶段的 hidden local hybrid resegmentation，`_build_projection_candidate_pool(...)` 不再把 `canonical_local_hybrid` 作为自动链候选，`_select_projection_candidate(...)` 也会在 canonical refresh 存在时强制只从该权威候选集合中选择。`_build_local_hybrid_projection_entries(...)` 降级为 contract-preserving pass-through，避免遗留调用重新引入第二切分阶段。验证：`tests/test_manual_editor_helpers.py tests/test_canonical_projection_guards.py tests/test_pipeline_projection_validation_contracts.py` 共 `255` 项通过。
- 2026-06-09: `T0.4` 开始落地真实任务回归入口：新增 `scripts/run_auto_edit_recovery_golden_set.py`，支持从 `reference_job_id` 克隆真实 job 复跑，输出 `batch_report`、`detailed_output_scorecard` 和失败样本 `audit_pack`；首个提交的 golden slice 在 `docs/golden-jobs/auto-edit-recovery-golden-slice.v1.json`，当前先绑定两条 manual-editor/projection 问题锚点。合同回归 `tests/test_run_auto_edit_recovery_golden_set.py` 通过。
- 2026-06-09: `T0.4` 继续推进：`auto-edit-recovery-golden-slice.v1.json` 扩容到 `9` 条真实任务锚点，覆盖 `maxace`、`heygem`、`noc_mt34` 与 `EDC` 场景，支撑回放稳定性与误删回归定位。
- 2026-06-09: `T0.4` 冒烟完成：使用 `docs/golden-jobs/auto-edit-recovery-golden-slice.v1.json` 对两条真实 job 锚点执行 `--stop-after content_profile`，成功落出 `batch_report.json/md`、`detailed_output_scorecard.json/md`、`golden_set_summary.md` 和 `audit_packs/*`。过程中发现新脚本复用 `run_fullchain_batch.render_markdown()` 时缺少 `summary` 基础字段，已修复根因并通过真实冒烟重验。两次 smoke 产生的 4 个 clone job 已全部显式 `cancelled` 回收，未保留运行态污染。
- 2026-06-09: `T0.4` 残余风险继续收口：定位到 `scripts/run_fullchain_batch.py::run_job(...)` 在 `stop_after` 触发 `partial` 时没有把 job 收成终态，第一坏层在共享 batch runner 而不是 golden 脚本本身。已新增 `stop_job_after_requested_step(...)`，会把剩余步骤标记为 `skipped/cancelled`，并将 job 收为 terminal `cancelled`，同时保留已生成工件用于评分。回归 `tests/test_run_fullchain_batch.py` 通过；真实 smoke 复验后，新 clone job 不再残留 `processing`。

## Verification

- The new design doc must name each pipeline stage, its inputs, outputs, and forbidden side effects.
- The task list must be dependency-ordered and executable without replaying prior chat history.
- The current-state file must point future agents to the active recovery docs instead of stale publication-only state.
