# Token Usage And Cache

## 已落地能力

- `GET /api/v1/jobs/{job_id}/token-usage`
  - 返回单个任务的 token telemetry、按步骤拆分、按 operation 拆分、按 model 拆分。
  - 同时返回 step 级 `cache_entries` 和 job 级 `cache` 汇总。

- `GET /api/v1/jobs/usage-summary`
  - 返回跨任务汇总视图。
  - 默认按最近 `60` 个任务聚合，可通过 `?limit=` 调整。
  - 包含总 tokens、总调用数、缓存命中/未命中、命中率、Top steps、Top models、Top providers。

- `GET /api/v1/jobs/usage-trend`
  - 返回按天聚合的趋势视图。
  - 默认最近 `7` 天，可通过 `?days=` 调整；任务采样窗口默认最近 `120` 个任务，可通过 `?limit=` 调整。
  - 支持 `?focus_type=step|model|provider` 和 `?focus_name=` 看指定维度的日趋势。
  - 支持 `?step_name=`，等价于 `?focus_type=step&focus_name=...`。
  - 每天包含：总 tokens、总调用、缓存命中率，以及当前维度下的当日最高消耗项。

## 缓存语义

- `content_profile`
  - 先走严格输入指纹缓存。
  - 指纹绑定：`source_file_hash`、`source_name`、`workflow_template`、字幕摘录、词表、用户记忆、`copy_style`。
  - 命中后直接复用已确认的推理结果，不再重复发起模型调用。

- `platform_package.fact_sheet`
  - 只在不会牺牲事实准确性的情况下允许缓存。
  - 对“主体不明确直接跳过核验”或“已有足够本地证据、无需再次联网搜索”的场景可复用。

- `platform_package.generate`
  - 指纹绑定：`prompt_brief`、`fact_sheet`、`copy_style`、`author_profile`。
  - 只有在事实约束完全一致时才复用平台文案生成结果。

## 指标解释

- `cache.hits`
  - 当前任务或当前汇总窗口里，命中的缓存条目数。

- `cache.avoided_calls`
  - 由缓存直接避免掉的重复模型调用次数。
  - 这是准确指标。

- `cache.saved_total_tokens`
  - 只统计“命中且拥有真实 usage baseline”的缓存条目。
  - baseline 来自该 cache key 首次 miss 时的真实模型 usage 增量，不做估算和分摊。

- `cache.saved_tokens_hit_rate`
  - 表示当前命中里，有多少比例已经具备真实 baseline。
  - 这能区分“命中了旧缓存但还没有历史基线”和“命中了可准确核算节省量的新缓存”。

- `content_profile.enrich` 预热缓存的保守口径
  - `infer` 完成后会顺手预热一份 `enrich` cache 结果，方便后续 seeded profile 命中。
  - 这份预热结果不是一次真实 `enrich` 调用，因此不会继承 `infer` 的 baseline，避免虚高 saved tokens。

- `model/provider` 维度下的 cache 口径
  - 目前不把 step 级 cache 命中硬分摊到 model 或 provider。
  - 原因是缓存发生在调用之前，很多情况下无法准确知道“被避免的那次调用”本应落到哪个 model/provider。
  - 因此 `focus_type=model|provider` 的趋势图只展示真实 usage，不虚构该维度的缓存收益。

## 前端展示

- Jobs 页顶部显示跨任务汇总：
  - `累计 Tokens`
  - `累计调用`
  - `节省 Tokens`
  - `缓存命中率`
  - 同页继续展示 `高消耗步骤` 和 `缓存效果` 面板。
  - 同页继续展示 `高消耗模型` 和 `高消耗 Provider` 面板。
  - 同页继续展示 `最近 7 天趋势` 面板。
  - 支持 `7d / 30d` 切换，以及 `总量 / 按步骤 / 按模型 / 按 Provider` 钻取。

- Overview 页也会显示最近任务的 token / cache 摘要：
  - `Total Tokens`
  - `Total Calls`
  - `Saved Tokens`
  - `Cache Hit Rate`
  - 同时显示 `最近 7 天趋势` 面板。
  - 支持 `7d / 30d` 和 `总量 / 按步骤 / 按模型 / 按 Provider` 切换。

- 任务详情页显示单任务视图：
  - token 总量
  - 输入 / 输出 tokens
  - 模型调用数
  - 缓存命中 / 命中率 / 避免重复调用 / 节省 Tokens / 基线覆盖率 / 命中步骤数
  - Top steps / Top operations / Cache-hit steps / Top models
