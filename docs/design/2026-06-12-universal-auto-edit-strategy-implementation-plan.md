# RoughCut 通用自动剪辑策略重构实现方案

日期：2026-06-12

## 目标

本方案把 RoughCut 从“信息密度型口播/开箱链路”升级为“通用自动剪辑发布引擎”的第一阶段实现。

第一阶段只做一件事：把当前已经收口的自动剪辑主链标定为 `information_density` 策略，并把候选、裁决、时间线、包装编排的边界显式化。

本阶段不追求新增 vlog、高光、录屏、多素材成片能力；也不重开已经闭合的 `C1-C5` 框架问题。

## 当前前提

依据：

- `docs/2026-06-12-final-closure-audit.md`
- `docs/2026-06-12-final-completion-audit-matrix.md`
- `docs/design/2026-06-11-universal-auto-edit-strategy-boundaries.md`

当前判断：

- `C1-C5` 在当前 narrowed scope 下已经足够闭合，可以作为新重构的基线。
- 剩余 render provider 类样本属于可选 breadth，不阻塞通用策略重构。
- `C6` 智能删减质量增强仍然延后，不能作为本次重构入口。

## 执行状态

当前文档不再只是启动前方案，也作为本轮重构的执行基线。

| 阶段 | 状态 | 当前结论 |
|---|---|---|
| Phase 0：基线冻结 | 已完成当前切片收口 | focused regression 已通过，manual-editor real-job apply semantics anchor 已通过，当前切片可继续向下推进 |
| Phase 1：Strategy Profile 合同 | 已落地 | 已新增 `strategy_profile.py`，默认把旧 payload 归一到 `information_density`，并写入 `cut_analysis / refine_decision_plan / manual-editor` 相关出口 |
| Phase 2：Candidate Producer 协议 | 已落地 | 现有规则候选已补齐 `producer_id / strategy_applicability` metadata，但尚未把策略真正接入裁决 |
| Phase 3：Strategy Decision / Risk Gate | 已落地首切片 | 已新增共享 strategy decision helper，`cut_analysis` 内的 auto-apply / manual-confirm 判断已统一收口，当前仍保持 `information_density` 行为等价 |
| Phase 4：Editorial Timeline 显式化 | 已落地首切片 | 已新增共享 editorial-timeline helper，统一 keep-segment normalize / build / resolve；render 与 manual-editor 开始复用，行为保持不变 |
| Phase 5：Packaging Timeline / Effect Plan 隔离 | 已落地首切片 | 已新增共享 packaging-timeline helper，并把 variant bundle 从平铺包装字段收成单个 `packaging_timeline` payload；当前仍保持读取兼容与行为不变 |
| Phase 6：Preset 层 | 未开始 | 产品 preset 只做入口映射，不得分叉核心流水线 |
| Phase 7：第二策略域准备 | 未开始 | 只有在 `information_density` 等价迁移闭合后，才允许进入 `step_demonstration` |

## 正式启动结论

当前已经具备正式重构条件，可以直接开始，不需要为了“先等所有未来题材方案想清楚”而继续空转。

原因只有三条：

1. 当前 `information_density` 链路已经有可回放、可验证、可对比的闭合基线。
2. 第一阶段重构的目标是收边界、收合同、收读取路径，不是同时扩到第二种剪辑策略。
3. 当前工作树里的未提交改动本身就是这轮重构的首批切片，继续沿同一条主线推进成本最低。

但有一个边界必须守住：

- 不要让另一个并行线程继续同时改 `src/roughcut/pipeline/steps.py`、`src/roughcut/api/jobs.py`、`src/roughcut/media/render.py` 这类主链文件；如果还有别的线程在动这些文件，应先停在只读/待合并状态，再沿当前线程继续推进。

## 总体原则

### 1. 行为等价优先

第一阶段必须保持当前口播/开箱自动剪辑结果基本等价。

允许变化：

- artifact 中增加内部策略 metadata；
- helper 命名更清晰；
- 旧 payload 增加向后兼容字段；
- 报告内部可读性提升。

不允许变化：

- 低风险自动删减数量无故变化；
- manual editor 看到的候选和 accepted cuts 无故变化；
- render 输入 keep/remove timeline 无故变化；
- golden / scorecard 口径被新策略字段重新解释。

### 2. 先抽合同，再扩能力

先把当前能力收进这些合同：

```text
Strategy Profile
Candidate Producer
Strategy Decision / Risk Gate
Editorial Timeline
Packaging Timeline / Effect Plan
Publication Package
```

