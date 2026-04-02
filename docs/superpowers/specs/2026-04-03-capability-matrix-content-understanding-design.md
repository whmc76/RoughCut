# Capability Matrix Content Understanding Design

## Goal

把当前以 `content_profile` 为中心的内容理解链，重构成一个通用的、能力矩阵驱动的多模态理解框架。

这套框架要满足四个核心目标：

- `LLM` 是最终主题、主体、摘要、检索词的唯一裁决者
- `ASR` 与视觉理解并列为主证据，`OCR` 是强补充证据
- 运行时按 provider 能力矩阵选择正确路径，而不是把多种视觉方案混用
- 在保证准确率优先的前提下，把单条任务延迟控制在可接受范围

## Non-Goals

- 不做新的品类硬编码、品牌白名单或案例特判
- 不把联网搜索或数据库检索升级成主判层
- 不追求“所有任务固定多阶段重推理”；编排必须可自适应
- 不在本次重构里顺手重写渲染、包装、Telegram 审核等外围流程

## Current Problems

### 1. 证据层级不对

当前链路虽然会抽帧、跑 OCR、做视觉分类，但视觉结果主要以 `visual_hints` 形式进入后续推理，地位偏弱。  
这导致：

- 视频里主体明明在画面里被反复展示，系统仍过度依赖字幕/ASR
- 当 `ASR` 脏、漏、同音误识别时，视觉无法形成有效纠偏
- 视觉结果容易退化成“给规则补 hint”，而不是参与主判断

### 2. 路由方式不对

当前更接近“整条链绑一个 provider”，而不是按能力独立路由。  
实际正确需求是：

- 有原生多模态的 provider，直接让它做视觉理解
- 没有原生多模态但有视觉 MCP，就走 MCP
- 没有视觉能力，就明确降级，而不是假装看过图

### 3. 编排方式不对

当前理解链是局部补强式演进，不是清晰的多阶段编排。  
缺点：

- 难以说明每一步在消化什么证据
- 难以判定什么时候该做实体消歧，什么时候不该加时延
- 审核页也很难解释“系统是怎么从视频原始称呼走到最终结论的”

### 4. 输出层不够可审计

虽然已经引入 `observed / resolved` 的双层实体，但还需要进一步扩展到：

- 证据来源层
- 冲突层
- 路由层
- 编排层

否则后续继续升级时，仍容易滑回“看起来智能，实际上不可解释”的状态。

## Design Principles

### 1. Final Judgment Is LLM-Only

以下字段只能由 `LLM` 产出：

- `video_type`
- `content_domain`
- `primary_subject`
- `subject_entities`
- `video_theme`
- `summary`
- `hook_line`
- `engagement_question`
- `search_queries`

规则层、检索层、视觉层都不能直接写这些最终字段。

### 2. ASR And Vision Are Both Primary Evidence

证据强度顺序固定为：

1. `ASR / subtitle semantic evidence`
2. `visual semantic evidence`
3. `OCR semantic evidence`
4. `hybrid retrieval evidence`

这里的含义不是“视觉永远弱于 ASR”，而是默认情况下：

- 如果字幕明确说出了品牌/型号/产品名，ASR 是最直接证据
- 如果画面强烈展示某个主体，视觉应当具备纠偏 ASR 的能力
- OCR 在看得到包装、铭牌、标签时可以直接补品牌/型号
- 检索只做佐证与消歧，不做主判

### 3. Capability Matrix, Not Single Provider Binding

运行时按能力矩阵为每个能力位单独选 provider：

- `asr`
- `visual_understanding`
- `ocr`
- `hybrid_retrieval`
- `reasoning`
- `verification`

每个能力位只选一条执行路径，不混用多条视觉方案。

### 4. Adaptive Orchestration

默认走三阶段：

1. `fact extraction`
2. `final understanding`
3. `conflict verification`

只有在以下条件出现时，才升级到四阶段，插入 `entity resolution`：

- `observed_entities` 存在明显别名/音近候选
- `ASR / vision / OCR` 互相冲突
- `search_queries` 命中多个互斥实体
- `final understanding` 的主体结论置信度低但证据不弱

### 5. No Hardcoded Fallback

任一阶段失败只能：

