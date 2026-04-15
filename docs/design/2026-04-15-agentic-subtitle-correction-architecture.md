# 2026-04-15 Agentic Subtitle Correction Architecture

## 定位

这是一份当前已落地链路的 contract 文档，不是继续扩散补丁的提案草图。

它要回答四个固定问题：

1. 现在的 pipeline 顺序是什么。
2. 每个 step 的职责边界是什么。
3. 关键 artifact 的输入、输出和 blocking 语义是什么。
4. rerun 应该从哪里开始，哪些步骤不能被越过。

凡是会影响这四件事的实现变更，都必须同步更新这份文档和附录。

## 当前主链路

当前已落地的主链路顺序如下：

`probe -> extract_audio -> transcribe -> subtitle_postprocess -> subtitle_term_resolution -> subtitle_consistency_review -> glossary_review -> subtitle_translation -> content_profile -> summary_review -> ai_director -> avatar_commentary -> edit_plan -> render -> final_review -> platform_package`

约束：

1. `subtitle_postprocess` 是字幕结构的起点，不是术语纠偏终点。
2. `subtitle_term_resolution` 是术语纠偏的主入口，不再由后续 step 兜底。
3. `subtitle_consistency_review` 是审校层，不产出新事实，只产出一致性判断。
4. `glossary_review` 已降级为回写和轻量维护层，不能重新承担主纠偏职责。
5. `content_profile` 是内容理解和下游画像的主入口，负责把结果收敛成可下游消费的 profile。
6. `summary_review` 是内容画像的人审边界，不是字幕链的第二套纠偏入口。
7. `final_review` 和 `platform_package` 只消费已经收敛的下游结果，不回头重定义前面步骤的职责。

## 责任边界

### `subtitle_postprocess`

职责：

- 做句界恢复、基础清理、时间轴友好分段。
- 产出首版字幕和字幕质量报告。

不能做的事：

- 不能替代术语纠偏。
- 不能把内容理解、身份确认、摘要判断塞进来。
- 不能把“看起来更像成片”的修饰当作结构修正。

### `subtitle_term_resolution`

职责：

- 基于字幕、文件名、内容画像、术语记忆和上下文，生成术语纠偏提案。
- 输出 `subtitle_term_resolution_patch`，给后续审校和回写使用。

不能做的事：

- 不能同时承担质量门禁和内容摘要判断。
- 不能把“待确认候选”伪装成最终事实。

### `subtitle_consistency_review`

职责：

- 检查字幕与文件名、OCR、摘要、同组上下文之间的一致性。
- 汇总冲突、告警和阻断原因。

不能做的事：

- 不能生成新的术语纠偏候选。
- 不能替代 `subtitle_term_resolution` 的主职责。

### `glossary_review`

职责：

- 复用已有术语纠偏结果。
- 做轻量回写、记忆维护和保守润色。
- 为下游提供更稳定的术语记忆反馈。

不能做的事：

- 不能重新成为主纠偏入口。
- 不能覆盖 `subtitle_term_resolution` 和 `subtitle_consistency_review` 的判断。

### `subtitle_translation`

职责：

- 做字幕翻译或语言投影。
- 以已稳定的字幕为输入，不反向修改上游事实。

不能做的事：

- 不能把翻译阶段的改写回灌成字幕事实修正。

### `content_profile`

职责：

- 消费已审过的字幕和一致性结果，生成内容画像。
- 产出 `content_profile_draft`、`content_profile_final` 和 `downstream_context` 的基础来源。
- 负责把下游需要的主体、主题、摘要、封面、搜索词等信息收束成结构化结果。

不能做的事：

- 不能把字幕错误“顺手修掉”后当作内容理解结果。
- 不能在没有显式反馈的情况下越权重写字幕链。

### `summary_review`

职责：

- 作为 `content_profile` 的唯一人审边界。
- 接收 `content_profile_draft`、`subtitle_quality_report`、`subtitle_consistency_report` 和必要的上下文。
- 决定 draft 是继续确认、保持待审，还是转为 final。

不能做的事：

- 不能把字幕审校问题伪装成内容摘要问题。
- 不能在 review 里重新发明字幕纠偏策略。

### `ai_director`、`avatar_commentary`、`edit_plan`、`render`、`final_review`、`platform_package`

职责：

- 只消费已经收敛的 content profile 和 downstream context。
- 保持下游文案、导演、剪辑、渲染、发布的一致性。