再考虑新增：

- screen activity evidence
- scenic / ambient evidence
- highlight candidate
- narrative assembly

### 3. 策略类型和视频形态分离

代码里第一层只认策略类型：

- `information_density`
- `step_demonstration`
- `experience_and_mood`
- `event_highlight`
- `narrative_assembly`

口播、开箱、录屏、vlog、直播、多素材合集是产品 preset 或识别结果，不是核心分支名。

### 4. 剪辑时间线和包装时间线分离

必须区分：

- `Source Timeline`：原始素材事实，不可改写。
- `Editorial Timeline`：保留、删除、压缩、重排、高光等剪辑决策。
- `Packaging Timeline / Effect Plan`：片头片尾、转场、特效、BGM、平台裁切、字幕样式等包装编排。

包装编排可以影响最终输出时间轴，但不能反向偷偷改变 `Editorial Timeline` 的保留/删除决策。

## 目标架构

第一阶段重构完成后的主链结构固定为：

```text
Source Timeline
  -> Candidate Producers
  -> Strategy Decision / Risk Gate
  -> Editorial Timeline
  -> Packaging Timeline / Effect Plan
  -> Render Variants / Publication Package
```

模块职责固定如下：

| 层 | 职责 | 不允许做的事 |
|---|---|---|
| `Source Timeline` | 保留原始素材时间事实、转写事实、画面事实 | 推断最终删减 |
| `Candidate Producers` | 产出候选动作和证据 | 直接改最终时间线 |
| `Strategy Decision / Risk Gate` | 按策略决定 `auto_apply / manual_confirm / block / ignore` | 写包装特效计划 |
| `Editorial Timeline` | 固化保留/删除/压缩后的剪辑决策 | 偷偷读取包装字段再二次改剪辑 |
| `Packaging Timeline / Effect Plan` | 追加 intro/outro/insert/transition/bgm/subtitle-style 等包装编排 | 回写 `Editorial Timeline` |
| `Render / Publication` | 消费 editorial + packaging，生成 variant 和发布物料 | 再发明新的剪辑策略分支 |

这套结构的关键不是“多一层抽象”，而是把将来不同题材的差异压到 `Strategy Profile + Candidate Producers + Decision Gate`，而不是散落在 render、manual-editor、scorecard 里。

## 分阶段实现

## Phase 0：基线冻结

目标：确保重构从一个可回放状态开始。

动作：

1. 确认当前进行中的收口线程已经停在 completed/idle。
2. 记录当前 `git status --short`。
3. 跑最小基线验证：

```powershell
PYTHONPATH=src python -m pytest tests/test_rule_registry.py tests/test_source_timeline_contract.py -q
PYTHONPATH=src python -m pytest tests/test_manual_editor_helpers.py -k "auto_refine or frontend_managed_auto_cuts or cut_analysis_candidate" -q
PYTHONPATH=src python -m pytest tests/test_run_auto_edit_recovery_golden_set.py -q
```

退出条件：

- 没有 in-progress thread 正在改 `steps.py / api/jobs.py / subtitle_pipeline.py / run_fullchain_batch.py`。
- 当前 failing tests 若存在，必须被记录为重构前已存在，而不是本次引入。

## Phase 1：Strategy Profile 合同

目标：引入策略合同，但不改变当前行为。

新增建议：

- `src/roughcut/edit/strategy_profile.py`

核心类型：

```python
StrategyType = Literal[
    "information_density",
    "step_demonstration",
    "experience_and_mood",
    "event_highlight",
    "narrative_assembly",
]
```

第一版只启用：

```json
{
  "strategy_type": "information_density",
  "auto_apply_policy": "current_conservative_default",
  "speech_priority": "high",
  "visual_priority": "medium",
  "silence_policy": "trim_unvoiced_gaps",
  "packaging_policy": "current_default"
}
```

接入点：

- `run_edit_plan(...)`
- `cut_analysis` payload
- `refine_decision_plan` metadata
- manual-editor session payload

约束：

- 不新增 scorecard 主指标。
- 不让 strategy 字段参与裁决，先只透传 metadata。

验证：

- 当前 golden case 的 keep/remove timeline 不应因为 strategy metadata 改变。
- manual editor 候选数量不应变化。

## Phase 2：Candidate Producer 协议

目标：把现有规则输出收口成候选生产器协议，但先不改生成逻辑。

现有能力映射：

