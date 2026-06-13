# RoughCut 上传素材闭环优化升级执行计划

日期：2026-06-13

## 1. 目标

本轮目标不是再造一条新剪辑链，而是在现有主链内完成上传素材闭环优化升级：

- 让 `strategy_profile -> capability_orchestration -> packaging_timeline -> render_plan` 成为新增剪辑能力的唯一接入面；
- 在不引入外部素材、付费 provider、第二条 render/cut pipeline 的前提下，扩展教程、体验、高光、多素材四类上传素材剪辑能力；
- 保持 `information_density` 基线稳定，并把新增能力都收敛到小而清晰的共享合同。

## 2. 当前判断

这轮工作已经可以直接进入实现，不需要再做前置重构。

原因很简单：

- `Phase 1` capability orchestration 已落地；
- `Phase 2` uploaded asset inventory 已落地；
- `Phase 3` local audio cues 已落地；
- `Phase 4` focus / chapter card 第一层合同已落地；
- 当前缺的不是方向，而是按阶段继续把 insert、highlight、多素材、UI 控制收口到同一主链。

## 3. 固定主链

新增能力只能走下面这条主链：

```text
Source Timeline
  -> Strategy Profile
  -> Capability Orchestrator
  -> Evidence / Candidate Producers
  -> Strategy Decision / Risk Gate
  -> Editorial Timeline
  -> Packaging Timeline
  -> Render Plan
  -> Render / Publication Gates
```

任何提案如果不能明确挂到这条主链中的某一层，就不属于本轮范围。

## 4. 框架原则

### 4.1 只保留一个决策主链

- 不引入第二条自动剪辑 pipeline；
- 不引入独立 tutorial/vlog/highlight runtime；
- 不让 render、publication、manual-editor 自己重新判断该启用哪些能力。

### 4.2 LLM 只做识别，不直接做执行

- LLM 可以判断视频类型、内容形态、推荐 mode；
- 是否启用能力、是否自动执行，必须经过 deterministic policy；
- `job_flow_mode != auto` 时，默认把激进能力降级到 `suggest` 或 `manual_required`。

### 4.3 编辑与包装严格分层

- `Editorial Timeline` 只管 keep/cut/compress/reorder/highlight 决策；
- `Packaging Timeline` 只管 subtitles/focus/insert/music/intro/outro/watermark；
- local insert、focus、chapter card、bgm/sfx 默认都属于 packaging，不得反写 editorial。

### 4.4 用户上传素材优先

- 优先使用主视频、辅视频、图片、音乐、SFX、片头片尾、水印；
- 缺素材时只允许降级，不允许静默拉取外部资源；
- 本轮完全不引入 provider 选择、预算控制、付费审批流。

### 4.5 能力开关必须集中

- mode 和 capability 决策只允许在 `capability_orchestrator` 收口；
- 下游只能消费 capability state，不能再自己猜。

## 5. 阶段计划

### Phase 0：基线冻结

目标：

- 确认 `information_density` 当前主链是稳定基线；
- 确认本轮只做 uploaded-material-only。

收口条件：

- 当前基线回归仍为绿色；
- 不新增任何旁路 artifact 或 side pipeline；
- `docs/design/2026-06-13-uploaded-material-only-optimization-plan.md` 与本执行计划共同作为本轮 source of truth。

### Phase 1：Capability Orchestration

状态：已完成

已落地：

- `src/roughcut/edit/capabilities.py`
- `src/roughcut/edit/capability_policy.py`
- `src/roughcut/edit/capability_orchestrator.py`
- API content-profile capability preview

收口条件：

- mode/capability 不再在 render/manual-editor/publication 出口重复判断；
- LLM 输出只作为输入，不直接决定执行；
- 默认 `information_density` 行为不被破坏。

### Phase 2：Uploaded Asset Inventory

状态：已完成

已落地：

- `src/roughcut/edit/local_asset_inventory.py`
- shared uploaded material inventory contract

收口条件：

- 主视频、辅视频、图片、音频、包装素材有统一 inventory；
- 无辅素材旧任务继续走原稳定路径；
- 不引入任何外部资产 source/provider 合同。

### Phase 3：Local Audio Packaging

状态：已完成

已落地：

- `src/roughcut/edit/local_audio_cues.py`
- packaging/render/runtime shared readers

