# 字幕断句与呈现逻辑通用重构方案

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

## 背景

当前字幕链路的核心行为是：

- `src/roughcut/speech/postprocess.py` 的 `split_into_subtitles()` 负责把转写结果切成展示单元。
- `subtitle_postprocess` 阶段产出首版字幕。
- `edit_plan` 阶段会调用 `polish_subtitle_items(..., allow_llm=True)`，但该接口只做逐条文本精修，不会重建字幕边界。

这导致系统的实际能力是“规则切条 + 逐条润色”，而不是“面向展示单元的语义断句”。在真实成片字幕中，问题已经不是少量漏网边界，而是存在系统性缺陷：

- 会把一个词、量词短语或固定搭配拆成前后两条。
- 会把一句话拆成多条残句，但每条都被补成句号，掩盖失败边界。
- 会出现 3 到 5 条连续碎裂，现有 pairwise merge / rebalance 无法恢复。
- 规则评分只看相邻条目，缺少窗口级别的整体最优重切分能力。

## 目标

本次重构目标不是继续追加启发式补丁，而是建立一套通用、可验证、可扩展的字幕构成框架。

目标分为四层：

1. 先保证“不能断错”
   - 禁止断词、断固定短语、断量词结构、断附着成分。
2. 再保证“句子基本闭合”
   - 展示单元应尽量是完整意群，而不是残句碎片。
3. 再保证“适配展示”
   - 同时满足横竖屏字数、时长、阅读速度、停顿感。
4. 最后才是“文本精修”
   - 错字、术语、数字、标点修正只能在结构稳定后进行。

## 当前问题诊断

当前实现有四个结构性问题：

### 1. 切分职责混杂

`split_into_subtitles()` 同时负责：

- 候选切点选择
- 邻接合并
- 边界重平衡
- 清理去重

这让逻辑很难扩展，也难以解释“为什么这条被切在这里”。

### 2. 只有相邻 pair 修补，没有窗口级重切分

现有 `_merge_continuation_entries()`、`_rebalance_semantic_pair()`、`_should_bridge_semantic_gap()` 都是邻接修补。它们能解决：

- `一 / 个`
- `可以把你的 / 小药丸`

但对于这种连续碎裂基本无能为力：

- `产品的味道大家。`
- `看选择很多而且以我。`
- `个人体验来说其实它的。`
- `口气清新的能力还是相当。`
- `不错的但是劲儿特别大。`

这类问题本质上需要对一个窗口内的 3 到 5 条重新求最优分段，而不是继续二元修补。

### 3. 标点补齐发生得太早

现在很多未闭合碎片会被规范成带 `。` 的条目，例如：

- `犯困或者说需。`
- `直冲天灵盖的那种感。`
- `女朋友或者说你的。`

这会把“断句失败”伪装成“句子结束”，让后续规则和人工都更难识别问题。

### 4. LLM 接入点不对

现有 `polish_subtitle_items()` 的输入输出是逐条 `index -> text_final`，不能：

- 合并两条
- 拆成三条
- 调整边界时间

所以即使启用 LLM，也无法承担“智能断句”的核心职责。

## 重构原则

### 原则 1：结构先于润色

先生成稳定的展示单元，再做文本纠错。禁止反过来做。

### 原则 2：边界决策显式化

每个切点都应有可解释的来源：

- 强制禁止切
- 强制允许切
- 候选可切但分数较低
- LLM 复判后改判

### 原则 3：窗口级优化替代局部打补丁

对复杂边界，允许在局部窗口内重切分，不再局限于“上一条 + 下一条”。

### 原则 4：规则保底，LLM 负责疑难边界

稳定、低成本、可重复的问题继续规则处理；模糊、跨句法、需要上下文理解的问题交给 LLM，但必须有严格约束和回退。

## 目标架构

建议把字幕生成拆成五层。

### 第一层：词流标准化

输入：ASR 段落 + word timing。

产出：统一词流 token 序列，每个 token 包含：

- `text`
- `start`
- `end`
- `segment_index`
- `word_index`
- `token_type`
- `protected_group`
- `prosody_pause_before`
- `prosody_pause_after`

这里要新增一层轻量词法标注，不依赖完整 NLP，也不要求高成本模型。

最低需要识别的 token/group：

- 数词
- 量词
- 专有名词
- 英文型号
- 口头禅
- 附着词
- 连词
- 结构助词
- 固定搭配片段