不能做的事：

- 不能倒灌回去改变前面字幕和审校的 contract。

## Artifact Contract 概览

| Artifact | 主要生产者 | 主要消费者 | contract 角色 |
|---|---|---|---|
| `subtitle_quality_report` | `subtitle_postprocess` | `subtitle_consistency_review`、`content_profile`、`summary_review`、质量门禁 | 字幕健康度和基础阻断信号 |
| `subtitle_term_resolution_patch` | `subtitle_term_resolution` | `subtitle_consistency_review`、`glossary_review`、`content_profile`、人审链路 | 术语纠偏提案和证据载体 |
| `subtitle_consistency_report` | `subtitle_consistency_review` | `content_profile`、`summary_review`、质量门禁 | 一致性冲突和阻断信号 |
| `content_profile_draft` | `content_profile` | `summary_review`、`downstream_context`、下游导演/剪辑/发布 | 待确认内容画像 |
| `downstream_context` | `content_profile` / `summary_review` | `ai_director`、`avatar_commentary`、`edit_plan`、`render`、`final_review`、`platform_package` | 下游统一消费的已收敛画像 |

详情字段见附录：[2026-04-15-agentic-subtitle-correction-artifact-contracts.md](./2026-04-15-agentic-subtitle-correction-artifact-contracts.md)

## Review 边界

当前只保留两类 review 边界：

### `subtitle_review`

覆盖：

- `subtitle_quality_report`
- `subtitle_term_resolution_patch`
- `subtitle_consistency_report`

语义：

- 处理字幕结构、术语候选和一致性阻断。
- 结果可以阻断后续自动放行，但不能改写成内容摘要问题。

### `summary_review`

覆盖：

- `content_profile_draft`
- `content_profile_final`
- `downstream_context`

语义：

- 处理内容画像是否足够稳定、是否需要人工确认。
- 如果字幕门禁阻断，仍然留在这条人审链里，但阻断原因必须保持为字幕问题，不得改写成摘要本身的问题。

边界规则：

1. `subtitle_review` 的问题可以阻断 `summary_review` 的自动确认。
2. `summary_review` 只能确认或拒绝内容画像，不得重置字幕审校结论。
3. 任何“字幕问题”和“摘要问题”都必须保留各自的 reason，不允许互相覆盖。

## Rerun 语义

rerun 只从责任最小且足够早的步骤开始，不从更后面的步骤补救前面的错误。

| 问题类型 | 重新起点 | 目的 |
|---|---|---|
| 句界、残句、短碎句、基础脏文本 | `subtitle_postprocess` | 重建字幕结构和基础质量报告 |
| 术语候选、品牌型号、显性纠错提案 | `subtitle_term_resolution` | 重建术语纠偏提案和 patch |
| 一致性冲突、摘要/文件名不一致 | `subtitle_consistency_review` | 重建审校结论和阻断原因 |
| 内容主题、主体、摘要、封面、搜索词变化 | `content_profile` | 重建内容画像和下游 context |
| 人工确认状态变化 | `summary_review` | 更新 review 状态和 final/profile 选择 |

rerun 规则：

1. 从某一步 rerun 时，必须默认重跑其后续依赖链。
2. 只有上游事实变化时，才允许回写到更后面的 artifact。
3. 不能用下游 step 的结果“倒补”上游事实缺口。
4. `downstream_context` 始终应当视为 `content_profile` 的派生结果，而不是独立事实源。

## 不可回退约束

以下行为不应再被重新引入：

1. `content_profile` 再次直接充当字幕纠偏主入口。
2. `glossary_review` 再次承担主纠偏职责。
3. 一个 review 同时覆盖字幕审校和内容摘要，导致 reason 被覆盖。
4. `downstream_context` 被当作独立事实源使用，而不是派生结果。
5. rerun 从过晚的步骤开始，导致上游坏证据不被重建。
6. artifact 继续只靠临时 JSON blob 约定，而没有明确 contract 语义。

## 维护规则

1. 新增或修改 artifact 字段时，先更新附录，再改实现。
2. 新增 step 或调整 step 顺序时，必须同时更新这份主文档和 `INDEX.md`。
3. 如果某个字段已经不再被消费，就从 contract 中删除，不要保留“历史兼容”式模糊描述。
4. 这份文档的职责是约束实现边界，不是记录临时实验。

