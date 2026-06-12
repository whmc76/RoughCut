# RoughCut 通用自动剪辑策略边界

日期：2026-06-11

## 定位

RoughCut 的项目初衷是做“任何人都能用的 90 分全自动素材剪辑发布工具”。

口播、开箱、测评不是产品边界，只是第一类测试题材和第一批真实需求。当前围绕 ASR、语言矫正、字幕映射、候选删减和渲染发布建立的链路，应被视为通用自动剪辑发布引擎的第一套可验证实现，而不是 RoughCut 的最终能力上限。

RoughCut 应统一的是工程底座，不是统一剪法。

```text
统一底座 + 类型化剪辑策略 + 隔离的包装编排 / 发布
```

## 核心原则

### 1. 通用底座统一

所有题材都应复用同一套主合同：

```text
素材接入
  -> 证据层
  -> 内容理解层
  -> 候选生成层
  -> 策略裁决 / 风险门禁
  -> 自动组装 / 渲染计划
  -> 包装编排 / 发布
```

底座负责让系统可解释、可回放、可测试、可持续扩展。

### 2. 剪辑策略类型化

不同剪辑策略对“好剪辑”的定义不同。常见视频形态不是策略本身，只是会映射到一种主策略，必要时再叠加辅助策略。

- 信息密度型追求高效表达、低废话、强字幕同步。
- 步骤演示型追求步骤完整、操作可跟随、无效等待压缩。
- 体验氛围型追求沉浸、空间感、环境声和情绪节奏。
- 事件高光型追求事件峰值、反应、冲突、结果和可切片传播。
- 叙事组装型追求素材间关系、结构组织、起承转合和完整成片。

因此同一个候选信号在不同策略下可以得出不同决策。无语音片段在信息密度型策略里可能应裁掉，在体验氛围型策略里可能是核心体验。

### 3. 候选生成和最终裁决分离

候选生产器只负责提出可能动作，不能直接改最终时间线。

例如：

- `pause_trim_candidate`
- `filler_delete_candidate`
- `screen_idle_trim_candidate`
- `scenic_keep_candidate`
- `highlight_candidate`
- `chapter_candidate`
- `reorder_candidate`

最终是否删除、保留、压缩、切片或重排，必须由策略裁决和风险门禁决定。

### 4. 剪辑、包装编排和发布分层隔离

剪辑能力改变内容或时间线：

- 删除片段
- 保留片段
- 压缩停顿
- 合并片段
- 重排片段
- 选择高光
- 自动组装成片

包装能力分为两类。

第一类不改变输出时间轴，只改变发布物料或呈现参数：

- 标题
- 封面
- 简介
- 标签
- 字幕样式
- 章节名
- 平台发布文案

第二类会影响输出时间轴或渲染结构，必须进入独立的 `Packaging Timeline / Effect Plan` 阶段：

- 片头片尾
- 转场
- 特效
- BGM 铺底和卡点
- 花字 / 贴纸 / 强调框
- 横竖屏重构
- 平台版本裁切

包装编排可以读取已经定稿的剪辑结果、内容画像和平台目标，但不能反向偷偷改变 `Editorial Timeline` 里的保留/删除决定。如果包装需要调整节奏，只能输出显式的包装时间轴、效果计划或人工复核建议，并由合同记录其影响范围。

## 策略类型

产品上可以提供模式，但架构上不应为每种模式创建一条隐藏流水线。模式应只是 `Editing Strategy Profile`。

### 信息密度型

目标是减少信息摩擦，提高密度。

```json
{
  "strategy_type": "information_density",
  "pace": "tight",
  "speech_priority": "high",
  "visual_priority": "medium",
  "silence_policy": "trim_unvoiced_gaps",
  "auto_delete_threshold": "moderate",
  "must_preserve": [
    "key_claim",
    "product_detail",
    "comparison",
    "conclusion"
  ]
}
```

常见视频形态：

- 口播
- 开箱
- 测评
- 知识讲解
- 观点评论

### 步骤演示型

目标是步骤可跟随，减少无效等待。

