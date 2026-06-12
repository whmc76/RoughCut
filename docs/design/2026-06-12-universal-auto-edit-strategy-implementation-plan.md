# RoughCut 通用自动剪辑策略重构实现方案

日期：2026-06-12

## 1. 目标

本轮正式重构的目标很具体：

- 把当前已闭合的口播/开箱自动剪辑主链正式收口为 `information_density` 基线；
- 把“剪辑决策”和“包装编排”在代码、artifact、执行出口三个层面彻底分层；
- 在不改行为语义的前提下，把主链里对同一事实的重复恢复收回共享 helper 或同函数内一次解析复用；
- 为后续 `step_demonstration / experience_and_mood / event_highlight / narrative_assembly` 留出稳定扩展位。

本轮不是为了马上支持所有题材，而是为了把第一条真实可用链路改造成通用底座。

## 2. 当前结论

已经具备正式重构条件，可以直接推进，不需要先等待别的题材实现完。

成立前提只有两个：

1. 当前 `information_density` 链路已经有可回放的真实基线；
2. 不允许并行写 `src/roughcut/pipeline/steps.py`、`src/roughcut/api/jobs.py`、`src/roughcut/media/render.py` 这三个主链文件。

详细已落地切片、回归结果、anchor 目录统一记录在 `docs/agent-current-state.md`。本文件只保留执行方案、顺序、边界和验收。

## 3. 策略类型与产品映射

核心架构只认“策略类型”，不直接认“题材名”。

### 3.1 策略类型

- `information_density`
- `step_demonstration`
- `experience_and_mood`
- `event_highlight`
- `narrative_assembly`

### 3.2 常见视频形态到策略类型的映射

| 常见视频形态 | 主策略类型 | 核心剪辑逻辑 |
|---|---|---|
| 口播、开箱、知识讲解、测评 | `information_density` | 提升表达效率，压缩废话与无效停顿 |
| 录屏讲解、软件教学、操作演示 | `step_demonstration` | 保步骤完整，可跟随，压缩无效等待 |
| vlog、旅行、探店、美食体验 | `experience_and_mood` | 保留体验段落、环境声、节奏与空间感 |
| 发布会高光、比赛集锦、活动精华 | `event_highlight` | 发现峰值片段，排序成可传播切片 |
| 多素材叙事、故事向拼接、合集成片 | `narrative_assembly` | 组织素材关系与叙事结构，不是单素材删减 |

### 3.3 preset 的位置

`talking_head`、`unboxing_review`、`knowledge_explainer`、`screen_tutorial`、`travel_vlog` 这类名字都应该是产品 preset。

preset 只负责：

- 选择默认 `strategy_type`；
- 提供局部参数；
- 指定默认包装偏好。

preset 不负责：

- 分叉核心流水线；
- 在 render、manual-editor 或 review 层偷偷实现另一套策略。

## 4. 固定主链

正式重构后的主链固定为：

```text
Source Timeline
  -> Candidate Producers
  -> Strategy Decision / Risk Gate
  -> Editorial Timeline
  -> Packaging Timeline / Effect Plan
  -> Render Variants / Publication Package
```

### 4.1 分层职责

| 层 | 负责什么 | 不允许做什么 |
|---|---|---|
| `Source Timeline` | 原始素材、ASR、视觉、音频、内容画像事实 | 直接下最终删减结论 |
| `Candidate Producers` | 产出 cut / keep / trim / highlight / reorder 候选与证据 | 直接写最终时间线 |
| `Strategy Decision / Risk Gate` | 按策略把候选裁成 `auto_apply / manual_confirm / block / ignore` | 写包装特效计划 |
| `Editorial Timeline` | 固化 keep / cut / compress / reorder / highlight 等剪辑决策 | 回读包装再改剪辑 |
| `Packaging Timeline / Effect Plan` | intro / outro / insert / transition / bgm / subtitles / crop 等包装编排 | 回写 editorial keep / cut |
| `Render / Publication` | 消费 editorial + packaging，输出变体和发布物料 | 重新发明策略规则 |

### 4.2 包装能力与剪辑能力的边界

必须明确区分：

- 剪辑能力：决定保留什么、删除什么、压缩什么、重排什么；
- 包装能力：决定保留下来的内容如何呈现。

包装确实会影响最终输出时间轴，例如片头片尾、转场、insert、BGM 卡点、平台裁切。但这些影响必须被隔离在 `Packaging Timeline / Effect Plan`，不能反向篡改 `Editorial Timeline` 的删减结论。

正确顺序固定为：

1. 先产出 `Editorial Timeline`；
2. 再基于 editorial 生成 `Packaging Timeline / Effect Plan`；
3. render 只消费这两层合同，不在运行时再发明新的删减规则。

## 5. 本轮范围

本轮只做 `information_density` 的行为等价迁移。