核心目的：把“不能断”的单位先表示出来，而不是事后猜。

### 第二层：边界候选图

在 token 之间构建边界图，每个边界输出结构化特征：

- `hard_block`
- `soft_block`
- `soft_allow`
- `pause_score`
- `syntax_score`
- `display_score`
- `term_split_penalty`
- `fragment_penalty`
- `continuation_bonus`

其中：

- `hard_block` 用于绝对禁止切分。
- `soft_block` 表示强烈不建议切分。
- `soft_allow` 表示这里天然适合作为展示停顿。

强制禁止切分的典型规则：

- 数词 + 量词
- 半个词被切开
- 英文型号被切开
- 固定词组被切开
- 左侧以附着成分结尾且右侧无法独立开句
- 右侧从明显挂接成分开始

### 第三层：窗口级分段求解

这层替代当前的“切完后 merge / rebalance”主逻辑。

建议采用两阶段求解：

1. 全局初切
   - 在 token 流上做 DP/Viterbi，求一个满足字数、时长、阅读速度的基础最优路径。
2. 局部重切分
   - 对低置信度边界触发窗口重算，窗口大小 3 到 6 条。

局部重切分的输入是一个字幕窗口，输出不是“改一个 index 的 text”，而是新的展示单元列表：

- `[{start_token, end_token, reason_tags}]`

这样才能修复连续碎裂。

### 第四层：疑难边界 LLM 复判

LLM 不直接全量生成字幕，只处理规则置信度低的窗口。

触发条件建议包括：

- 窗口内存在多个未闭合残句
- 连续两个以上可疑边界
- 规则无法在时长与闭合之间取得平衡
- 保护词组冲突
- 生成结果被结构校验判为失败

LLM 的任务应该是“边界决策”，不是“自由改写”。

建议的输入输出：

- 输入：当前窗口 token 列表、时间、候选切点、禁止切点、展示限制。
- 输出：`{"cuts":[5, 12, 19], "rationale_tags":["merge_fragment","keep_measure_phrase"]}`

或者：

- 输出每个边界的标签：`keep_together` / `allow_break` / `must_break`

约束：

- 不允许添加信息
- 不允许删减信息
- 不允许自由改写语序
- 只允许在 token 边界上切
- 输出后必须经过本地约束校验

### 第五层：结构稳定后的文本精修

`polish_subtitle_items()` 应保留，但职责要收缩：

- 纠错
- 术语修正
- 数字展示规范化
- 标点整理

禁止再承担边界修复职责。

同时需要增加一个约束：

- 对未闭合句尾禁止盲目补 `。`

即：只有当结构层明确认定该条为闭合展示单元时，才允许补终止标点。

## 呈现逻辑重构

断句和呈现不能再混为一谈。建议把“语义单元”与“展示单元”区分开来。

### 语义单元

表示一句话在语义上怎么切。

### 展示单元

表示这一句在当前视频形态下如何显示。

这意味着：

- 一套语义边界可以在横版、竖版上投影成不同的展示条数。
- 但禁止跨语义边界乱合，也禁止在语义单元内部切出残句。

建议新增一个“展示投影器”：

- 输入：语义单元
- 输出：适合横版或竖版的具体字幕条目

投影规则：

- 优先保证完整短语
- 再控制单条字数
- 再控制阅读速度
- 必要时允许在语义单元内部二次分行，但不能切出残句

## 数据模型建议

建议在内存结构中增加两个中间模型。

### `BoundaryDecision`

- `left_token_index`
- `right_token_index`
- `decision`
- `score`
- `reason_tags`
- `source`

其中 `source` 为：

- `rule`
- `window_solver`
- `llm`
- `fallback`

### `SemanticSubtitleUnit`

- `start`
- `end`
- `token_start`
- `token_end`
- `text_raw`
- `closure_state`
- `reason_tags`

其中 `closure_state` 至少包含：

- `closed`
- `continuation`
- `attached_prefix`
- `attached_suffix`

## 代码改造建议

### 1. `postprocess.py`

保留现有基础工具函数，但拆分主流程：

- `build_subtitle_token_stream()`
- `build_boundary_features()`
- `solve_initial_subtitle_units()`
- `refine_low_confidence_windows()`
- `project_semantic_units_to_display_units()`
- `cleanup_display_units()`

现有函数去向建议：