- 保留已有结论
- 清空冲突字段
- 设置 `needs_review = true`

不能：

- 回退成预设品类
- 根据规则“帮忙改判”
- 把未知包装成看似具体的主题

## Target Architecture

### Stage 0: Capability Resolution

在任务进入内容理解链之前，先构建一次能力矩阵快照：

```json
{
  "asr": {"provider": "qwen3_asr", "mode": "native"},
  "visual_understanding": {"provider": "minimax", "mode": "native_multimodal"},
  "ocr": {"provider": "paddleocr", "mode": "native"},
  "hybrid_retrieval": {"provider": "mixed", "mode": "online_plus_internal"},
  "reasoning": {"provider": "minimax", "mode": "native_reasoning"},
  "verification": {"provider": "minimax", "mode": "native_reasoning"}
}
```

如果 `visual_understanding` 不支持原生多模态，但支持视觉 MCP，则：

```json
{
  "visual_understanding": {"provider": "mcp:minimax-vision", "mode": "mcp"}
}
```

这层能力矩阵进入 artifact、review trace 和 debug payload，供后续排查。

### Stage 1: Evidence Acquisition

这一步只负责采集与标准化证据，不做最终判断。

输出结构：

- `audio_semantic_evidence`
- `visual_semantic_evidence`
- `ocr_semantic_evidence`
- `source_metadata_evidence`

#### 1. Audio Semantic Evidence

来源：

- `transcript`
- `subtitle_items`
- `transcript_evidence`

输出：

- `observed_phrases`
- `brand_candidates`
- `model_candidates`
- `product_name_candidates`
- `product_type_candidates`
- `relationship_candidates`
- `phonetic_candidates`
- `evidence_sentences`

#### 2. Visual Semantic Evidence

来源：

- 抽帧结果
- 原生多模态 provider 或视觉 MCP 返回结果

输出：

- `visual_subject_candidates`
- `object_categories`
- `interaction_type`
- `scene_context`
- `visible_brand_candidates`
- `visible_model_candidates`
- `visual_evidence_sentences`
- `frame_level_findings`

这里明确把视觉从 `visual_hints` 升级成 `visual_semantic_evidence`，不再只是辅助 hint。

#### 3. OCR Semantic Evidence

来源：

- `content_profile_ocr`
- 后续更通用的 OCR artifact

输出：

- `ocr_text_lines`
- `ocr_brand_candidates`
- `ocr_model_candidates`
- `ocr_product_name_candidates`
- `ocr_frame_refs`

### Stage 2: Fact Extraction

`reasoning` 能力位读取所有标准化证据，统一产出“事实层”，不直接给最终主题。

输出：

- `observed_entities`
- `observed_relations`
- `observed_product_names`
- `observed_aliases`
- `phonetic_candidates`
- `search_expansions`
- `fact_conflicts`
- `fact_confidence`

这里的目标是把“这是哪家的、叫什么、是什么类型、有没有联名”先抽成事实。

### Stage 3: Final Understanding

如果事实层没有明显冲突，则直接进入最终理解。

输出：

- `video_type`
- `content_domain`
- `primary_subject`
- `subject_entities`
- `video_theme`
- `summary`
- `hook_line`
- `engagement_question`
- `search_queries`
- `confidence`
- `needs_review`
- `review_reasons`

这一步默认仍保留：

- `observed_entities`
- `resolved_entities = []`
- `resolved_primary_subject = ""`
- `entity_resolution_map = []`

### Stage 4: Conditional Entity Resolution

只有在需要时才执行。

触发条件：

- `fact_conflicts` 非空
- `observed_entities` 存在 alias / transliteration / phonetic ambiguity
- `primary_subject` 置信度低于阈值
- 检索或内部实体库命中多个竞争实体

输入：

- `observed_entities`
- `search_expansions`
- `online_results`
- `database_results`

输出：

- `resolved_entities`
- `resolved_primary_subject`
- `entity_resolution_map`
- `resolution_conflicts`
- `resolution_confidence`

决策规则：

- 允许最终主结论采用 `resolved`
- 必须保留 `observed -> resolved` 映射
- 如果归一化证据不够强，则保持 `resolved` 为空或接近 `observed`

### Stage 5: Conflict Verification

