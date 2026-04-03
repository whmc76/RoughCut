# Downstream Context Propagation Design

## Goal

让 RoughCut 把“综合调研结果”和“人工校对结果”沉淀成统一的下游决议上下文，并把这份上下文广泛应用到所有后续环节，而不是只影响字幕、标题或局部剪辑逻辑。

## Problem

当前系统对人工校对和调研结果的利用是不均匀的：

- `platform_package` 已能部分读取 `resolved_review_user_feedback`
- `content_profile.evidence` 会影响事实核验，但没有被统一建模为后续文案与决策输入
- `ai_director`、`avatar_commentary`、`edit_plan`、`render`、`final_review` 仍主要直接消费原始 `content_profile`

这会导致同一条任务里，下游不同步骤可能基于不同版本的主体判断、主题定位和文案方向继续工作。

## Requirements

### Functional

1. 生成一份统一的下游上下文 artifact，表达“人工校对 > 综合调研 > 原始自动推断”的决议结果。
2. 后续步骤优先读取这份上下文，而不是各自直接拼接 `content_profile`。
3. 这份上下文至少覆盖：
   - `ai_director`
   - `avatar_commentary`
   - `edit_plan`
   - `render`
   - `final_review`
   - `platform_package`
4. 下游上下文要保留来源痕迹，便于审计：
   - 哪些字段来自人工校对
   - 哪些字段来自综合调研
   - 哪些字段仍回退到自动推断
5. 现有消费者尽量继续使用熟悉的 profile 形状，避免大面积重写。

### Non-functional

1. 改动要最小化，不引入多套并行优先级逻辑。
2. 回退路径要安全：没有下游上下文 artifact 时，现有流程仍可继续运行。
3. 测试要覆盖多条下游链路，而不是只测 `platform_package`。

## Recommended Approach

新增 `downstream_context` 统一 artifact，并提供集中式解析函数：

- 输入：`content_profile_*` artifact
- 输出：
  - 一份“可直接给下游消费者使用”的 resolved profile
  - 一份附带来源元数据的 `downstream_context`

核心策略：

- 人工校对字段覆盖原始 profile 中对应字段
- 综合调研保留为事实与文案定位约束，并在下游上下文中显式标记 `research_applied`
- 对下游消费者暴露与现有 `content_profile` 尽量一致的字段集合，减少适配成本

## Data Model

新增 artifact 类型：`downstream_context`

建议结构：

```json
{
  "resolved_profile": {
    "subject_brand": "",
    "subject_model": "",
    "subject_type": "",
    "subject_domain": "",
    "video_theme": "",
    "summary": "",
    "hook_line": "",
    "engagement_question": "",
    "visible_text": "",
    "search_queries": [],
    "cover_title": {},
    "evidence": [],
    "review_mode": "",
    "resolved_review_user_feedback": {}
  },
  "field_sources": {
    "subject_brand": "manual_review",
    "subject_model": "manual_review",
    "video_theme": "research",
    "summary": "base_profile"
  },
  "manual_review_applied": true,
  "research_applied": true
}
```

## Integration Points

### Content Profile Step

- 在 `run_content_profile` 产出 draft/final profile 后，同步生成 `downstream_context` artifact。
- 如果人工校对已被解析并应用，`manual_review_applied` 置为 `true`。
- 如果 profile 中存在 `evidence`，`research_applied` 置为 `true`。

### AI Director

- 改为优先读取 `downstream_context.resolved_profile`。
- 导演钩子、桥接文案、互动问题都应基于人工校对/调研后的定位。

### Avatar Commentary

- 改为优先读取 `downstream_context.resolved_profile`。
- 即使当前数字人模式较轻，也要保证后续扩展时默认拿到统一决议上下文。

### Edit Plan

- 改为优先读取 `downstream_context.resolved_profile`。
- 主体 token、低信号字幕判断、插槽与音乐策略都以决议上下文为准。

### Render

- 改为优先读取 `downstream_context.resolved_profile`。
- 输出目录、封面、包装计划等依赖主体信息的位置，都应共享同一上下文。

### Final Review

- Bot 侧内容摘要、关键词、审核提示改为优先读取 `downstream_context`。
- 保证最终审核看到的是已吸收调研和人工校对后的版本。

### Platform Package

- 继续读取统一决议上下文，而不是只特殊处理 `resolved_review_user_feedback`。
- 现有逻辑保留，但输入统一化。

## Error Handling

- 若 `downstream_context` 缺失，回退到当前 `content_profile_*` 选择逻辑。
- 若 `downstream_context` 结构损坏，忽略该 artifact 并回退。
- 不在读取阶段再次做字段优先级推断，避免多处重复逻辑。

## Testing

需要新增或扩展回归测试，覆盖：

1. `run_content_profile` 生成 `downstream_context` artifact
2. `run_ai_director` 优先把 `downstream_context.resolved_profile` 传给导演计划
3. `run_avatar_commentary` 优先把 `downstream_context.resolved_profile` 传给数字人计划
4. `run_edit_plan` 优先把 `downstream_context.resolved_profile` 传给剪辑决策
5. final review 选择内容画像时优先使用 `downstream_context`
6. `platform_package` 在有 `downstream_context` 时继续走统一 resolved profile

## Scope Boundaries

本次不做：

- 新的人工校对字段解析协议
- 调研系统的独立 schema 重构
- 对已有 `content_profile` 生成算法做大改

本次只解决“统一决议结果如何被所有后续环节稳定消费”。