| 当前来源 | Candidate Producer |
|---|---|
| filler rules | `speech_filler_candidate_producer` |
| catchphrase rules | `speech_catchphrase_candidate_producer` |
| pause / silence | `pause_trim_candidate_producer` |
| repeated speech | `repeated_speech_candidate_producer` |
| smart delete / low signal | `semantic_trim_candidate_producer` |

建议最小协议：

```json
{
  "candidate_id": "...",
  "producer_id": "speech_filler_candidate_producer",
  "action": "delete|trim|keep|highlight|chapter|reorder",
  "start": 12.3,
  "end": 18.6,
  "strategy_applicability": ["information_density"],
  "risk_level": "low|medium|high",
  "confidence": 0.86,
  "match_surface": "raw|canonical|display|screen|vision|audio",
  "evidence": {}
}
```

接入方式：

- 复用现有 `src/roughcut/edit/rule_registry.py`。
- 不创建第二套规则注册表。
- 在 `cut_analysis` / `smart_cut_candidates` 的出口归一化 producer metadata。

主要文件：

- `src/roughcut/edit/rule_registry.py`
- `src/roughcut/edit/cut_analysis.py`
- `src/roughcut/edit/smart_cut_candidates.py`
- `src/roughcut/edit/refine_decisions.py`
- `src/roughcut/api/jobs.py`

退出条件：

- 规则卡片计数、candidate 计数、manual editor 高亮计数不变。
- legacy candidate payload 仍可被读取。

## Phase 3：Strategy Decision / Risk Gate

目标：把“是否自动应用”从规则散点判断迁到统一策略裁决层。

第一版只实现：

```text
information_density strategy + current conservative policy
```

裁决输入：

- candidate list
- rule registry metadata
- source timeline contract
- current strategy profile
- manual override / accepted cuts

裁决输出：

```json
{
  "decision_id": "...",
  "candidate_id": "...",
  "decision": "auto_apply|manual_confirm|block|ignore",
  "strategy_type": "information_density",
  "reason": "...",
  "risk_level": "low|medium|high",
  "evidence": {}
}
```

主要落点：

- `src/roughcut/edit/refine_decisions.py`
- `src/roughcut/edit/timeline_contract.py`
- `src/roughcut/api/jobs.py`

退出条件：

- 当前 auto mode 的 low-risk 自动删减集合不变。
- manual editor 的 frontend-managed auto cuts 集合不变。
- `verify_manual_editor_apply_semantics.py --json` 继续通过当前 4 条 contract anchors。

## Phase 4：Editorial Timeline 显式化

目标：把现有 keep/remove/refine timeline 明确命名为 `Editorial Timeline`，但不重写 render。

第一阶段不拆数据库模型，只做 helper 和 payload alias：

```text
refine_decision_plan.keep_segments
editorial_timeline.keep_segments
render_plan.keep_segments
```

必须保持同源。

建议新增：

- `src/roughcut/edit/editorial_timeline.py`

职责：

- normalize keep/remove segments
- derive removed segments
- attach decision provenance
- expose compatibility view for render/manual-editor

禁止：

- 在 render 阶段重新判断删减。
- 在 manual editor save 时绕过 shared editorial helper。
- 为包装转场或 BGM 改写 editorial keep/remove。

退出条件：

- render 输入 keep segments 与重构前一致。
- manual editor subtitle-only / no-material-change 合同不变。

## Phase 5：Packaging Timeline / Effect Plan 隔离

目标：把会影响输出时间轴的包装编排从剪辑决策中隔离出来。

第一版只做命名和读取边界，不重写所有包装逻辑。

归入 `Packaging Timeline / Effect Plan`：

- intro / outro
- insert clips
- transition events
- BGM / sound effect events
- emphasis / pulse / overlay accents
- subtitles style and layout
- platform crop / aspect adaptation

主要文件：

- `src/roughcut/edit/render_plan.py`
- `src/roughcut/pipeline/steps.py`
- `src/roughcut/media/render.py`
- `src/roughcut/media/output.py`
- `src/roughcut/publication_packaging.py`

原则：

- 包装计划消费 `Editorial Timeline`。
- 包装计划可以生成自己的 output timeline。
- 包装计划不能回写 editorial keep/remove。

退出条件：

- plain / packaged / ai_effect / avatar variants 的输出路径和字幕映射不变。
- `render_outputs` payload 兼容旧消费者。
- audit pack 能同时看见 editorial decision 与 packaging effects。

