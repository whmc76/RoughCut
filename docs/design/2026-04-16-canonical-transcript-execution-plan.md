# 2026-04-16 Canonical Transcript Execution Plan

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

## 定位

这是一份重构收口和 live 准入的执行文档，不是架构讨论稿。

它只回答四件事：

1. 后续重构优化要按哪四条主线推进。
2. 什么条件下可以判定这轮重构真正完成。
3. 什么条件下可以开始 live 测试。
4. 这轮工作应该怎么分阶段落地和验收。

默认前提：

- 不考虑旧语义兼容。
- 不再允许 `subtitle_items` 继续充当主事实源。
- 不把“能跑通”当作完成，必须以稳定、可观测、可回放为标准。

## 当前边界

当前系统已经具备三层主干：

- `transcript_fact_layer` 负责保存原始事实。
- `canonical_transcript_layer` 负责保存规范后的内容事实。
- `subtitle_projection_layer` 负责保存展示侧字幕投影。

后续工作的目标不是再造新的事实源，而是把这三层的职责、消费者、回退路径和质量门禁全部收口。

## 后续四条主线

### 1. 主链路收口

目标：

- 让 `transcribe -> glossary_review / transcript_review -> canonical_transcript_layer -> subtitle_projection_layer -> downstream` 成为唯一主路径。
- 把旧的字幕倒推理解路径全部降级成显式 fallback，而不是默认行为。
- 让所有关键步骤只消费自己职责范围内的 artifact。

重点任务：

- 清除下游对旧 `SubtitleItem` 的主事实依赖。
- 统一 `content_profile`、`summary_review`、`edit_plan`、`render`、`final_review` 的输入优先级。
- 将 `subtitle_postprocess` 收束为纯投影层，不再承担事实修正职责。

### 2. 重跑与幂等

目标：

- 让每个 step 都有明确的重跑起点、幂等语义和副作用边界。
- 让失败恢复成为标准流程，而不是人工修库。
- 让 Telegram 通知、文件写出、平台文案、成片产物索引都具备可恢复行为。

重点任务：

- 明确哪些步骤可重跑、哪些步骤需要先清理旧产物。
- 为外部副作用定义补偿和重试策略。
- 给失败恢复提供可执行的 rerun 起点映射。

### 3. 质量门禁与可观测

目标：

- 把质量判断从业务逻辑中分离出来，形成结构化门禁。
- 让缺层、坏层、回退层、超时、解析失败都能被明确识别。
- 让控制台、API、CLI 对同一状态源展示一致的诊断信息。

重点任务：

- 固化 `subtitle_quality`、`identity/entity conflict`、`edit_plan review`、`final_review` 的 issue code。
- 把阻断原因、降级原因、回退原因统一成结构化输出。
- 让补偿队列、审核状态、重跑状态都可观测、可过滤、可处置。

### 4. 测试与 live 准备

目标：

- 用固定样本集证明这套链路比旧链路更稳。
- 用重复批次证明问题不是偶然通过。
- 用 live 准入门槛把“可跑”和“可上线”分开。

重点任务：

- 固定 golden jobs。
- 覆盖中文口播、开箱测评、品牌型号密集、复杂停顿和长句等素材类型。
- 把单测、组件测试、流程测试、批量 fullchain、失败恢复测试串成一套标准门禁。

## 完成标准

这轮重构什么时候算“完成”，用下面六条同时成立来判定。

### 1. 单一事实源成立

- `transcript_fact_layer` 是原始事实起点。
- `canonical_transcript_layer` 是规范内容事实起点。
- `subtitle_projection_layer` 只负责展示，不再反向修事实。

### 2. 下游消费者收口完成

- `content_profile`、`summary_review`、`edit_plan`、`render`、`final_review` 默认优先消费 canonical transcript 或其派生物。
- 旧 `SubtitleItem` 不再作为默认事实源。
- fallback 只在显式缺层时出现，并且必须有日志和测试覆盖。

### 3. 重跑语义明确

- 每个关键 step 都有可追踪的 rerun 起点。
- 任一步失败后可以从最近的声明式断点恢复。
- 不需要人工改数据库才能继续跑。

### 4. 质量门禁稳定

- 结构化 issue code 已固定。
- 主要阻断原因可以被稳定复现。
- 质量判断不依赖人眼猜日志。