```json
{
  "strategy_type": "step_demonstration",
  "pace": "medium_tight",
  "speech_priority": "high",
  "screen_activity_priority": "high",
  "silence_policy": "trim_only_when_screen_idle",
  "auto_delete_threshold": "conservative",
  "must_preserve": [
    "screen_change",
    "cursor_action",
    "code_or_ui_change",
    "step_explanation"
  ]
}
```

常见视频形态：

- 录屏教程
- 软件演示
- 操作教学
- 手工制作
- 产品安装 / 调试

### 体验氛围型

目标是保留体验、氛围和情绪。

```json
{
  "strategy_type": "experience_and_mood",
  "pace": "medium_slow",
  "speech_priority": "medium",
  "visual_priority": "high",
  "ambient_audio_priority": "high",
  "silence_policy": "preserve_when_visual_or_ambient_value",
  "auto_delete_threshold": "very_conservative",
  "must_preserve": [
    "scenic_shot",
    "reaction_shot",
    "ambient_sound",
    "location_transition",
    "emotional_pause"
  ]
}
```

常见视频形态：

- Vlog
- 旅行
- 探店
- 风景
- 日常记录

### 事件高光型

目标是发现可传播片段和事件峰值。

```json
{
  "strategy_type": "event_highlight",
  "pace": "variable",
  "speech_priority": "medium",
  "visual_priority": "high",
  "audio_energy_priority": "high",
  "auto_delete_threshold": "conservative",
  "must_preserve": [
    "reaction",
    "conflict",
    "result",
    "surprise",
    "audience_response"
  ]
}
```

常见视频形态：

- 直播切片
- 游戏
- 活动
- 访谈片段
- 比赛 / 发布会

### 叙事组装型

目标是把多段素材组织成完整成片。

```json
{
  "strategy_type": "narrative_assembly",
  "pace": "structured",
  "speech_priority": "variable",
  "visual_priority": "high",
  "sequence_priority": "high",
  "auto_delete_threshold": "conservative",
  "must_preserve": [
    "setup",
    "development",
    "turning_point",
    "payoff",
    "closing"
  ]
}
```

常见视频形态：

- 多段素材自动组片
- 活动回顾
- 旅行合集
- 产品宣传粗剪
- 项目过程记录

## 常见视频形态映射

| 常见视频形态 | 主策略类型 | 常见辅助策略 | 剪辑逻辑 |
|---|---|---|---|
| 口播 / 观点 / 知识讲解 | 信息密度型 | 叙事组装型 | 以语义和语言顺滑为主，压缩停顿、重复和低信息表达，保留观点、结论和论证链 |
| 开箱 / 测评 | 信息密度型 | 步骤演示型、体验氛围型 | 压缩废话但保护产品细节、展示动作、对比结果和体验反应 |
| 录屏教程 / 软件演示 | 步骤演示型 | 信息密度型 | 保留操作步骤和屏幕变化，压缩无操作等待，不能因为无语音删掉关键操作 |
| 手工 / 安装 / 调试 | 步骤演示型 | 体验氛围型 | 保留过程连续性、手部动作和结果验证，压缩重复等待和失败旁枝 |
| Vlog / 旅行 / 探店 | 体验氛围型 | 叙事组装型 | 保留环境、节奏、情绪和地点转换，不能把空镜、环境声、反应镜头简单当低信息 |
| 风景 / 日常记录 | 体验氛围型 | 事件高光型 | 以视觉和声音体验为主，删除阈值保守，更多做片段选择和节奏编排 |
| 直播切片 / 访谈片段 | 事件高光型 | 信息密度型 | 找观点、冲突、反应和结果，输出可独立传播的片段，避免只按全文压缩 |
| 游戏 / 比赛 / 活动 | 事件高光型 | 体验氛围型 | 保护铺垫、紧张等待、爆点和反应，不能把静默等待一概裁掉 |
| 多段素材合集 / 宣传粗剪 | 叙事组装型 | 体验氛围型、事件高光型 | 先定结构和素材角色，再做片段选择、排序、转场和包装编排 |

## 决策示例

同一个候选：

