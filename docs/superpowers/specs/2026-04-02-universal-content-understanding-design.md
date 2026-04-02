# RoughCut Universal Content Understanding Design

## Goal

把 RoughCut 现有偏开箱、偏规则注入的 `content_profile` 链路，重构为一个面向所有视频类型的通用智能理解框架。

新框架的核心原则是：

- 当前视频证据优先
- LLM 负责统一推理、提炼和裁决
- 联网搜索与内部数据库检索只做弱佐证
- 规则层只负责证据采集、标准化、检索编排和保守守门

## Why This Change

当前链路存在三个根本问题：

### 1. Final Fields Are Still Rule-Injected

虽然已有 LLM 推理步骤，但 `subject_type`、`video_theme` 等关键字段在进入 LLM 前已经被规则、词表、历史记忆和领域映射预填，导致最终结果并不是“LLM 基于完整证据的独立判断”，而是“规则先下注，LLM 再补全”。

这会直接造成错误类型被写死，例如把无关任务错误判成 `EDC手电`。

### 2. Existing Model Is Too Narrow

现有字段与 heuristics 仍然围绕“开箱产品识别”组织：

- `subject_brand`
- `subject_model`
- `subject_type`
- `video_theme`

这对于教程、评论、新闻、Vlog、游戏、美食、AI 工作流、软件演示等视频都不够自然，导致内部逻辑不断叠加特例。

### 3. Verification Layer Lacks a Unified Reasoning Loop

现在的搜索、memory、entity graph、glossary、OCR、字幕都分散在不同阶段使用，没有统一的“证据 -> 推理 -> 检索 -> 再推理 -> 保守输出”闭环。

## Product Decision

本次重构采用以下明确决策：

- 最终内容理解结果由 LLM 主判
- 规则层不得再直接生成最终的 `subject_type / video_theme / summary / content_domain / video_type`
- 联网搜索与内部数据库检索都作为弱佐证层，不得越权覆盖当前视频证据
- 该框架面向所有视频类型，而不是仅服务开箱/EDC
- 证据不足时，系统必须允许保守留空并待审

## Design Principles

### 1. LLM Is the Final Judge

所有对外可见的核心理解字段，由 LLM 基于完整证据包统一输出。

### 2. Retrieval Assists, Never Overrides

联网搜索结果、数据库历史记录、confirmed entity、field preference、glossary、entity graph 都只能作为“辅助佐证”，不能绕过当前视频证据直接创建最终字段。

### 3. Current Video Evidence Is the Source of Truth

当前任务中的字幕、OCR、抽帧、文件名、visible text、媒体元数据，是第一优先级输入。

### 4. Generalize Around Understanding, Not Product Identity

框架应先抽象“视频形式、内容领域、主体对象、主题焦点、叙事目标”，再兼容产品品牌/型号这类细分信息，而不是反过来以开箱产品模型统治全局。

### 5. Conservative Failure Mode

任何冲突、弱证据、无佐证、跨源互斥，都应该让输出进入 `needs_review`，而不是由规则层继续猜一个“最像的”。

## Target Architecture

新链路统一为五个阶段：

### Stage 1: Evidence Bundle

输入来源：

- `subtitle_items`
- `transcript_excerpt`
- OCR 识别结果
- 抽帧视觉描述或视觉 hints
- 文件名与路径
- 媒体基础元数据
- 当前任务已有人工修正

输出：

- `EvidenceBundle`

职责：

- 收集原始证据
- 对字幕/OCR/文件名做标准化
- 保留证据来源、片段、位置、时间轴
- 生成供 LLM 使用的结构化证据上下文

禁止：

- 在这个阶段直接生成最终 `video_type / content_domain / subject_type / video_theme / summary`

### Stage 2: LLM Primary Inference

LLM 接收完整 `EvidenceBundle`，做首次统一理解，直接输出通用理解结构。

输出职责包括：

- 判断视频形式
- 判断内容领域
- 判断主体对象
- 提炼主题焦点
- 生成摘要、钩子、互动问题、搜索查询
- 标记不确定性、冲突点、待审原因

这一阶段是主判阶段。

### Stage 3: Hybrid Verification

基于 LLM 首轮结果，触发混合佐证：

- 联网搜索
- 内部数据库检索

两者返回的检索结果统一回灌给 LLM，让 LLM 做二次验证。

这一步只做：