本轮允许：

- 调整 helper 边界；
- 合并重复 reader；
- 收平 caller / callee context 传递；
- 让 manual-editor、bundle、render 三个出口消费同一份合同。

本轮禁止：

- 新增 `step_demonstration`、`experience_and_mood`、`event_highlight`、`narrative_assembly` 的完整实现；
- 重开已经闭合的 `C1-C5` 框架问题；
- 为抽象而新增 registry、facade、report schema；
- 为了“未来可能有用”重写 packaging 算法或 render 流程。

## 6. 当前代码基线

本轮以当前 June 12 代码状态为基线，以下事实已经成立：

- `Phase 0`：`information_density` 已有 focused regressions + 真实 anchor 基线；
- `Phase 1`：strategy metadata 已落地；
- `Phase 2`：candidate producer metadata 已落地；
- `Phase 3`：统一 strategy decision / risk gate 首切片已落地；
- `Phase 4`：editorial helper 已落地，并进入 consumer sweep；
- `Phase 5`：packaging helper 已落地，并进入 consumer sweep。

本轮不再做“重新设计未来架构”，而是把当前闭合主链收成稳定合同。

## 7. 当前共享合同

本轮所有代码变更都应围绕现有合同推进，不再额外发明并行协议。

### 7.1 Editorial 合同

主要来源：

- `src/roughcut/edit/editorial_timeline.py`
- `editorial_timeline_segments(...)`
- `editorial_timeline_analysis(...)`
- `editorial_timeline_subtitle_projection(...)`
- 已有 shared editorial readers

要求：

- keep / cut / subtitle projection / analysis 只通过 editorial helper 读取；
- 不再在消费者本地直读旧字段并拼半套 editorial 事实。

### 7.2 Packaging 合同

主要来源：

- `src/roughcut/edit/packaging_timeline.py`
- `resolve_packaging_timeline_payload(...)`
- `build_packaging_timeline_payload(...)`
- `packaging_timeline_asset_plan(...)`
- `packaging_timeline_transitions(...)`
- 其他已落地 `packaging_timeline_*` readers

要求：

- 包装资产、编辑强调、转场、section choreography、subtitle style 等都通过共享 helper 读取；
- 不再在 `steps.py / render.py / api/jobs.py` 手拆 nested payload。

### 7.3 Render-plan 合同

主要来源：

- `src/roughcut/edit/render_plan.py`
- `render_plan_*` readers
- 本地 execution context helpers，例如：
  - `src/roughcut/api/jobs.py::_manual_editor_render_plan_context(...)`
  - `src/roughcut/pipeline/steps.py::_runtime_render_plan_context(...)`
  - `src/roughcut/media/render.py::_render_runtime_plan_context(...)`

要求：

- 同一执行函数里的 render-plan 子事实优先一次恢复，随后本地复用；
- caller 已有 context 时，callee 优先消费调用方上下文，不再内部重算。

## 8. 正式实施批次

### Batch A：Phase 4/5 consumer sweep

这是当前主工作包，目标是把主链里还没收平的事实读取路径继续收掉。

主文件固定为：

- `src/roughcut/pipeline/steps.py`
- `src/roughcut/media/render.py`
- `src/roughcut/api/jobs.py`

执行原则：

- 只收“第一坏层”的重复事实恢复；
- 优先处理 live path；
- 优先处理 caller 已有 context、callee 又重算一次的边界；
- 优先处理同函数内多次恢复同一 payload 子事实的点。

完成标准：

- keep / cut / projection / analysis 全部通过 editorial helper 或同函数单次解析；
- packaging assets / transitions / subtitle style / editing accents 全部通过 packaging helper 或同函数单次解析；
- render-plan 已有 helper 能覆盖的事实，不再在消费者本地再拼一遍。

### Batch B：三个执行出口对齐

目标是把三个真正产出结果的出口，拉到同一份策略合同上：

- `api/jobs.py::apply_manual_editor_timeline(...)`
- `pipeline/steps.py::_build_variant_timeline_bundle(...)`
- `pipeline/steps.py::run_render(...)` + `media/render.py::render_video(...)`

完成标准：

- 每个出口都能明确说出自己在消费哪一层合同；
- 不再出现“helper 已存在，但出口仍局部重建半套事实”的分叉；
- manual-editor / bundle / render 对 `information_density` 的行为保持等价。

### Batch C：根因优先

如果 consumer cleanup 暴露真实回归，只修第一坏层，不做症状补丁。

执行格式固定为：

1. 先写症状；
2. 再写第一坏层；
3. 再写根因；
4. 再写为什么现在暴露。

已经闭合、不得重开的点：

- `subtitle_sync_issue`
- `resolve_packaging_timeline_payload(...)` import gap

### Batch D：最小验证 + 真实 anchor

每个窄切片都必须带最小验证。

规则固定为：