收口条件：

- 音乐/SFX 只存在于 packaging contract；
- 缺少本地音乐时可平滑退化；
- packaged variant 和 render runtime 读同一份合同。

### Phase 4：Tutorial Focus Layer

状态：第一层已完成

已落地：

- `src/roughcut/edit/local_focus_plan.py`
- focus events / chapter cards 共享合同

下一步：

- 继续补 tutorial anchor 和 step-continuity 验证；
- 收紧 `step_demonstration` 下的 capability-policy 与 runtime gate。

收口条件：

- 教学型静默区间不会被默认误剪；
- focus / chapter card 只影响 packaging；
- 无 focus evidence 时能平滑退化；
- 至少一个教程类 anchor 验证通过。

### Phase 5：Local Insert / B-roll Packaging

状态：下一实现重点

目标：

- 把上传辅视频、图片、片段插入能力收口成共享 insert 合同；
- 不让 insert 逻辑散落在 pipeline、render、manual-editor。

最小交付：

- `src/roughcut/edit/local_insert_plan.py`
- shared insert normalization / recommendation contract
- packaging_timeline / render_plan / runtime shared readers

收口条件：

- 不触发任何外部素材检索；
- insert 只增强呈现，不改变 editorial keep/cut；
- 缺匹配素材默认退化为 `suggest`；
- packaged output 通过 shared readers 消费 insert plan。

### Phase 6：Highlight + Light Multi-material Candidates

目标：

- 增加高光窗口候选；
- 增加轻量多素材组织能力；
- 但不发展成第二条剪辑流水线。

最小交付：

- highlight candidate producer
- narrative assembly candidate producer
- strategy decision gate integration

收口条件：

- highlight 候选进入统一 decision/risk gate；
- 多素材能力仍输出到现有 editorial/packaging/render plan；
- 自动执行阈值保持保守；
- artifact 中可见 candidate provenance 和 reason。

### Phase 7：产品控制面

目标：

- 给前端/API 暴露少量高层控制，不暴露底层碎开关。

建议控制面：

- `edit_mode`: `auto | talking_head | tutorial | vlog | highlight | multi_material`
- `automation_level`: `conservative | standard | richer`
- `material_usage`: `main_only | all_uploaded | selected_uploaded`

收口条件：

- 前端/API 不暴露 provider/stock 配置；
- UI 选择统一落到 `strategy_profile + capability_policy`；
- 默认任务仍走当前稳定路径；
- 对于高风险能力，保留用户显式触发或确认入口，不做静默强开。

## 6. 实现顺序

严格按下面顺序推进：

1. 收完 `Phase 4` 教程锚点与策略门禁；
2. 做 `Phase 5` shared local insert contract；
3. 做 `Phase 6` highlight candidate producer；
4. 做 `Phase 6` light multi-material assembly contract；
5. 最后做 `Phase 7` API/UI 控制面。

不要反过来先做 UI，也不要先引入 provider 或外部资产。

## 7. 每阶段最低验证要求

| 阶段 | 最低验证 |
|---|---|
| Phase 4 | focus contract tests + 1 tutorial anchor |
| Phase 5 | local insert plan tests + 1 packaged insert anchor |
| Phase 6 highlight | candidate tests + 1 highlight anchor |
| Phase 6 multi-material | assembly contract tests + 1 multi-material anchor |
| Phase 7 | API/UI mode contract tests |

所有阶段都必须补：

1. `py_compile` 或等效语法验证；
2. 最窄单测；
3. 影响 runtime 时至少一条代表性 anchor。

## 8. 明确延期项

以下内容本轮不做：

- 外部 stock 下载；
- provider registry；
- 付费 BGM/SFX/图片/视频生成；
- 审批和预算控制；
- 第二条 render pipeline；
- workflow DSL；
- 大型 plugin framework；
- broad frontend redesign。

## 9. 完成定义

本轮优化升级只在以下条件同时满足时才算完成：

1. capability orchestration 已成为权威入口；
2. uploaded local assets 已通过 shared contracts 贯通；
3. tutorial focus、local audio、local insert 三类能力均已接入主链；
4. highlight 和 light multi-material 具备 candidate 支持，但没有演化成第二 pipeline；
5. UI/API 只暴露简洁高层控制；
6. 外部素材/provider 仍保持延期，不混入主链。