## Phase 6：Preset 层

目标：把常见视频形态映射到策略 profile，但暂不新增复杂能力。

第一批 preset：

| Preset | strategy_type |
|---|---|
| `talking_head` | `information_density` |
| `unboxing_review` | `information_density` |
| `knowledge_explainer` | `information_density` |

只作为产品/配置入口，不作为核心分支。

延后 preset：

- `screen_tutorial`
- `vlog_travel`
- `event_highlight`
- `narrative_assembly`

## Phase 7：第二策略域准备

只有当 `information_density` 行为等价迁移完成后，才允许进入第二策略域。

推荐第二策略：

```text
step_demonstration
```

原因：

- 与当前语音/字幕链路最接近。
- 只需要增加 screen activity / OCR / UI state evidence。
- 不需要先解决 vlog 的视觉美感判断。

第一批新增 evidence：

- screen change
- cursor / keyboard activity
- OCR text change
- UI state transition
- long idle with no speech

禁止：

- 不得把 no-speech 直接等同于 delete。
- 不得在 evidence 层直接生成 final timeline。

## 文件影响面

### 第一批可动文件

- `src/roughcut/edit/rule_registry.py`
- `src/roughcut/edit/cut_analysis.py`
- `src/roughcut/edit/smart_cut_candidates.py`
- `src/roughcut/edit/refine_decisions.py`
- `src/roughcut/edit/timeline_contract.py`
- `src/roughcut/api/jobs.py`
- `src/roughcut/pipeline/steps.py`

### 第二批可动文件

- `src/roughcut/edit/render_plan.py`
- `src/roughcut/media/render.py`
- `src/roughcut/media/output.py`
- `src/roughcut/pipeline/quality.py`
- `scripts/run_auto_edit_recovery_golden_set.py`
- `scripts/build_batch_output_scorecard.py`

### 暂不主动触碰

- publication adapter runtime
- browser publication bridge
- cover generation prompt logic
- platform-specific upload code
- frontend broad UI redesign

除非它们被第一阶段策略 metadata 或 packaging timeline compatibility 明确阻塞。

## 测试矩阵

### 单元 / 合同测试

每个 phase 必须有最小定向回归：

- strategy profile 默认值
- candidate producer metadata compatibility
- risk gate decision compatibility
- editorial timeline keep/remove compatibility
- packaging timeline does not mutate editorial timeline

### 当前必须复跑的现有测试

```powershell
PYTHONPATH=src python -m pytest tests/test_rule_registry.py tests/test_source_timeline_contract.py -q
PYTHONPATH=src python -m pytest tests/test_manual_editor_helpers.py -q
PYTHONPATH=src python -m pytest tests/test_run_auto_edit_recovery_golden_set.py -q
PYTHONPATH=src python -m pytest tests/test_run_fullchain_batch.py -q
```

### 真实样本验证

第一阶段至少复跑一个信息密度型 anchor：

```powershell
python scripts/run_auto_edit_recovery_golden_set.py --manifest docs/golden-jobs/auto-edit-recovery-golden-slice.v1.json --case-id noc_mt34_short_done --stop-after edit_plan --report-dir output/test/auto-edit-recovery-golden/strategy-refactor
```

验收：

- job terminal state 正常；
- `edit_plan` 能完成；
- keep ratio 与重构前同量级；
- auto-apply / manual-confirm / multimodal-pending 数量无异常漂移；
- manual-editor contract 不退化。

## 切换策略

### 默认策略

所有旧 job、旧 API、旧 CLI 默认：

```text
strategy_type = information_density
```

### 兼容原则

- 旧 artifact 没有 strategy metadata 时，按 `information_density` 读取。
- 新 artifact 写 strategy metadata，但旧消费者可以忽略。
- 任何策略字段都不得成为旧 job 回放失败原因。

### 回滚方式

每个 phase 必须能通过删除新 metadata / helper facade 回到旧行为。

不允许一次性改动：

- candidate generation
- risk gate
- render plan
- packaging plan
- scorecard

## 已落地首切片

截至当前执行状态，第一轮代码切片已经落地，范围仍控制在“只补合同，不改行为”：