- `_flatten_segment_words()` 可以保留，升级成 token stream 构建入口。
- `_semantic_boundary_quality()` 保留，但降级为特征之一，不再单独决定边界。
- `_merge_continuation_entries()` 与 `_rebalance_semantic_pair()` 逐步退出主链路，改成兼容 fallback。
- `_split_with_words()` 和 `_segment_subtitles_from_global_words()` 要迁移到“求解器”模型下。

### 2. `steps.py`

在 `run_subtitle_postprocess()` 中引入新分层：

- 先跑规则求解
- 对低置信度窗口可选跑 `llm_boundary_refine`
- 保存结构元数据供后续分析

在 `run_edit_plan()` 中：

- `polish_subtitle_items()` 只处理文本
- 不再承担结构修补

### 3. `content_profile.py`

把逐条字幕精修 prompt 约束得更窄：

- 删除“明显断句问题”这种模糊表述
- 明确禁止通过改写掩盖结构错误

如果要保留 LLM 结构修复，应新增独立接口，例如：

- `refine_subtitle_boundaries()`

而不是继续复用 `polish_subtitle_items()`。

## 验证体系

必须建立比当前更严格的回归标准，否则改完很容易产生新的隐性回归。

### 一类：结构约束测试

新增自动检查：

- 禁止字幕以明显挂接前缀开头
- 禁止字幕以明显未闭合结尾收束
- 禁止数词量词拆裂
- 禁止英文型号拆裂
- 禁止连续两条都处于 `continuation` 状态

### 二类：窗口级回归样本

针对真实失败模式建立参数化测试，覆盖：

- 断词
- 断量词
- 断固定搭配
- 断句中间插入句号
- 3 条以上连续碎裂
- 横版和竖版不同展示投影

### 三类：真实语料基准集

新增一个字幕断句 benchmark，来源于已确认问题的真实任务。

每条样本至少记录：

- transcript words
- 期望切分结果
- 是否允许多种合法答案
- 错误类型标签

建议先覆盖：

- LuckyKiss / EDC
- 开箱类口播
- 参数介绍类
- 对比评测类
- 带英文型号和数字规格的视频

### 四类：线上质量指标

建议把以下指标写入 step metadata，便于看板化：

- `fragment_start_count`
- `fragment_end_count`
- `protected_term_split_count`
- `consecutive_fragment_window_count`
- `llm_refine_window_count`
- `llm_refine_accept_count`
- `avg_chars_per_subtitle`
- `avg_reading_speed`

## 分阶段落地计划

### Phase 1：结构解耦

目标：

- 把切分、重切分、润色分层。
- 停止把 `edit_plan` 当成断句补锅层。

交付：

- 新中间模型
- 新主流程骨架
- 现有规则迁移

### Phase 2：窗口级重切分

目标：

- 替换 pairwise merge / rebalance 的主导地位。

交付：

- 窗口求解器
- 低置信度边界识别
- 多条碎裂回收能力

### Phase 3：LLM 边界复判

目标：

- 让 LLM 真正参与“智能断句”，但只处理疑难窗口。

交付：

- 边界复判 prompt
- 结构化 JSON 输出
- 本地约束校验
- 超时和回退机制

### Phase 4：展示投影器

目标：

- 分离语义单元和横竖屏呈现。

交付：

- 语义单元到展示单元的投影
- 横竖屏差异化参数
- 阅读速度校验

### Phase 5：基准集与质量面板

目标：

- 让字幕质量退化可见、可测、可阻断。

交付：

- benchmark 数据
- 结构指标埋点
- 回归阈值

## 验收标准

重构完成后，至少满足以下标准：

- 真实任务中“断词 / 断量词 / 断固定搭配”问题显著下降。
- 连续碎裂窗口可以被自动回收，不再依赖人工抽查。
- `subtitle_postprocess` 的结果本身就可直接用于成片，不再指望 `edit_plan` 补救结构。
- LLM 是否启用只影响疑难边界质量，不影响基本可用性。
- 任何字幕条目若被补终止标点，必须能通过闭合状态校验。

## 推荐实施顺序

建议严格按下面顺序实施：

1. 先拆职责和中间模型。
2. 再上窗口级重切分。
3. 再接 LLM 边界复判。
4. 最后做展示投影和更细的风格化策略。

如果顺序反过来，例如先上 LLM 再补结构层，最终只会得到一个更难调、更难解释、成本更高的系统。
