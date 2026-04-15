# 2026-04-15 Agentic Subtitle Correction Artifact Contracts

## 说明

这是主文档的附录，只记录当前已落地 artifact 的结构边界。

原则：

1. 字段名尽量稳定。
2. `blocking` 只能表示是否阻断自动确认或下游放行，不等于“结果差”。
3. `warning_reasons` 只提示风险，不应阻断主链路。
4. 所有 artifact 都允许扩展字段，但不能破坏现有必填字段语义。

## `subtitle_quality_report`

生产者：

- `subtitle_postprocess`

消费者：

- `subtitle_consistency_review`
- `content_profile`
- `summary_review`
- 质量门禁与 rerun 策略

必备字段：

- `score`
- `blocking`
- `blocking_reasons`
- `warning_reasons`
- `metrics`
- `source_name`
- `subject`
- `summary`

`metrics` 约定字段：

- `subtitle_count`
- `bad_term_total`
- `bad_term_counts`
- `filler_count`
- `low_signal_count`
- `short_fragment_count`
- `short_fragment_rate`
- `filler_rate`
- `low_signal_rate`
- `summary_generic_hits`
- `identity_expected`
- `identity_missing`

阻断语义：

- 热词/型号错词残留
- 短碎句率过高
- 摘要模板化命中
- 摘要/主体未保住文件名中的品牌型号

## `subtitle_term_resolution_patch`

生产者：

- `subtitle_term_resolution`

消费者：

- `subtitle_consistency_review`
- `glossary_review`
- `content_profile`
- subtitle 人审链路

必备字段：

- `source_name`
- `candidate_terms`
- `patches`
- `evidence`
- `confidence`
- `scope`
- `blocking`
- `metrics`

`patches` 每项约定字段：

- `subtitle_item_id`
- `original_span`
- `suggested_span`
- `change_type`
- `confidence`
- `source`
- `auto_applied`
- `human_decision`

`metrics` 约定字段：

- `patch_count`
- `auto_applied_count`
- `accepted_count`
- `pending_count`

阻断语义：

- 只要存在未决候选，就应视为字幕审校未完成。

## `subtitle_consistency_report`

生产者：

- `subtitle_consistency_review`

消费者：

- `content_profile`
- `summary_review`
- 质量门禁与 rerun 策略

必备字段：

- `source_name`
- `score`
- `blocking`
- `blocking_reasons`
- `warning_reasons`
- `conflicts`
- `metrics`

`conflicts` 约定分组：

- `subtitle_vs_filename`
- `subtitle_vs_ocr`
- `subtitle_vs_summary`
- `group_context_conflicts`

`metrics` 约定字段：

- `subtitle_count`
- `pending_patch_count`
- `resolved_patch_count`
- `auto_applied_patch_count`
- `quality_blocking_reason_count`

阻断语义：

- 待确认的术语候选
- 与文件名或主体线索不一致
- 字幕质量门禁已经阻断

## `content_profile_draft`

生产者：

- `content_profile`

消费者：

- `summary_review`
- `downstream_context`
- 下游导演、数字人、剪辑、发布步骤

contract 角色：

- 这是“待确认内容画像”。
- 它可以带有 review 状态、字幕门禁信息和人工反馈，但它还不是最终下游 truth。

应保留的核心信息：

- 主体字段
- 主题字段
- 摘要字段
- 封面/标题/搜索词等下游字段
- review 相关状态
- `subtitle_quality_report`
- `subtitle_consistency_report`
- 人工反馈与解析反馈

不可混淆的点：

- `content_profile_draft` 不是纯摘要文本。
- `content_profile_draft` 也不是字幕审校 artifact 的替代品。

## `content_profile_final`

生产者：

- `summary_review` 或 `content_profile` 的最终确认分支

消费者：

- `downstream_context`
- 下游导演、数字人、剪辑、发布步骤

contract 角色：

- 这是确认后的内容画像。
- 如果存在 `downstream_context`，下游优先消费 `downstream_context`，而不是直接消费 `content_profile_final`。

## `downstream_context`

生产者：

- `content_profile`
- `summary_review`

消费者：

- `ai_director`
- `avatar_commentary`
- `edit_plan`
- `render`
- `final_review`
- `platform_package`

必备字段：

- `resolved_profile`
- `field_sources`
- `manual_review_applied`
- `research_applied`
- `generated_at`

`resolved_profile` 的语义：

- 这是下游统一消费的已收敛画像。
- 手工确认字段优先于基线字段。
- 研究证据只作为补充来源，不应覆盖明确的人审结论。

`field_sources` 的语义：

- 标记每个已跟踪字段来自 `base_profile` 还是 `manual_review`。

## `subtitle_review` 与 `summary_review` 的字段映射

### `subtitle_review`

显示对象：

- `subtitle_quality_report`
- `subtitle_term_resolution_patch`
- `subtitle_consistency_report`

### `summary_review`

显示对象：

- `content_profile_draft`
- `content_profile_final`
- `downstream_context`

这个映射不能被打散。任何把字幕问题直接伪装成 summary 问题的实现，都属于 contract 退化。

## `job_activity.decisions` 的 subtitle action contract

字幕相关 decision 不再只返回 `summary/detail` 文案。现在要求同时提供结构化动作字段，供 Web、Telegram 和后续自动化统一消费。

适用 kind：

- `subtitle_quality`
- `subtitle_term_resolution`
- `subtitle_consistency_review`
- `subtitle_review`

约定字段：

- `blocking`
- `review_route`
- `review_label`
- `recommended_action`
- `rerun_start_step`
- `rerun_steps`
- `issue_codes`

字段语义：

- `blocking`
  表示该 decision 是否阻断当前链路继续自动放行。
- `review_route`
  当前只允许 `subtitle_review` 或空值。为 `subtitle_review` 时，前端和 Telegram 都应引导用户先处理字幕复核，而不是继续 summary/final review。
- `review_label`
  给人工入口的短标签，例如“字幕质量复核”“术语候选确认”“一致性冲突复核”。
- `recommended_action`
  面向用户的直接处理动作说明，必须能单独阅读，不依赖额外上下文。
- `rerun_start_step`
  如果用户决定自动回退，建议从哪个 step 开始。
- `rerun_steps`
  展开的推荐重跑链，用于展示和后续自动化，不应再由调用方临时拼接。
- `issue_codes`
  稳定的原因码，供质量系统、筛选器和后续统计消费。

当前映射规则：

- `subtitle_quality_blocking` / `subtitle_identity_missing`
  `review_route=subtitle_review`
  `rerun_start_step=subtitle_postprocess`
- `subtitle_terms_pending`
  `review_route=subtitle_review`
  `rerun_start_step=subtitle_term_resolution` 或 `glossary_review`
- `subtitle_consistency_blocking`
  `review_route=subtitle_review`
  `rerun_start_step=subtitle_consistency_review`
- warning 类问题
  可以保留 `review_route=null`，但仍应提供 `recommended_action` 和 rerun 提示

## `job.review_label / review_detail` 的 subtitle gate 约束

当任务仍停在 `summary_review`，但阻断原因实际上来自字幕链时：

- `review_step` 仍保留 `summary_review`
- `review_label` 必须降到 `字幕复核`
- `review_detail` 必须优先展示 subtitle action 的 `recommended_action`

这条约束用于避免 UI 继续把字幕阻断误展示为“等待确认摘要”。