- helper / editorial-only / manual-editor 语义切片：`py_compile` + focused pytest + `edit_plan` anchor；
- render / runtime 切片：`py_compile` + focused pytest + `render` anchor。

通过标准固定为：

- focused regressions 通过；
- `live_readiness=pass`；
- `required_checks=4/4`。

当前仍允许保留的非阻断项只有：

- `reference_high_risk_not_reproduced`

### Batch E：preset 层前的停手条件

只有在下面条件成立后，才允许进入 preset 映射或下一策略域：

1. `steps.py / api/jobs.py / render.py` 主链高价值 consumer 的重复事实恢复已基本收平；
2. manual-editor、bundle、render 三个出口已经对齐到共享合同；
3. `information_density` 基线在 focused regression 和真实 anchor 上继续等价。

## 9. 当前执行顺序

当前不再从零开始，而是从已落地基线继续往前切。

接下来的执行顺序固定为：

1. 先继续 `src/roughcut/pipeline/steps.py` 的剩余 consumer sweep；
2. 再处理 `src/roughcut/media/render.py` 的 caller / callee context handoff；
3. 最后回到 `src/roughcut/api/jobs.py` 收剩余 manual-editor apply / rebuild 局部重建点。

说明：

- 这里说的是“优先扫描顺序”，不是一次同时大改三份文件；
- 每次只落一个窄切片；
- 一刀只改一个真实重复事实恢复点。

## 10. 当前优先切片

以下是已经收敛出的下一批优先切片，按顺序执行。

### Slice 1：`steps.py` bundle / validation 邻域

目标：

- 继续收平 `variant_timeline_bundle` 及其校验链对 editorial / packaging 事实的重复恢复；
- 让 bundle builder 和 validator 优先消费已经标准化的本地 facts，而不是再从嵌套 payload 读回一遍。

重点位置：

- `src/roughcut/pipeline/steps.py::_build_variant_timeline_bundle(...)`
- `src/roughcut/pipeline/steps.py::_validate_variant_timeline_bundle(...)`
- 它们的直接 caller

完成标准：

- bundle 产出层不再做低价值的 payload 回读；
- validation 只校验 bundle 当前合同，不临时发明另一套 reader 路径。

### Slice 2：`render.py` runtime handoff 邻域

目标：

- 继续检查 `render_video(...)` 与下游 helper 之间，是否还存在 caller 已有 context、callee 又局部重算的 live path；
- 只处理真实重复恢复点，不做 render 算法改版。

重点位置：

- `src/roughcut/media/render.py::render_video(...)`
- timed overlay / packaging apply / avatar 分支相关 helper

完成标准：

- runtime 主链能用已有 context 的地方都直接透传；
- 下游 helper 的 fallback 只保留给非主链调用场景。

### Slice 3：`api/jobs.py` manual-editor apply 邻域

目标：

- 在 rebuild-delivery slice 之后，继续收掉 `apply_manual_editor_timeline(...)` 中仍残留的 same-function render-plan / packaging / editorial 子事实局部重建点；
- 保持 manual-editor 的 apply 语义、rerun 语义和 subtitle-only 语义不变。

重点位置：

- `src/roughcut/api/jobs.py::apply_manual_editor_timeline(...)`
- 紧邻的 manual-editor helper consumers

完成标准：

- manual-editor 出口只消费共享合同或本地一次解析事实；
- 不再出现“前面刚算过，后面又从 rebuilt payload 读回来”的模式。

## 11. 不动点

以下内容本轮明确不动：

- `step_demonstration` 的 screen activity / OCR / cursor evidence；
- `experience_and_mood` 的风景保留与氛围节奏判断；
- `event_highlight` 的峰值检测与高光排序；
- `narrative_assembly` 的多素材结构编排；
- packaging timeline 的大改版；
- scorecard / golden schema 的再扩张；
- 为了抽象而新增新的 registry / facade / orchestrator 层。

## 12. 验收标准

本轮正式重构结束时，至少满足：

1. 当前链路可以明确标记为 `information_density`；
2. 旧 job、旧 artifact、旧 manual-editor flow 继续兼容；
3. editorial 和 packaging 的边界在代码和 artifact 中都可见；
4. manual-editor、bundle、render 三个出口消费同一份共享合同；
5. 至少一个真实 `information_density` anchor 持续通过；
6. 没有为了重构便利，把包装能力重新塞回剪辑能力层。

## 13. 下一阶段入口

只有在本轮验收标准成立后，才进入下一阶段。

推荐的下一策略域仍然是：

- `step_demonstration`

原因不是它“更容易”，而是它离现有链路最近：

- 仍然高度依赖语音、字幕和时间轴；
- 只是在证据层新增 screen activity / OCR / UI state；
- 不需要先解决 `experience_and_mood` 对视觉美感、环境声和节奏保护的问题。