```json
{
  "candidate_id": "cand_silence_0042",
  "type": "trim",
  "raw_signal": "no_speech",
  "start": 42.0,
  "end": 46.0,
  "duration": 4.0
}
```

在不同策略下可能得到不同裁决：

| 策略 | 裁决 | 原因 |
|---|---|---|
| 信息密度型 | 自动压缩 | 无语音且无关键画面，符合紧凑节奏 |
| 步骤演示型 | 条件压缩 | 屏幕或操作无变化时压缩，有操作变化时保留 |
| 体验氛围型 | 保留或人工候选 | 可能是风景、环境声或情绪停顿 |
| 事件高光型 | 保留或截断 | 需要看是否是紧张等待、反应或事件铺垫 |
| 叙事组装型 | 取决于结构角色 | 如果是转场、铺垫或收束，可能需要保留 |

## 插入当前主链的位置

当前信息密度型第一实现不需要推倒重来，应逐步泛化：

| 当前概念 | 泛化方向 |
|---|---|
| `ASR Evidence` | `Speech Evidence`，属于更大的 `Evidence Layer` |
| `Canonical Transcript` | 语音证据的标准化事实层 |
| `Subtitle Projection` | 语音/字幕展示派生层 |
| `Edit Candidate Generation` | `Candidate Producers` |
| `Decision Audit And Risk Gate` | 全题材共享的策略裁决和风险门禁 |
| `Render Plan` | 自动组装后的统一渲染输入 |
| `Platform Package` | 包装物料、包装时间轴和发布层 |

新增题材时，优先增加证据生产器、候选生产器和策略配置，而不是新增第二条剪辑流水线。

## 推荐推进顺序

### 第一阶段：信息密度型

范围：

- 口播
- 开箱
- 测评
- 知识讲解

目标：

- 把当前语言清理、字幕映射、候选删减、风险门禁做稳。
- 形成可解释的 90 分自动初剪底座。

### 第二阶段：步骤演示型

范围：

- 录屏教程
- 软件演示
- 操作教学

新增能力：

- screen activity evidence
- OCR / UI state evidence
- 操作步骤保护
- 屏幕静止等待压缩

### 第三阶段：体验氛围型

范围：

- Vlog
- 旅行
- 探店
- 风景

新增能力：

- scenic / reaction / ambient evidence
- 氛围片段保护
- 节奏曲线而非语音密度优先
- 更保守的自动删除门禁

### 第四阶段：事件高光型

范围：

- 直播
- 游戏
- 活动
- 访谈切片

新增能力：

- highlight candidate producer
- 情绪 / 音频能量 / 视觉峰值分析
- 可独立传播片段导出

### 第五阶段：叙事组装型

范围：

- 多段素材自动组片
- 活动回顾
- 旅行合集
- 产品宣传粗剪

新增能力：

- 跨素材聚类
- 叙事角色识别
- 自动组装结构
- 片段重排候选
- 包装时间轴 / 转场 / 特效计划

## 当前收口工作的关系

当前 `C1-C6` 自动剪辑收口不是偏离通用目标，而是在修通用底座：

- `C1` 保证证据和展示不混用。
- `C2` 保证人工复核不是第二条隐藏流水线。
- `C3` 保证候选生成和风险门禁统一。
- `C4` 保证渲染运行时可回放。
- `C5` 保证质量判断有 golden/batch 证据。
- `C6` 才开始做更强的智能删减质量增强。

在 `C1-C5` 没有稳定前，不应过早添加体验氛围型、事件高光型、叙事组装型等复杂策略，否则会把策略差异误写成新一轮隐藏分支。

## 结论

RoughCut 的长期边界是通用自动剪辑发布系统，不是口播工具。

但通用不意味着所有视频套同一套剪法。正确方向是：

```text
统一证据和候选合同
统一风险门禁和渲染发布
按策略类型配置剪辑裁决
按平台配置包装编排和发布
```

这样 RoughCut 可以从信息密度型任务平滑扩展到步骤演示型、体验氛围型、事件高光型和叙事组装型任务，同时避免把某一种视频形态的剪法错误套到所有题材上。
