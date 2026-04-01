# RoughCut Type/Domain Taxonomy Cleanup Design

## Goal

把 RoughCut 的语义分类严格收口到两条轴：

- `video_type`：视频形式，影响剪辑策略与执行模板
- `content_domain`：内容领域，影响词汇校对、热词提示、人工记忆范围、包装风格偏置

## Current Problems

- `workflow_template`、`video_type`、`subject_domain` 在多处被混用。
- `digital` 这种混合领域把 `AI` 和 `数码科技` 强行并到一起，导致词汇校对范围过宽。
- 旧信号如 `ai / coding / software` 仍有价值，但当前层级不清晰，既像领域又像信号源。
- 模板名虽然已不再直接决定 `subject_domain`，但领域命名仍然不够稳定，外显口径和内部信号层不一致。

## Target Taxonomy

### Video Type

仅描述视频形式，例如：

- `unboxing`
- `review`
- `tutorial`
- `news`
- `commentary`
- `vlog`

### Content Domain

仅描述内容领域，例如：

- `edc`
- `outdoor`
- `tech`
- `ai`
- `functional`
- `tools`
- `food`
- `travel`
- `finance`
- `news`
- `sports`

其中：

- `tech` 表示数码科技/消费电子内容，例如手机、电脑、耳机、相机、芯片、续航、屏幕。
- `ai` 表示 AI 工具、AI 教程、AI 新闻、AI 开源项目、模型推理、工作流等内容。

## Normalization Rules

- `digital` 不再作为最终 `content_domain`。
- `tech` 是 `数码科技` 的最终 canonical key。
- 旧值 `digital` 向后兼容归一到 `tech`。
- `software`、`coding` 保留为内部信号源，但最终归一到 `ai`。
- `ai` 保持为独立最终领域，不再并入 `tech`。
- `gear` 保留为内部宽信号，但最终归一到 `edc`。
- `bag`、`functional_wear` 最终归一到 `functional`。

## Behavioral Rules

- `workflow_template` 不能直接推出 `content_domain`。
- `video_type` 不能冒充 `content_domain`。
- `content_domain` 负责：
  - glossary pack 选择
  - subtitle/transcription review memory 过滤
  - confirmed entity memory 的作用范围
  - packaging style 的领域偏置
- `video_type` 负责：
  - 剪辑手法
  - 节奏与镜头组织
  - 包装模板与产出策略

## Scope

本轮只收口 taxonomy、canonical domain 和相关词汇/记忆入口，不改动已有工作流模板集合，也不做新的 UI 交互设计。

## Acceptance Criteria

- 对外可见 builtin glossary packs 不再出现 `digital`，改为独立的 `tech` 和 `ai`。
- `detect_glossary_domains()` 能区分：
  - 手机/电脑/耳机类内容 -> `tech`
  - 工作流/模型/ComfyUI/节点编排类内容 -> `ai`
- 旧输入 `digital`、`software`、`coding` 仍能被识别，但最终 canonical 化到正确领域。
- memory domain matching 不再把 `tech` 和 `ai` 合并成同一个领域。