### 5. 运维可观测

- 控制台、API、CLI 能看到同一份补偿队列和审核状态。
- 失败项可以 requeue、drop、过滤、查看摘要。
- 隐性失败不会被伪装成“空队列”或“正常完成”。

### 6. 回归基线稳定

- golden jobs 连续多轮一致通过。
- 常见素材类型没有新增回归。
- live 相关的阻断项收敛到可解释、可定位、可重跑的范围。

## 开始 Live 测试的门槛

只有在下面门槛全部满足后，才允许开始 live 测试。

### 必要条件

- `batch fullchain` 连续 `3/3` 成功。
- golden jobs 的整体成功率不低于 `90%`。
- 平均质量分不低于 `80`。
- 没有 `P0` blocker。
- 没有“假成功但成片不可用”的情况。
- 失败项都能归因到明确的 issue code。

### 运行条件

- 单测和流程测试全绿。
- 前端控制台和管理页相关测试全绿。
- `pnpm --dir frontend typecheck` 全绿。
- 补偿队列和审核状态在 UI、API、CLI 三端一致。

### 进入方式

先做两段式 live：

1. `Live Dry Run`。
   - 5 到 10 条真实素材。
   - 只验证稳定性和门禁，不对外。
   - 不再做大范围结构改动，只修 blocker。

2. `Live Beta`。
   - 20 条真实素材。
   - 允许人工兜底。
   - 重点看连续稳定性和失败恢复能力。

## 建议阶段划分

### Phase 0: 冻结基线

目标：

- 固定样本集。
- 记录当前基线指标。
- 停止继续扩大旧路径。

验收：

- golden jobs 固定。
- 基线可重复。
- 当前退化路径清单完整。

### Phase 1: 主链路收口

目标：

- 统一事实层、规范层、投影层职责。
- 清掉默认的旧事实依赖。

验收：

- 下游优先级统一。
- fallback 显式且可观测。
- 主链路 contract 稳定。

### Phase 2: 幂等与重跑

目标：

- 让失败恢复成为标准化流程。
- 把副作用收口成可恢复动作。

验收：

- 关键 step 可重跑。
- 外部副作用可补偿。
- 恢复行为有测试覆盖。

### Phase 3: 质量门禁硬化

目标：

- 把所有阻断原因变成结构化诊断。
- 让控制台/API/CLI 看到同一套状态。

验收：

- issue code 固化。
- 运维入口完整。
- 阻断和降级都可解释。

### Phase 4: 批量回归

目标：

- 用真实样本批量验证稳定性。
- 用连续运行验证不是偶然通过。

验收：

- `3/3` batch fullchain 通过。
- golden jobs 满足门槛。
- 没有新的 P0 blocker。

### Phase 5: Live 准入

目标：

- 进入 live dry run。
- 先内部观察，再扩大到 beta。

验收：

- `Live Dry Run` 通过。
- `Live Beta` 可以开始。
- live 期只做 blocker 修复，不再做大重构。

## 测试矩阵

| 测试层级 | 覆盖对象 | 重点 | 通过标准 |
|---|---|---|---|
| 单元测试 | artifact builder、优先级选择、结构化转换 | schema、字段、优先级 | contract 稳定 |
| 组件测试 | `transcribe`、`glossary_review`、`subtitle_postprocess`、`content_profile`、`edit_plan` | 三层 artifact 是否按预期落地 | 输入输出一致 |
| 流程测试 | `pipeline.steps` 主链 | 依赖顺序、回退行为 | 主路径正确，fallback 显式 |
| 回归测试 | golden jobs / 历史问题样本 | 品牌、型号、数字、长句、断句 | 不新增明显退化 |
| 运维测试 | CLI / API / 控制台 | 队列、重试、drop/requeue、状态查看 | 三端一致 |
| 失败恢复测试 | rerun、补偿、队列损坏、超时 | 恢复能力 | 能定位、能恢复、能重复 |

## 结论

这轮重构的目标不是继续堆新能力，而是把当前系统收口成一条稳定主链：

`事实层 -> 规范层 -> 投影层 -> 下游消费 -> 可观测运维 -> 可恢复重跑`

当“完成标准”全部满足，并且批量回归连续稳定后，才进入 `Live Dry Run`。`Live Dry Run` 通过后，才进入 `Live Beta`。