- 佐证
- 反证
- 冲突发现
- 置信度修正
- 待审判断

这一步不做：

- 独立于 LLM 的规则改判

### Stage 4: LLM Verification Resolution

LLM 结合：

- 当前视频证据
- 联网搜索结果
- 内部数据库检索结果

输出最终理解结果：

- 保留哪些字段
- 清空哪些字段
- 哪些字段可信
- 为什么需要人工审核

### Stage 5: Conservative Guard

规则层最后只负责执行守门策略：

- schema 校验
- 长度与格式规范
- 冲突字段清空
- `needs_review` 兜底
- 向下游兼容旧接口

规则层不得在这个阶段生成新的主体、主题、领域或类型。

## New Canonical Output Schema

现有 `content_profile` 以产品身份为中心，不适合通用化。新 schema 调整为“通用理解层 + 兼容层”。

### Universal Layer

新增统一结构 `content_understanding`：

- `video_type`
  - 视频形式，如 `unboxing / tutorial / commentary / vlog / gameplay / food / news / interview / showcase / mixed`
- `content_domain`
  - 内容领域，如 `edc / tools / tech / ai / food / finance / sports / travel / lifestyle / mixed`
- `primary_subject`
  - 当前视频主要对象的自然语言描述
- `subject_entities`
  - 主体实体列表，允许包含品牌、型号、软件名、店名、人物、作品、机构等
- `video_theme`
  - 视频核心主题
- `summary`
  - 通用摘要
- `hook_line`
  - 标题钩子
- `engagement_question`
  - 互动问题
- `search_queries`
  - 用于后续验证的查询词
- `evidence_spans`
  - 关键判断所依赖的字幕/OCR/视觉/文件名片段
- `uncertainties`
  - 尚未确认的疑点
- `confidence`
  - 全局或分字段置信度
- `needs_review`
  - 是否需要人工审核
- `review_reasons`
  - 待审原因

### Compatibility Layer

现有字段仍保留一段迁移期，以兼容现有 API/UI：

- `subject_brand`
- `subject_model`
- `subject_type`
- `subject_domain`
- `content_kind`
- `video_theme`
- `summary`
- `hook_line`
- `engagement_question`
- `search_queries`

兼容规则：

- 这些字段从 `content_understanding` 映射生成
- 不再反向驱动主推理
- 若视频并非产品/品牌中心内容，则兼容字段允许为空

## Evidence Authority Model

为了防止跨视频污染，定义统一权重顺序：

### Level A: Current Video Direct Evidence

- 字幕
- OCR
- 画面内容
- visible text
- 文件名中可验证的直接信息

权限：

- 可以参与 LLM 主判
- 可以被用于最终字段佐证

### Level B: Current Task Derived Context

- 当前任务的结构化 hints
- 当前任务的抽帧聚类结果
- 当前任务的中间摘要

权限：

- 只能作为当前视频证据的辅助组织形式
- 不能跳过视频证据直接生成最终字段

### Level C: Hybrid Retrieval Evidence

- 联网搜索结果
- 内部数据库命中结果

权限：

- 只能做弱佐证或反证
- 当与当前视频直接证据冲突时，不能单独覆盖当前视频结论

### Level D: Historical Memory and Correction Assets

- confirmed entities
- user memory
- field preferences
- phrase preferences
- glossary normalization
- entity graph

权限：

- 只能帮助检索召回、命中后规范化、审核解释
- 不能直接创建最终主体字段

## Hybrid Verification Strategy

### Online Search

联网搜索用于找公开可验证信息，例如：

- 品牌官网
- 产品页
- 软件官网/发布页
- 平台页面
- 新闻报道
- 评测文章

用途：

- 验证品牌/型号/术语是否真实存在
- 验证主题命名是否准确
- 验证 LLM 是否把对象判错品类

### Database Retrieval

内部数据库检索范围包括：

- 历史 jobs 的已确认内容画像
- entity graph
- 人工修正记录
- OCR/字幕证据索引
- 已确认实体别名

用途：

- 提供内部同款命中或相似案例
- 提供别名、错写、历史纠正轨迹
- 帮助 LLM 判断是否为同类内容

限制：

- 历史命中只能作为弱证据
- 当前视频没有直接证据时，数据库结果不能替代当前判断

## LLM Responsibilities

新框架中，LLM 需要承担三个明确职责：

### 1. Multimodal Synthesis