最后由 `verification` 能力位对整条链做一次收口：

- 证据是否自洽
- `resolved` 是否越权
- 是否需要清空某些字段

这一步只能：

- 保留字段
- 清空字段
- 标记待审

不能：

- 生成新的主题
- 用规则改判主题

## Capability Matrix

### Provider Capability Schema

新增统一能力声明：

```json
{
  "provider": "minimax",
  "capabilities": {
    "asr": false,
    "reasoning": true,
    "verification": true,
    "multimodal_native": true,
    "visual_mcp": false,
    "ocr_native": false,
    "online_search": true,
    "internal_entity_search": false
  }
}
```

### Routing Rules

#### Visual Understanding

优先级：

1. `multimodal_native`
2. `visual_mcp`
3. unavailable

不能把 `multimodal_native` 和 `visual_mcp` 同时跑作同一层视觉主证据，除非后续单独设计 fallback retry。

#### Reasoning

优先选择：

- 支持强 JSON 输出
- 稳定支持长上下文
- 有较好的证据归纳能力

#### Verification

可以和 reasoning 是同一 provider，但逻辑上是独立能力位，便于后续分离。

## Data Contracts

### Evidence Artifact

新增统一 artifact：

- `content_understanding_evidence`

字段：

- `capability_matrix`
- `audio_semantic_evidence`
- `visual_semantic_evidence`
- `ocr_semantic_evidence`
- `source_metadata_evidence`
- `fact_layer`

### Final Artifact

`content_profile_draft` / `content_understanding` 至少包含：

- `observed_entities`
- `resolved_entities`
- `resolved_primary_subject`
- `entity_resolution_map`
- `conflicts`
- `capability_matrix`
- `orchestration_trace`

## Latency Strategy

为满足“准确率优先，但单条任务延迟可接受”，采用以下策略：

### 1. 默认三阶段

多数任务不进入实体消歧，减少一轮模型与检索开销。

### 2. 视觉抽帧数量升级，但控制上限

当前 `3` 帧不足。新策略建议：

- 默认 `5` 帧
- 长视频或主体切换明显时 `7` 帧
- 不做无限加帧

### 3. 检索只在必要时放大

默认：

- `search_queries <= 4`
- 只在 alias/音近冲突时增加扩展查询

### 4. 缓存分层

缓存至少分为：

- `evidence cache`
- `fact extraction cache`
- `final understanding cache`
- `entity resolution cache`

任何单层升级都必须 bump 自己的 cache version，不允许污染整条链。

## Migration Plan

### Phase 1

落 capability matrix schema 与 orchestration trace，不改变最终 UI 读取逻辑。

### Phase 2

把视觉从 `visual_hints` 提升为 `visual_semantic_evidence`，并接入 provider capability router。

### Phase 3

把 `fact extraction` 从 `content_understanding_infer` 中拆出，形成清晰的三阶段主链。

### Phase 4

引入条件化 `entity resolution`，并把 `resolved` 层彻底接到最终主结论。

### Phase 5

基于固定 benchmark 和 live 样本回归，清除剩余 legacy 主题推断路径。

## Benchmark And Validation

新的 benchmark 不能只覆盖一个视频。至少要覆盖：

- 包
- 手电
- 刀/工具
- 配件/材料

验证重点：

- 是否能从视觉证据中提取强主体
- 是否能在 `ASR` 弱时仍保持正确大类
- 是否在证据不足时保守待审
- 是否始终保留 `observed / resolved / conflicts`

## Risks

### 1. 视觉证据过度主导

如果视觉 prompt 不够克制，可能被背景道具或桌面元素误导。  
解决方式是让视觉阶段输出事实，不直接出最终主题。

### 2. Provider Routing 复杂度上升

能力矩阵会引入更多运行时分支。  
解决方式是统一能力 schema 与 orchestration trace，保证可审计。

### 3. 四阶段升级过多

如果实体消歧触发阈值太低，时延会明显上升。  
解决方式是默认三阶段，只在冲突时升级。

### 4. Legacy 兼容污染

旧的 `subject_type/video_theme` helper 仍可能偷偷越权。  
解决方式是在迁移期持续压缩 legacy 写权限，只允许它们消费新链结果。