1. 已新增 `src/roughcut/edit/strategy_profile.py`。
2. 已把旧 payload 默认归一到 `information_density`。
3. 已在 `cut_analysis / refine_decision_plan` 内透传 `strategy_type / strategy_profile`。
4. 已给当前 rule candidates 归一 `producer_id / strategy_applicability` metadata。
5. 已新增首个共享 `strategy_decisions` helper，并让 `cut_analysis` 的 auto-apply / manual-confirm 判断从散点逻辑收口到统一决策层。
6. 已新增 `editorial_timeline` helper，并把 keep-segment normalize / build / resolve 收口到共享入口。
7. 已新增 `packaging_timeline` helper，并把 variant bundle 的包装字段收成单个 `packaging_timeline` payload。
8. 已开始让 manual-editor、render-start 检查、scorecard 摘要复用 packaging helper，而不是继续平铺读取 render-plan 字段。

本轮明确没有做：

- 新 preset UI；
- 新视频类型；
- 新 scorecard 指标；
- packaging timeline 拆分；
- render plan schema 大改。

## 下一执行顺序

在不扩需求的前提下，后续顺序固定为：

1. 先收掉 `Phase 5` 剩余的 render-plan 平铺读取点，尤其是 `pipeline/steps.py` 内 packaged timeline mapping、transition overlap、intro/insert/outro trailing-gap 这些还可能直接读 flat fields 的位置。
2. 再继续收掉 `Phase 4` / `Phase 5` 剩余的重复 reconstruction 入口，要求 keep/remove 只能通过 `editorial_timeline` helper，包装/effect 只能通过 `packaging_timeline` helper。
3. 给每个新增共享 helper 补最小回归，重点覆盖：legacy flat payload 兼容、nested payload 优先级、manual-editor roundtrip、render packaged mapping。
4. 跑 targeted tests 加一个真实 anchor replay，确认 `information_density` 的 keep/remove、managed auto cuts、subtitle-only change scope 没有漂移。
5. 只有在 `Phase 5` 行为等价迁移闭合后，才进入 `Phase 6` preset 映射；preset 只做入口映射，不得再引入隐藏分支。

当前已完成到：

1. `Phase 0` 当前切片基线验证。
2. `Phase 1` strategy metadata。
3. `Phase 2` candidate producer metadata。
4. `Phase 3` 在 `cut_analysis` 层的首个共享 decision slice。
5. `Phase 4` 在 keep/remove 事实层的首个共享 editorial helper slice。
6. `Phase 5` 在 packaging/effect 读取边界的首个共享 helper slice。

当前正在执行的代码切片应限定为：

1. `pipeline/steps.py` 中剩余的 flat packaging consumer 收口。
2. render/manual-editor/bundle 的 helper 消费对齐。
3. 对应 focused regression 与一个真实 job anchor 复验。

禁止跳步进入：

- `step_demonstration` 新证据接入；
- `experience_and_mood / event_highlight / narrative_assembly` 新策略实现；
- 包装特效编排大改；
- scorecard / golden schema 再扩张。

## 风险与控制

| 风险 | 控制 |
|---|---|
| 新策略字段改变旧行为 | Phase 1 只透传 metadata，不参与裁决 |
| 候选协议变成第二套规则注册表 | 复用 `RuleDefinition`，producer metadata 只做外层归一化 |
| 包装时间线误改剪辑时间线 | 明确 `Packaging Timeline` 只能消费 `Editorial Timeline` |
| 并行线程互相覆盖主链文件 | 当前主链文件只保留一条编码线程；其它线程最多做只读审阅或后续合并 |
| golden/scorecard 再次膨胀 | 不新增主指标；只有真实失败解释不了时才扩字段 |
| 多题材扩展过早 | 第二策略域必须等 `information_density` 等价迁移完成 |

## 完成标准

第一阶段完成时应满足：

1. 当前链路可被明确标记为 `information_density`。
2. 旧 job / 旧 artifact / 旧 manual-editor flow 兼容。
3. candidate 输出具备 producer metadata，但现有规则计数不漂移。
4. risk gate 可读取 strategy profile，但默认行为与当前一致。
5. editorial timeline 和 packaging timeline 的边界在代码 helper / artifact metadata 中可见。
6. 至少一个真实信息密度型 anchor 通过 `edit_plan` replay。

## 后续路线

完成第一阶段后，再进入：

1. `step_demonstration` evidence 接入；
2. screen activity candidate producer；
3. 包装编排 timeline 独立 artifact；
4. `experience_and_mood` 的视觉/环境声保护；
5. `event_highlight` 的高光候选；
6. `narrative_assembly` 的多素材结构组装。

每一步都必须先新增 evidence / candidate，再交给 strategy gate 裁决，不能直接写最终时间线。