综合字幕、OCR、画面、文件名、元数据，形成第一轮理解结果。

### 2. Retrieval-Aware Verification

阅读联网搜索和数据库检索结果，判断首轮结果是否得到支持或遭遇反证。

### 3. Conservative Finalization

在证据不足、冲突严重或领域不明时，保守输出空值并给出待审理由。

## What Must Be Removed

以下旧行为必须从最终链路中移除：

- 根据词表直接写死 `EDC手电 / EDC折刀 / 多功能工具钳 / EDC机能包`
- 根据 memory/confirmed entity 直接创建 `subject_type`
- 根据品牌或型号映射自动补全最终类型
- 根据 workflow template 或 domain pack 直接推出具体主体
- 让 enrichment 回写或覆盖主体结论

## Migration Plan

### Phase 1: Introduce Universal Schema

- 定义 `content_understanding` 新结构
- 为旧 API 保留兼容字段映射
- 扩展前后端类型定义与序列化结构

### Phase 2: Replace Rule-First Inference with LLM-First Inference

- 删除规则层对最终字段的直接注入
- 保留规则层做 evidence bundle 构建
- 接入统一 LLM 主判入口

### Phase 3: Add Hybrid Verification Loop

- 抽象联网搜索与数据库检索接口
- 让 LLM 二次读取混合检索结果并修正结论
- 新增 `needs_review / review_reasons / confidence / uncertainties`

### Phase 4: Compatibility and UI Adoption

- 让现有 UI 使用兼容字段继续工作
- 新 UI 逐步展示 `video_type / content_domain / evidence_spans / review_reasons`
- 审核页优先展示“证据链”和“待审原因”

### Phase 5: Remove Legacy Injection Paths

- 删除旧 `subject_type` heuristics
- 删除旧 `video_theme` 强制兜底注入
- 删除开箱/EDC 特化的主路径逻辑
- 把 memory、glossary、entity graph 降级为弱佐证或规范化辅助

## Testing Strategy

### Unit Tests

必须覆盖以下场景：

1. 当前视频没有手电证据时，不得因历史记忆或旧 alias 被判成 `EDC手电`
2. 教程视频可以输出软件/功能/工作流类主体，而不是强行走产品开箱 schema
3. 新闻/评论/Vlog 等非产品视频允许 `subject_brand / subject_model` 为空，但 `content_understanding` 仍完整
4. 联网搜索与数据库检索命中旧实体时，只能弱佐证，不能独立覆盖当前视频结论
5. 当前视频证据与外部结果冲突时，系统进入 `needs_review`
6. enrichment 不得反向修改 LLM 已确定的主体理解

### Regression Tests

必须补齐以下回归：

- 无手电证据的视频不再误识别为手电
- 工具钳/机能包/折刀/软件教程等互不再被硬规则串扰
- 混合类型视频不会被单一规则模板强行定型
- 历史数据库里存在同款已确认记录，也不能在当前视频无证据时直接套用

### Integration Tests

验证完整闭环：

- `EvidenceBundle -> LLM 主判 -> 混合检索 -> LLM 二次验证 -> Guard`
- API 输出兼容
- 审核页可展示待审原因与证据链
- 旧包装流程在兼容字段存在时仍可工作

## Acceptance Criteria

- 最终 `video_type / content_domain / video_theme / summary` 由 LLM 主判生成
- 规则层不再直接写入具体产品类型
- 联网搜索与数据库检索同时纳入统一佐证框架
- 历史确认实体只作为弱佐证
- 框架可覆盖非开箱视频，而不是继续围绕产品开箱建模
- 在证据不足或冲突时，系统会保守待审，而不是强行猜测

## Non-Goals

本轮不包含：

- 所有 UI 的一次性全面重写
- 所有 packaging 文案策略重做
- 搜索 provider 的全面替换
- 领域 taxonomy 的再次大规模扩表

这些仅在支撑新框架时做必要改动。

## Expected Outcome

重构后，RoughCut 的内容理解链路应从“规则堆叠的半自动识别器”，升级为“以当前视频证据为核心、由 LLM 主判、由混合检索弱佐证、对所有视频类型通用的智能理解框架”。

短期内，自动确认率可能因为更保守而下降；但误判、跨视频污染和错误类型写死的问题应显著收敛，且后续扩展到更多视频类型时不再需要继续堆叠领域特例。
